"""
FloatChat Metadata Generator Module

Computes dataset statistics and generates LLM summaries after ingestion.
Called after all profiles are written for a dataset.

Statistics computed:
- date_range_start / date_range_end: Earliest and latest timestamps
- float_count: Number of distinct floats (platform_number)
- profile_count: Total profiles written
- variable_list: All variable names found
- bbox: Bounding box polygon from PostGIS ST_ConvexHull

LLM Summary:
- Uses OpenAI GPT-4o if API key is configured
- Falls back to template string if LLM unavailable or fails
- LLM errors never fail the ingestion job
"""

from datetime import datetime
from typing import Optional

import structlog
from sqlalchemy import distinct, func, select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Dataset, Float, Measurement, Profile

logger = structlog.get_logger(__name__)


def compute_dataset_metadata(
    db: Session,
    dataset_id: int,
    job_id: Optional[str] = None,
) -> dict:
    """
    Compute metadata for a dataset from its ingested profiles.
    
    Args:
        db: Database session
        dataset_id: Dataset to compute metadata for
        job_id: Optional job ID for logging
    
    Returns:
        Dict with computed metadata fields
    """
    log = logger.bind(job_id=job_id, dataset_id=dataset_id) if job_id else logger.bind(dataset_id=dataset_id)
    
    log.info("metadata_computation_started")
    
    # Query profiles for this dataset
    profile_query = select(Profile).where(Profile.dataset_id == dataset_id)
    
    # Get date range
    date_range_result = db.execute(
        select(
            func.min(Profile.timestamp).label("date_start"),
            func.max(Profile.timestamp).label("date_end"),
        ).where(Profile.dataset_id == dataset_id)
    ).one()
    
    date_range_start = date_range_result.date_start
    date_range_end = date_range_result.date_end
    
    # Get float count (distinct platform_number)
    float_count = db.execute(
        select(func.count(distinct(Profile.platform_number))).where(
            Profile.dataset_id == dataset_id
        )
    ).scalar() or 0
    
    # Get profile count
    profile_count = db.execute(
        select(func.count(Profile.profile_id)).where(Profile.dataset_id == dataset_id)
    ).scalar() or 0
    
    # Compute bounding box using PostGIS
    bbox_wkt = None
    try:
        bbox_result = db.execute(
            text("""
                SELECT ST_AsText(ST_ConvexHull(ST_Collect(geom)))
                FROM profiles
                WHERE dataset_id = :dataset_id AND geom IS NOT NULL
            """),
            {"dataset_id": dataset_id},
        ).scalar()
        
        if bbox_result:
            bbox_wkt = bbox_result
    except Exception as e:
        log.warning("bbox_computation_failed", error=str(e))
    
    # Determine variables found by checking if any measurements have non-null values
    variable_list = []
    
    # Get profile IDs for this dataset
    profile_ids = db.execute(
        select(Profile.profile_id).where(Profile.dataset_id == dataset_id)
    ).scalars().all()
    
    if profile_ids:
        # Check which measurement columns have data
        var_check = db.execute(
            select(
                func.bool_or(Measurement.temperature.isnot(None)).label("has_temp"),
                func.bool_or(Measurement.salinity.isnot(None)).label("has_sal"),
                func.bool_or(Measurement.pressure.isnot(None)).label("has_pres"),
                func.bool_or(Measurement.dissolved_oxygen.isnot(None)).label("has_doxy"),
                func.bool_or(Measurement.chlorophyll.isnot(None)).label("has_chla"),
                func.bool_or(Measurement.nitrate.isnot(None)).label("has_nitrate"),
                func.bool_or(Measurement.ph.isnot(None)).label("has_ph"),
            ).where(Measurement.profile_id.in_(profile_ids))
        ).one()
        
        if var_check.has_pres:
            variable_list.append("PRES")
        if var_check.has_temp:
            variable_list.append("TEMP")
        if var_check.has_sal:
            variable_list.append("PSAL")
        if var_check.has_doxy:
            variable_list.append("DOXY")
        if var_check.has_chla:
            variable_list.append("CHLA")
        if var_check.has_nitrate:
            variable_list.append("NITRATE")
        if var_check.has_ph:
            variable_list.append("PH_IN_SITU_TOTAL")
    
    metadata = {
        "date_range_start": date_range_start,
        "date_range_end": date_range_end,
        "float_count": float_count,
        "profile_count": profile_count,
        "variable_list": sorted(variable_list),
        "bbox_wkt": bbox_wkt,
    }
    
    log.info(
        "metadata_computed",
        date_range_start=str(date_range_start) if date_range_start else None,
        date_range_end=str(date_range_end) if date_range_end else None,
        float_count=float_count,
        profile_count=profile_count,
        variables=variable_list,
    )
    
    return metadata


def generate_llm_summary(
    metadata: dict,
    dataset_name: Optional[str] = None,
    job_id: Optional[str] = None,
) -> str:
    """
    Generate an LLM summary of the dataset.
    
    Uses OpenAI GPT-4o if API key is configured.
    Falls back to template string if LLM unavailable.
    
    Args:
        metadata: Computed metadata dict
        dataset_name: Optional dataset name for context
        job_id: Optional job ID for logging
    
    Returns:
        Summary text (either from LLM or template)
    """
    log = logger.bind(job_id=job_id) if job_id else logger
    
    # Extract metadata fields
    date_start = metadata.get("date_range_start")
    date_end = metadata.get("date_range_end")
    float_count = metadata.get("float_count", 0)
    profile_count = metadata.get("profile_count", 0)
    variables = metadata.get("variable_list", [])
    
    # Format dates
    date_start_str = date_start.strftime("%Y-%m-%d") if date_start else "unknown"
    date_end_str = date_end.strftime("%Y-%m-%d") if date_end else "unknown"
    variables_str = ", ".join(variables) if variables else "unknown"
    
    # Fallback template
    fallback_summary = (
        f"Dataset contains {profile_count} profiles from {float_count} floats, "
        f"spanning {date_start_str} to {date_end_str}. Variables: {variables_str}."
    )
    
    # Check if OpenAI is configured
    if not settings.OPENAI_API_KEY:
        log.info("llm_summary_skipped_no_api_key")
        return fallback_summary
    
    # Try to generate LLM summary
    try:
        import openai
        
        client = openai.OpenAI(
            api_key=settings.OPENAI_API_KEY,
            timeout=settings.LLM_TIMEOUT_SECONDS,
        )
        
        prompt = f"""Write a 2-3 sentence plain-English summary of this oceanographic dataset for a researcher.

Dataset information:
- Name: {dataset_name or "ARGO Float Data"}
- Time period: {date_start_str} to {date_end_str}
- Number of floats: {float_count}
- Number of profiles: {profile_count}
- Variables measured: {variables_str}

The summary should be informative and suitable for a dataset catalog entry.
Do not include technical details like file formats or data quality flags."""
        
        response = client.chat.completions.create(
            model=settings.LLM_MODEL,
            messages=[
                {"role": "system", "content": "You are an oceanographic data assistant helping researchers understand ARGO float datasets."},
                {"role": "user", "content": prompt},
            ],
            max_tokens=200,
            temperature=0.7,
        )
        
        summary = response.choices[0].message.content.strip()
        
        log.info("llm_summary_generated", summary_length=len(summary))
        return summary
        
    except Exception as e:
        # LLM failure must never fail ingestion - use fallback
        log.warning(
            "llm_summary_failed_using_fallback",
            error=str(e),
        )
        return fallback_summary


def update_dataset_metadata(
    db: Session,
    dataset_id: int,
    job_id: Optional[str] = None,
) -> None:
    """
    Compute and update all metadata for a dataset.
    
    This is the main entry point - call after all profiles are written.
    
    Args:
        db: Database session
        dataset_id: Dataset to update
        job_id: Optional job ID for logging
    """
    log = logger.bind(job_id=job_id, dataset_id=dataset_id) if job_id else logger.bind(dataset_id=dataset_id)
    
    log.info("metadata_update_started")
    
    # Get the dataset record
    dataset = db.execute(
        select(Dataset).where(Dataset.dataset_id == dataset_id)
    ).scalar_one_or_none()
    
    if not dataset:
        log.error("dataset_not_found")
        return
    
    # Compute metadata
    metadata = compute_dataset_metadata(db, dataset_id, job_id)
    
    # Generate LLM summary
    summary = generate_llm_summary(
        metadata=metadata,
        dataset_name=dataset.name,
        job_id=job_id,
    )
    
    # Update the dataset record
    dataset.date_range_start = metadata["date_range_start"]
    dataset.date_range_end = metadata["date_range_end"]
    dataset.float_count = metadata["float_count"]
    dataset.profile_count = metadata["profile_count"]
    dataset.variable_list = metadata["variable_list"]
    dataset.summary_text = summary
    
    # Update bbox using raw SQL
    if metadata.get("bbox_wkt"):
        try:
            db.execute(
                text("""
                    UPDATE datasets 
                    SET bbox = ST_GeogFromText(:wkt)
                    WHERE dataset_id = :dataset_id
                """),
                {"wkt": metadata["bbox_wkt"], "dataset_id": dataset_id},
            )
        except Exception as e:
            log.warning("bbox_update_failed", error=str(e))
    
    db.flush()
    
    log.info(
        "metadata_update_complete",
        float_count=metadata["float_count"],
        profile_count=metadata["profile_count"],
        summary_length=len(summary),
    )


def get_dataset_summary(
    db: Session,
    dataset_id: int,
) -> Optional[dict]:
    """
    Get a summary of a dataset's metadata.
    
    Args:
        db: Database session
        dataset_id: Dataset ID
    
    Returns:
        Dict with dataset metadata or None if not found
    """
    dataset = db.execute(
        select(Dataset).where(Dataset.dataset_id == dataset_id)
    ).scalar_one_or_none()
    
    if not dataset:
        return None
    
    return {
        "dataset_id": dataset.dataset_id,
        "name": dataset.name,
        "source_filename": dataset.source_filename,
        "ingestion_date": dataset.ingestion_date.isoformat() if dataset.ingestion_date else None,
        "date_range_start": dataset.date_range_start.isoformat() if dataset.date_range_start else None,
        "date_range_end": dataset.date_range_end.isoformat() if dataset.date_range_end else None,
        "float_count": dataset.float_count,
        "profile_count": dataset.profile_count,
        "variable_list": dataset.variable_list,
        "summary_text": dataset.summary_text,
        "is_active": dataset.is_active,
    }
