"""
FloatChat Database Writer Module

Handles all database write operations for the ingestion pipeline.
All operations are idempotent using upsert logic.

Key Design Decisions:
- Never calls db.commit() - only db.flush() to get generated IDs
- Caller (tasks.py) is responsible for transaction management
- Uses bulk_insert_mappings for measurements in batches
- PostGIS geometry created via shapely + geoalchemy2
"""

from datetime import datetime, timezone
from typing import Optional

import structlog
from geoalchemy2 import WKTElement
from shapely.geometry import Point
from sqlalchemy import delete, select, text
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    Dataset,
    Float,
    FloatPosition,
    IngestionJob,
    Measurement,
    Profile,
)
from app.ingestion.cleaner import CleanedMeasurement, CleaningResult
from app.ingestion.parser import FloatInfo, ParseResult, ProfileInfo

logger = structlog.get_logger(__name__)


def _create_point_geometry(latitude: float, longitude: float) -> WKTElement:
    """
    Create a PostGIS GEOGRAPHY point from lat/lon.
    
    Args:
        latitude: Latitude in degrees (-90 to 90)
        longitude: Longitude in degrees (-180 to 180)
    
    Returns:
        WKTElement for PostGIS GEOGRAPHY(POINT, 4326)
    """
    point = Point(longitude, latitude)  # Note: PostGIS uses (lon, lat) order
    return WKTElement(point.wkt, srid=4326)


def _is_valid_position(latitude: Optional[float], longitude: Optional[float]) -> bool:
    """Check if lat/lon are valid for PostGIS geometry."""
    if latitude is None or longitude is None:
        return False
    if latitude < -90 or latitude > 90:
        return False
    if longitude < -180 or longitude > 180:
        return False
    return True


def upsert_float(
    db: Session,
    platform_number: str,
    float_type: str = "core",
    wmo_id: Optional[str] = None,
    job_id: Optional[str] = None,
) -> int:
    """
    Upsert a float record.
    
    Uses INSERT ... ON CONFLICT DO NOTHING to avoid duplicates.
    If float exists, returns existing float_id.
    
    Args:
        db: Database session
        platform_number: ARGO platform number (WMO ID)
        float_type: 'core', 'BGC', or 'deep'
        wmo_id: WMO ID (usually same as platform_number)
        job_id: Optional job ID for logging
    
    Returns:
        float_id of the upserted/existing record
    """
    log = logger.bind(job_id=job_id) if job_id else logger
    
    # Use platform_number as wmo_id if not provided
    if wmo_id is None:
        wmo_id = platform_number
    
    # PostgreSQL INSERT ... ON CONFLICT DO NOTHING
    stmt = insert(Float).values(
        platform_number=platform_number,
        wmo_id=wmo_id,
        float_type=float_type,
    ).on_conflict_do_nothing(
        index_elements=["platform_number"]
    )
    
    db.execute(stmt)
    db.flush()
    
    # Fetch the float_id (whether newly inserted or existing)
    result = db.execute(
        select(Float.float_id).where(Float.platform_number == platform_number)
    ).scalar_one()
    
    log.debug(
        "float_upserted",
        platform_number=platform_number,
        float_id=result,
    )
    
    return result


def upsert_profile(
    db: Session,
    profile_info: ProfileInfo,
    float_info: FloatInfo,
    float_id: int,
    dataset_id: int,
    job_id: Optional[str] = None,
) -> int:
    """
    Upsert a profile record with PostGIS geometry.
    
    Uses INSERT ... ON CONFLICT DO UPDATE to handle re-ingestion.
    
    Args:
        db: Database session
        profile_info: Parsed profile metadata
        float_info: Parsed float metadata
        float_id: FK to floats table
        dataset_id: FK to datasets table
        job_id: Optional job ID for logging
    
    Returns:
        profile_id of the upserted record
    """
    log = logger.bind(job_id=job_id) if job_id else logger
    
    platform_number = float_info.wmo_id
    
    # Determine if position is valid for geometry
    position_invalid = not _is_valid_position(
        profile_info.latitude, profile_info.longitude
    )
    
    # Determine if timestamp is missing
    timestamp_missing = profile_info.timestamp is None
    
    # Build values dict
    values = {
        "float_id": float_id,
        "platform_number": platform_number,
        "cycle_number": profile_info.cycle_number,
        "latitude": profile_info.latitude,
        "longitude": profile_info.longitude,
        "position_invalid": position_invalid,
        "timestamp": profile_info.timestamp,
        "timestamp_missing": timestamp_missing,
        "data_mode": profile_info.direction if profile_info.direction in ("R", "A", "D") else "R",
        "dataset_id": dataset_id,
        "updated_at": datetime.now(timezone.utc),
    }
    
    # PostgreSQL INSERT ... ON CONFLICT DO UPDATE
    stmt = insert(Profile).values(**values)
    
    # On conflict, update all fields except platform_number and cycle_number
    update_dict = {
        "float_id": stmt.excluded.float_id,
        "latitude": stmt.excluded.latitude,
        "longitude": stmt.excluded.longitude,
        "position_invalid": stmt.excluded.position_invalid,
        "timestamp": stmt.excluded.timestamp,
        "timestamp_missing": stmt.excluded.timestamp_missing,
        "data_mode": stmt.excluded.data_mode,
        "dataset_id": stmt.excluded.dataset_id,
        "updated_at": stmt.excluded.updated_at,
    }
    
    stmt = stmt.on_conflict_do_update(
        constraint="uq_profiles_platform_cycle",
        set_=update_dict,
    )
    
    db.execute(stmt)
    db.flush()
    
    # Fetch the profile_id
    profile_id = db.execute(
        select(Profile.profile_id).where(
            Profile.platform_number == platform_number,
            Profile.cycle_number == profile_info.cycle_number,
        )
    ).scalar_one()
    
    # Update geometry separately using raw SQL (geoalchemy2 quirk with upserts)
    if not position_invalid:
        geom_wkt = f"POINT({profile_info.longitude} {profile_info.latitude})"
        db.execute(
            text(
                "UPDATE profiles SET geom = ST_GeogFromText(:wkt) WHERE profile_id = :pid"
            ),
            {"wkt": geom_wkt, "pid": profile_id},
        )
        db.flush()
    
    log.debug(
        "profile_upserted",
        profile_id=profile_id,
        platform_number=platform_number,
        cycle_number=profile_info.cycle_number,
    )
    
    return profile_id


def write_measurements(
    db: Session,
    profile_id: int,
    measurements: list[CleanedMeasurement],
    job_id: Optional[str] = None,
) -> int:
    """
    Write measurements for a profile using batch insert.
    
    Strategy:
    1. Delete all existing measurements for this profile
    2. Batch insert new measurements using bulk_insert_mappings
    
    This ensures measurements are always in sync after re-ingestion.
    
    Args:
        db: Database session
        profile_id: FK to profiles table
        measurements: List of cleaned measurements
        job_id: Optional job ID for logging
    
    Returns:
        Number of measurements written
    """
    log = logger.bind(job_id=job_id) if job_id else logger
    
    if not measurements:
        log.debug("no_measurements_to_write", profile_id=profile_id)
        return 0
    
    # Step 1: Delete existing measurements for this profile
    delete_stmt = delete(Measurement).where(Measurement.profile_id == profile_id)
    db.execute(delete_stmt)
    db.flush()
    
    # Step 2: Prepare measurement dicts for bulk insert
    measurement_dicts = []
    for m in measurements:
        measurement_dicts.append({
            "profile_id": profile_id,
            "pressure": m.pressure,
            "temperature": m.temperature,
            "salinity": m.salinity,
            "dissolved_oxygen": m.oxygen,
            "chlorophyll": m.chlorophyll_a,
            "nitrate": m.nitrate,
            "ph": m.ph,
            # QC flags - not in CleanedMeasurement, set to None
            "pres_qc": None,
            "temp_qc": None,
            "psal_qc": None,
            "doxy_qc": None,
            "chla_qc": None,
            "nitrate_qc": None,
            "ph_qc": None,
            # Outlier flag from cleaner
            "is_outlier": m.has_outlier,
        })
    
    # Step 3: Batch insert using bulk_insert_mappings
    batch_size = settings.DB_INSERT_BATCH_SIZE
    total_inserted = 0
    
    for i in range(0, len(measurement_dicts), batch_size):
        batch = measurement_dicts[i:i + batch_size]
        db.bulk_insert_mappings(Measurement, batch)
        total_inserted += len(batch)
        
        # Flush after each batch to free memory
        db.flush()
        
        log.debug(
            "measurement_batch_inserted",
            profile_id=profile_id,
            batch_start=i,
            batch_size=len(batch),
        )
    
    log.info(
        "measurements_written",
        profile_id=profile_id,
        count=total_inserted,
    )
    
    return total_inserted


def upsert_float_position(
    db: Session,
    profile_info: ProfileInfo,
    float_info: FloatInfo,
    job_id: Optional[str] = None,
) -> Optional[int]:
    """
    Upsert a float position record for the lightweight spatial index.
    
    This is a denormalized copy of profile positions for fast map queries.
    
    Args:
        db: Database session
        profile_info: Parsed profile metadata
        float_info: Parsed float metadata
        job_id: Optional job ID for logging
    
    Returns:
        position_id of the upserted record, or None if position invalid
    """
    log = logger.bind(job_id=job_id) if job_id else logger
    
    # Skip if position is invalid
    if not _is_valid_position(profile_info.latitude, profile_info.longitude):
        log.debug(
            "float_position_skipped_invalid",
            platform_number=float_info.wmo_id,
            cycle_number=profile_info.cycle_number,
        )
        return None
    
    platform_number = float_info.wmo_id
    
    values = {
        "platform_number": platform_number,
        "cycle_number": profile_info.cycle_number,
        "timestamp": profile_info.timestamp,
        "latitude": profile_info.latitude,
        "longitude": profile_info.longitude,
    }
    
    stmt = insert(FloatPosition).values(**values)
    
    update_dict = {
        "timestamp": stmt.excluded.timestamp,
        "latitude": stmt.excluded.latitude,
        "longitude": stmt.excluded.longitude,
    }
    
    stmt = stmt.on_conflict_do_update(
        constraint="uq_float_positions_platform_cycle",
        set_=update_dict,
    )
    
    db.execute(stmt)
    db.flush()
    
    # Fetch the position_id
    position_id = db.execute(
        select(FloatPosition.position_id).where(
            FloatPosition.platform_number == platform_number,
            FloatPosition.cycle_number == profile_info.cycle_number,
        )
    ).scalar_one()
    
    # Update geometry separately
    geom_wkt = f"POINT({profile_info.longitude} {profile_info.latitude})"
    db.execute(
        text(
            "UPDATE float_positions SET geom = ST_GeogFromText(:wkt) WHERE position_id = :pid"
        ),
        {"wkt": geom_wkt, "pid": position_id},
    )
    db.flush()
    
    log.debug(
        "float_position_upserted",
        position_id=position_id,
        platform_number=platform_number,
        cycle_number=profile_info.cycle_number,
    )
    
    return position_id


def write_dataset(
    db: Session,
    source_filename: str,
    raw_file_path: Optional[str] = None,
    name: Optional[str] = None,
    job_id: Optional[str] = None,
) -> int:
    """
    Create a new dataset record.
    
    Initial record with minimal data. Metadata (date_range, bbox, etc.)
    will be computed and updated by the metadata module after ingestion.
    
    Args:
        db: Database session
        source_filename: Original uploaded filename
        raw_file_path: S3 path where raw file is stored
        name: Optional dataset name
        job_id: Optional job ID for logging
    
    Returns:
        dataset_id of the created record
    """
    log = logger.bind(job_id=job_id) if job_id else logger
    
    dataset = Dataset(
        name=name or source_filename,
        source_filename=source_filename,
        raw_file_path=raw_file_path,
        ingestion_date=datetime.now(timezone.utc),
        is_active=True,
        dataset_version=1,
    )
    
    db.add(dataset)
    db.flush()
    
    log.info(
        "dataset_created",
        dataset_id=dataset.dataset_id,
        source_filename=source_filename,
    )
    
    return dataset.dataset_id


def write_ingestion_job(
    db: Session,
    dataset_id: int,
    original_filename: str,
    raw_file_path: Optional[str] = None,
) -> str:
    """
    Create a new ingestion job record.
    
    Args:
        db: Database session
        dataset_id: FK to datasets table
        original_filename: Original uploaded filename
        raw_file_path: S3 path where raw file is stored
    
    Returns:
        job_id (UUID as string)
    """
    job = IngestionJob(
        dataset_id=dataset_id,
        original_filename=original_filename,
        raw_file_path=raw_file_path,
        status="pending",
        progress_pct=0,
        profiles_ingested=0,
    )
    
    db.add(job)
    db.flush()
    
    job_id = str(job.job_id)
    
    logger.info(
        "ingestion_job_created",
        job_id=job_id,
        dataset_id=dataset_id,
        original_filename=original_filename,
    )
    
    return job_id


def update_job_status(
    db: Session,
    job_id: str,
    status: str,
    progress_pct: Optional[int] = None,
    profiles_total: Optional[int] = None,
    profiles_ingested: Optional[int] = None,
    error_log: Optional[str] = None,
    errors: Optional[list] = None,
) -> None:
    """
    Update an ingestion job's status and progress.
    
    Args:
        db: Database session
        job_id: Job UUID as string
        status: New status ('pending', 'running', 'succeeded', 'failed')
        progress_pct: Progress percentage (0-100)
        profiles_total: Total profiles to ingest
        profiles_ingested: Profiles ingested so far
        error_log: Error message text
        errors: List of error dicts for JSONB column
    """
    import uuid as uuid_module
    
    job = db.execute(
        select(IngestionJob).where(IngestionJob.job_id == uuid_module.UUID(job_id))
    ).scalar_one_or_none()
    
    if not job:
        logger.error("job_not_found", job_id=job_id)
        return
    
    job.status = status
    
    if progress_pct is not None:
        job.progress_pct = progress_pct
    
    if profiles_total is not None:
        job.profiles_total = profiles_total
    
    if profiles_ingested is not None:
        job.profiles_ingested = profiles_ingested
    
    if error_log is not None:
        job.error_log = error_log
    
    if errors is not None:
        job.errors = errors
    
    # Update timestamps based on status
    now = datetime.now(timezone.utc)
    if status == "running" and job.started_at is None:
        job.started_at = now
    elif status in ("succeeded", "failed"):
        job.completed_at = now
    
    db.flush()
    
    logger.info(
        "job_status_updated",
        job_id=job_id,
        status=status,
        progress_pct=progress_pct,
    )


def write_parse_result(
    db: Session,
    parse_result: ParseResult,
    cleaning_result: CleaningResult,
    dataset_id: int,
    job_id: Optional[str] = None,
) -> dict:
    """
    Write a complete parse result to the database.
    
    High-level function that orchestrates all writes for a single profile:
    1. Upsert float
    2. Upsert profile
    3. Write measurements
    4. Upsert float position
    
    Args:
        db: Database session
        parse_result: ParseResult from parser
        cleaning_result: CleaningResult from cleaner
        dataset_id: FK to datasets table
        job_id: Optional job ID for logging
    
    Returns:
        Dict with write statistics
    """
    log = logger.bind(job_id=job_id) if job_id else logger
    
    if not parse_result.success:
        log.warning(
            "write_skipped_failed_parse",
            error=parse_result.error_message,
        )
        return {"success": False, "error": parse_result.error_message}
    
    if not cleaning_result.success:
        log.warning(
            "write_skipped_failed_cleaning",
            error=cleaning_result.error_message,
        )
        return {"success": False, "error": cleaning_result.error_message}
    
    float_info = parse_result.float_info
    profile_info = parse_result.profile_info
    
    log.info(
        "db_write_started",
        platform_number=float_info.wmo_id,
        cycle_number=profile_info.cycle_number,
    )
    
    # 1. Upsert float
    float_id = upsert_float(
        db=db,
        platform_number=float_info.wmo_id,
        float_type=float_info.float_type,
        job_id=job_id,
    )
    
    # 2. Upsert profile
    profile_id = upsert_profile(
        db=db,
        profile_info=profile_info,
        float_info=float_info,
        float_id=float_id,
        dataset_id=dataset_id,
        job_id=job_id,
    )
    
    # 3. Write measurements
    measurement_count = write_measurements(
        db=db,
        profile_id=profile_id,
        measurements=cleaning_result.measurements,
        job_id=job_id,
    )
    
    # 4. Upsert float position
    position_id = upsert_float_position(
        db=db,
        profile_info=profile_info,
        float_info=float_info,
        job_id=job_id,
    )
    
    log.info(
        "db_write_complete",
        float_id=float_id,
        profile_id=profile_id,
        measurement_count=measurement_count,
        position_id=position_id,
    )
    
    return {
        "success": True,
        "float_id": float_id,
        "profile_id": profile_id,
        "measurement_count": measurement_count,
        "position_id": position_id,
    }
