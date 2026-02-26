"""
FloatChat Discovery Module

Float discovery, fuzzy region name matching, and dataset summary functions.

Functions:
    resolve_region_name        — Fuzzy match a region name via pg_trgm (Hard Rule #7)
    discover_floats_by_region  — Spatial float lookup within a named region
    discover_floats_by_variable — Float lookup by measured variable
    get_dataset_summary        — Rich summary dict for a single dataset
    get_all_summaries          — Lightweight summary cards for all active datasets

Rules:
    - resolve_region_name is the SOLE point for region name resolution (Hard Rule #7)
    - No other function may query ocean_regions by name directly
    - Fuzzy matching uses pg_trgm similarity() function
    - Summaries never return inactive datasets
"""

import time
from typing import Any, Optional

import structlog
from geoalchemy2.functions import ST_AsGeoJSON, ST_Within
from sqlalchemy import Double, func, select, text
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    Dataset,
    Float,
    Measurement,
    OceanRegion,
    Profile,
    mv_float_latest_position,
)

logger = structlog.get_logger(__name__)

# Allowed variable names for discover_floats_by_variable
_ALLOWED_VARIABLES = {
    "temperature",
    "salinity",
    "dissolved_oxygen",
    "chlorophyll",
    "nitrate",
    "ph",
}


# ── Region Name Resolution ────────────────────────────────────────────────


def resolve_region_name(region_name: str, db: Session) -> OceanRegion:
    """
    Fuzzy-match a region name against the ocean_regions table using pg_trgm.

    This is the SOLE entry point for region name resolution (Hard Rule #7).
    No other function may query ocean_regions by name directly.

    Uses PostgreSQL's pg_trgm similarity() function to find the best match.
    If the best match score >= FUZZY_MATCH_THRESHOLD, returns the matching
    OceanRegion object. Otherwise raises ValueError with the top 3 closest
    suggestions.

    Args:
        region_name: The region name string to resolve (may be informal).
        db: SQLAlchemy session.

    Returns:
        The matching OceanRegion ORM object.

    Raises:
        ValueError: If no match meets the fuzzy threshold, with suggestions.
    """
    start_time = time.time()

    # Query all regions with their similarity score, ordered desc
    similarity_col = func.similarity(
        OceanRegion.region_name, region_name
    ).label("sim_score")

    stmt = (
        select(OceanRegion, similarity_col)
        .order_by(similarity_col.desc())
        .limit(5)
    )

    rows = db.execute(stmt).all()

    if not rows:
        raise ValueError(
            f"Region '{region_name}' not found. No ocean regions exist in the database."
        )

    best_region, best_score = rows[0]

    elapsed = round(time.time() - start_time, 3)
    logger.info(
        "resolve_region_name",
        input_name=region_name,
        matched_name=best_region.region_name,
        similarity_score=round(float(best_score), 4),
        elapsed_seconds=elapsed,
    )

    if float(best_score) >= settings.FUZZY_MATCH_THRESHOLD:
        return best_region

    # No match above threshold — build suggestion list from top 3
    suggestions = [row[0].region_name for row in rows[:3]]
    suggestions_str = ", ".join(f"'{s}'" for s in suggestions)
    raise ValueError(
        f"Region '{region_name}' not found. Did you mean: {suggestions_str}?"
    )


# ── Float Discovery ───────────────────────────────────────────────────────


def discover_floats_by_region(
    region_name: str,
    float_type: Optional[str],
    db: Session,
) -> list[dict[str, Any]]:
    """
    Discover floats whose latest position falls within a named ocean region.

    Resolves the region name via resolve_region_name (Hard Rule #7), then
    queries mv_float_latest_position with ST_Within against the region polygon.
    Optionally filters by float_type by joining the floats table.

    Args:
        region_name: The region name to search within (fuzzy-matched).
        float_type: Optional filter — 'core', 'BGC', or 'deep'.
        db: SQLAlchemy session.

    Returns:
        List of dicts with float metadata: platform_number, float_id,
        float_type, latitude, longitude, last_seen, cycle_number.

    Raises:
        ValueError: If region name cannot be resolved.
    """
    start_time = time.time()

    # Resolve region name → polygon (Hard Rule #7)
    region = resolve_region_name(region_name, db)

    # Query mv_float_latest_position for floats within the region
    mv = mv_float_latest_position

    stmt = (
        select(
            mv.c.platform_number,
            mv.c.float_id,
            mv.c.cycle_number,
            mv.c.timestamp,
            mv.c.latitude,
            mv.c.longitude,
        )
        .where(
            ST_Within(mv.c.geom, region.geom)
        )
    )

    # Optionally filter by float_type via join to floats table
    if float_type:
        stmt = (
            stmt.join(Float, mv.c.float_id == Float.float_id)
            .where(Float.float_type == float_type)
            .add_columns(Float.float_type)
        )
    else:
        # Still join to get float_type for the response
        stmt = (
            stmt.join(Float, mv.c.float_id == Float.float_id)
            .add_columns(Float.float_type)
        )

    rows = db.execute(stmt).all()

    results = []
    for row in rows:
        results.append({
            "platform_number": row.platform_number,
            "float_id": row.float_id,
            "float_type": row.float_type,
            "latitude": row.latitude,
            "longitude": row.longitude,
            "last_seen": row.timestamp.isoformat() if row.timestamp else None,
            "cycle_number": row.cycle_number,
        })

    elapsed = round(time.time() - start_time, 3)
    logger.info(
        "discover_floats_by_region",
        region_name=region_name,
        resolved_region=region.region_name,
        float_type=float_type,
        result_count=len(results),
        elapsed_seconds=elapsed,
    )

    return results


def discover_floats_by_variable(
    variable_name: str,
    db: Session,
) -> list[dict[str, Any]]:
    """
    Discover floats that have at least one non-null measurement for a variable.

    Validates the variable name against the allowed list. Queries measurements
    joined to profiles and floats to find distinct floats with at least one
    non-null value for the requested variable.

    Args:
        variable_name: One of: temperature, salinity, dissolved_oxygen,
                       chlorophyll, nitrate, ph.
        db: SQLAlchemy session.

    Returns:
        List of dicts with float metadata.

    Raises:
        ValueError: If variable_name is not in the allowed list.
    """
    start_time = time.time()

    if variable_name not in _ALLOWED_VARIABLES:
        raise ValueError(
            f"Unsupported variable: '{variable_name}'. "
            f"Must be one of: {', '.join(sorted(_ALLOWED_VARIABLES))}"
        )

    # Get the measurement column for this variable
    var_col = getattr(Measurement, variable_name)

    # Find distinct float_ids that have at least one non-null measurement
    float_ids_subquery = (
        select(Float.float_id)
        .join(Profile, Float.float_id == Profile.float_id)
        .join(Measurement, Profile.profile_id == Measurement.profile_id)
        .where(var_col.isnot(None))
        .distinct()
        .subquery()
    )

    stmt = select(Float).where(Float.float_id.in_(select(float_ids_subquery.c.float_id)))
    floats = db.execute(stmt).scalars().all()

    results = []
    for f in floats:
        results.append({
            "float_id": f.float_id,
            "platform_number": f.platform_number,
            "float_type": f.float_type,
            "deployment_lat": f.deployment_lat,
            "deployment_lon": f.deployment_lon,
            "deployment_date": (
                f.deployment_date.isoformat() if f.deployment_date else None
            ),
            "country": f.country,
            "program": f.program,
        })

    elapsed = round(time.time() - start_time, 3)
    logger.info(
        "discover_floats_by_variable",
        variable_name=variable_name,
        result_count=len(results),
        elapsed_seconds=elapsed,
    )

    return results


# ── Dataset Summaries ─────────────────────────────────────────────────────


def get_dataset_summary(dataset_id: int, db: Session) -> dict[str, Any]:
    """
    Return a rich summary for a single dataset (FR-22).

    Includes: name, summary_text, date_range_start, date_range_end,
    float_count, profile_count, variable_list, bbox as GeoJSON, is_active.

    Raises ValueError if the dataset is not found or is inactive.

    Args:
        dataset_id: Primary key of the dataset.
        db: SQLAlchemy session.

    Returns:
        A dict with all summary fields.

    Raises:
        ValueError: If dataset not found or is_active is False.
    """
    start_time = time.time()

    dataset = db.execute(
        select(Dataset).where(Dataset.dataset_id == dataset_id)
    ).scalar_one_or_none()

    if dataset is None:
        raise ValueError(f"Dataset not found: {dataset_id}")

    if not dataset.is_active:
        raise ValueError(f"Dataset is inactive: {dataset_id}")

    # Convert bbox to GeoJSON if present
    bbox_geojson = None
    if dataset.bbox is not None:
        geojson_result = db.execute(
            select(ST_AsGeoJSON(dataset.bbox))
        ).scalar()
        if geojson_result:
            import json
            bbox_geojson = json.loads(geojson_result)

    result = {
        "dataset_id": dataset.dataset_id,
        "name": dataset.name,
        "summary_text": dataset.summary_text,
        "date_range_start": (
            dataset.date_range_start.isoformat() if dataset.date_range_start else None
        ),
        "date_range_end": (
            dataset.date_range_end.isoformat() if dataset.date_range_end else None
        ),
        "float_count": dataset.float_count,
        "profile_count": dataset.profile_count,
        "variable_list": dataset.variable_list,
        "bbox": bbox_geojson,
        "is_active": dataset.is_active,
    }

    elapsed = round(time.time() - start_time, 3)
    logger.info(
        "get_dataset_summary",
        dataset_id=dataset_id,
        elapsed_seconds=elapsed,
    )

    return result


def get_all_summaries(db: Session) -> list[dict[str, Any]]:
    """
    Return lightweight summary cards for all active datasets (FR-23).

    Ordered by ingestion_date descending. Truncates summary_text to 300
    characters. Never returns inactive datasets. No pagination for v1.

    Args:
        db: SQLAlchemy session.

    Returns:
        List of summary dicts with: dataset_id, name, summary_text (truncated),
        float_count, date_range_start, date_range_end, variable_list.
    """
    start_time = time.time()

    stmt = (
        select(Dataset)
        .where(Dataset.is_active == True)  # noqa: E712
        .order_by(Dataset.ingestion_date.desc())
    )
    datasets = db.execute(stmt).scalars().all()

    results = []
    for ds in datasets:
        summary = ds.summary_text or ""
        if len(summary) > 300:
            summary = summary[:300]

        results.append({
            "dataset_id": ds.dataset_id,
            "name": ds.name,
            "summary_text": summary,
            "float_count": ds.float_count,
            "date_range_start": (
                ds.date_range_start.isoformat() if ds.date_range_start else None
            ),
            "date_range_end": (
                ds.date_range_end.isoformat() if ds.date_range_end else None
            ),
            "variable_list": ds.variable_list,
        })

    elapsed = round(time.time() - start_time, 3)
    logger.info(
        "get_all_summaries",
        result_count=len(results),
        elapsed_seconds=elapsed,
    )

    return results
