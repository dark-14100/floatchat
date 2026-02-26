"""
FloatChat Data Access Layer (DAL)

The single module where all database queries live.  No other part of the
application is allowed to write raw SQL — everything goes through here.

Every public function:
    - Accepts a SQLAlchemy ``Session`` as the keyword argument ``db``.
    - Logs the function name and wall-clock execution time (ms) via structlog.
    - Returns plain Python dicts (never SQLAlchemy model instances).
    - Raises ``ValueError`` for invalid / missing inputs.
    - Raises ``RuntimeError`` for unexpected database errors.
"""

from __future__ import annotations

import time
from datetime import datetime
from typing import Any, Optional

import structlog
from geoalchemy2.functions import ST_DWithin, ST_Within
from redis import Redis
from sqlalchemy import func, select, text
from sqlalchemy.orm import Session

from app.cache.redis_cache import invalidate_all_query_cache
from app.db.models import (
    Dataset,
    Float,
    Measurement,
    OceanRegion,
    Profile,
    mv_dataset_stats,
    mv_float_latest_position,
)

logger = structlog.get_logger(__name__)

# ── Allowed variable names for get_profiles_with_variable ──────────────────
# Maps user-facing variable name → (measurement column, QC column)
_VARIABLE_MAP: dict[str, tuple[str, str]] = {
    "temperature": ("temperature", "temp_qc"),
    "salinity": ("salinity", "psal_qc"),
    "dissolved_oxygen": ("dissolved_oxygen", "doxy_qc"),
    "chlorophyll": ("chlorophyll", "chla_qc"),
    "nitrate": ("nitrate", "nitrate_qc"),
    "ph": ("ph", "ph_qc"),
}


# ── Helpers ────────────────────────────────────────────────────────────────

def _profile_to_dict(row: Profile) -> dict[str, Any]:
    """Convert a Profile ORM instance to a plain dict."""
    return {
        "profile_id": row.profile_id,
        "float_id": row.float_id,
        "platform_number": row.platform_number,
        "cycle_number": row.cycle_number,
        "timestamp": row.timestamp.isoformat() if row.timestamp else None,
        "latitude": row.latitude,
        "longitude": row.longitude,
        "position_invalid": row.position_invalid,
        "data_mode": row.data_mode,
        "dataset_id": row.dataset_id,
    }


def _measurement_to_dict(row: Measurement) -> dict[str, Any]:
    """Convert a Measurement ORM instance to a plain dict."""
    return {
        "measurement_id": row.measurement_id,
        "profile_id": row.profile_id,
        "pressure": row.pressure,
        "temperature": row.temperature,
        "salinity": row.salinity,
        "dissolved_oxygen": row.dissolved_oxygen,
        "chlorophyll": row.chlorophyll,
        "nitrate": row.nitrate,
        "ph": row.ph,
        "bbp700": row.bbp700,
        "downwelling_irradiance": row.downwelling_irradiance,
        "pres_qc": row.pres_qc,
        "temp_qc": row.temp_qc,
        "psal_qc": row.psal_qc,
        "doxy_qc": row.doxy_qc,
        "chla_qc": row.chla_qc,
        "nitrate_qc": row.nitrate_qc,
        "ph_qc": row.ph_qc,
        "is_outlier": row.is_outlier,
    }


def _dataset_to_dict(row: Dataset) -> dict[str, Any]:
    """Convert a Dataset ORM instance to a plain dict."""
    return {
        "dataset_id": row.dataset_id,
        "name": row.name,
        "source_filename": row.source_filename,
        "raw_file_path": row.raw_file_path,
        "ingestion_date": row.ingestion_date.isoformat() if row.ingestion_date else None,
        "date_range_start": row.date_range_start.isoformat() if row.date_range_start else None,
        "date_range_end": row.date_range_end.isoformat() if row.date_range_end else None,
        "float_count": row.float_count,
        "profile_count": row.profile_count,
        "variable_list": row.variable_list,
        "summary_text": row.summary_text,
        "is_active": row.is_active,
        "dataset_version": row.dataset_version,
    }


def _float_to_dict(row: Float) -> dict[str, Any]:
    """Convert a Float ORM instance to a plain dict."""
    return {
        "float_id": row.float_id,
        "platform_number": row.platform_number,
        "wmo_id": row.wmo_id,
        "float_type": row.float_type,
        "deployment_date": row.deployment_date.isoformat() if row.deployment_date else None,
        "deployment_lat": row.deployment_lat,
        "deployment_lon": row.deployment_lon,
        "country": row.country,
        "program": row.program,
    }


def _timed(fn_name: str, start: float) -> None:
    """Log elapsed time in milliseconds."""
    elapsed_ms = round((time.perf_counter() - start) * 1000, 2)
    logger.info("dal_query", function=fn_name, elapsed_ms=elapsed_ms)


# ── Public API ─────────────────────────────────────────────────────────────


def get_profiles_by_radius(
    lat: float,
    lon: float,
    radius_meters: float,
    start_date: Optional[datetime],
    end_date: Optional[datetime],
    *,
    db: Session,
) -> list[dict[str, Any]]:
    """
    Return profiles within *radius_meters* of (*lat*, *lon*), optionally
    filtered by a date range.  Only profiles with valid positions are included.

    Uses PostGIS ``ST_DWithin`` on the ``profiles.geom`` GEOGRAPHY column.
    """
    start = time.perf_counter()
    try:
        point_wkt = f"SRID=4326;POINT({lon} {lat})"
        stmt = (
            select(Profile)
            .where(Profile.position_invalid == False)  # noqa: E712
            .where(
                ST_DWithin(
                    Profile.geom,
                    func.ST_GeogFromText(point_wkt),
                    radius_meters,
                )
            )
        )
        if start_date is not None:
            stmt = stmt.where(Profile.timestamp >= start_date)
        if end_date is not None:
            stmt = stmt.where(Profile.timestamp <= end_date)

        stmt = stmt.order_by(Profile.timestamp.desc())
        rows = db.execute(stmt).scalars().all()
        return [_profile_to_dict(r) for r in rows]
    except ValueError:
        raise
    except Exception as exc:
        raise RuntimeError(f"get_profiles_by_radius failed: {exc}") from exc
    finally:
        _timed("get_profiles_by_radius", start)


def get_profiles_by_basin(
    region_name: str,
    start_date: Optional[datetime],
    end_date: Optional[datetime],
    *,
    db: Session,
) -> list[dict[str, Any]]:
    """
    Return profiles that fall within the named ocean region polygon.

    Raises ``ValueError`` if *region_name* is not found in ``ocean_regions``.
    """
    start = time.perf_counter()
    try:
        region = db.execute(
            select(OceanRegion).where(OceanRegion.region_name == region_name)
        ).scalar_one_or_none()

        if region is None:
            raise ValueError(f"Unknown ocean region: '{region_name}'")

        stmt = (
            select(Profile)
            .where(Profile.position_invalid == False)  # noqa: E712
            .where(ST_Within(Profile.geom, OceanRegion.geom))
            .where(OceanRegion.region_name == region_name)
        )
        if start_date is not None:
            stmt = stmt.where(Profile.timestamp >= start_date)
        if end_date is not None:
            stmt = stmt.where(Profile.timestamp <= end_date)

        stmt = stmt.order_by(Profile.timestamp.desc())
        rows = db.execute(stmt).scalars().all()
        return [_profile_to_dict(r) for r in rows]
    except ValueError:
        raise
    except Exception as exc:
        raise RuntimeError(f"get_profiles_by_basin failed: {exc}") from exc
    finally:
        _timed("get_profiles_by_basin", start)


def get_measurements_by_profile(
    profile_id: int,
    min_pressure: Optional[float] = None,
    max_pressure: Optional[float] = None,
    *,
    db: Session,
) -> list[dict[str, Any]]:
    """
    Return measurements for a given profile, optionally filtered by depth range.

    If both *min_pressure* and *max_pressure* are ``None`` all depth levels
    are returned.
    """
    start = time.perf_counter()
    try:
        stmt = select(Measurement).where(Measurement.profile_id == profile_id)

        if min_pressure is not None:
            stmt = stmt.where(Measurement.pressure >= min_pressure)
        if max_pressure is not None:
            stmt = stmt.where(Measurement.pressure <= max_pressure)

        stmt = stmt.order_by(Measurement.pressure.asc())
        rows = db.execute(stmt).scalars().all()
        return [_measurement_to_dict(r) for r in rows]
    except Exception as exc:
        raise RuntimeError(f"get_measurements_by_profile failed: {exc}") from exc
    finally:
        _timed("get_measurements_by_profile", start)


def get_float_latest_positions(*, db: Session) -> list[dict[str, Any]]:
    """
    Read directly from the ``mv_float_latest_position`` materialized view.

    Hard rule 7: never recompute inline — always read the MV.
    """
    start = time.perf_counter()
    try:
        stmt = select(mv_float_latest_position)
        rows = db.execute(stmt).fetchall()
        return [
            {
                "platform_number": r.platform_number,
                "float_id": r.float_id,
                "cycle_number": r.cycle_number,
                "timestamp": r.timestamp.isoformat() if r.timestamp else None,
                "latitude": r.latitude,
                "longitude": r.longitude,
            }
            for r in rows
        ]
    except Exception as exc:
        raise RuntimeError(f"get_float_latest_positions failed: {exc}") from exc
    finally:
        _timed("get_float_latest_positions", start)


def get_active_datasets(*, db: Session) -> list[dict[str, Any]]:
    """Return all datasets where ``is_active = TRUE``, newest first."""
    start = time.perf_counter()
    try:
        stmt = (
            select(Dataset)
            .where(Dataset.is_active == True)  # noqa: E712
            .order_by(Dataset.ingestion_date.desc())
        )
        rows = db.execute(stmt).scalars().all()
        return [_dataset_to_dict(r) for r in rows]
    except Exception as exc:
        raise RuntimeError(f"get_active_datasets failed: {exc}") from exc
    finally:
        _timed("get_active_datasets", start)


def get_dataset_by_id(dataset_id: int, *, db: Session) -> dict[str, Any]:
    """
    Return a single dataset by ID.

    Raises ``ValueError`` if no dataset with *dataset_id* exists.
    """
    start = time.perf_counter()
    try:
        row = db.execute(
            select(Dataset).where(Dataset.dataset_id == dataset_id)
        ).scalar_one_or_none()

        if row is None:
            raise ValueError(f"Dataset not found: {dataset_id}")

        return _dataset_to_dict(row)
    except ValueError:
        raise
    except Exception as exc:
        raise RuntimeError(f"get_dataset_by_id failed: {exc}") from exc
    finally:
        _timed("get_dataset_by_id", start)


def search_floats_by_type(float_type: str, *, db: Session) -> list[dict[str, Any]]:
    """Return all floats matching the given ``float_type`` (core / BGC / deep)."""
    start = time.perf_counter()
    try:
        stmt = select(Float).where(Float.float_type == float_type)
        rows = db.execute(stmt).scalars().all()
        return [_float_to_dict(r) for r in rows]
    except Exception as exc:
        raise RuntimeError(f"search_floats_by_type failed: {exc}") from exc
    finally:
        _timed("search_floats_by_type", start)


def get_profiles_with_variable(
    variable_name: str,
    *,
    db: Session,
) -> list[dict[str, Any]]:
    """
    Return profiles that have at least one non-null measurement for *variable_name*.

    Supported variables: temperature, salinity, dissolved_oxygen, chlorophyll,
    nitrate, ph.

    Raises ``ValueError`` for unsupported variable names.
    """
    if variable_name not in _VARIABLE_MAP:
        raise ValueError(
            f"Unsupported variable: '{variable_name}'. "
            f"Must be one of: {', '.join(sorted(_VARIABLE_MAP))}"
        )

    start = time.perf_counter()
    col_name, qc_col_name = _VARIABLE_MAP[variable_name]
    try:
        # Find profile IDs that have at least one non-null QC for the variable
        qc_col = getattr(Measurement, qc_col_name)
        sub = (
            select(Measurement.profile_id)
            .where(qc_col.isnot(None))
            .distinct()
            .subquery()
        )
        stmt = (
            select(Profile)
            .where(Profile.profile_id.in_(select(sub.c.profile_id)))
            .order_by(Profile.timestamp.desc())
        )
        rows = db.execute(stmt).scalars().all()
        return [_profile_to_dict(r) for r in rows]
    except Exception as exc:
        raise RuntimeError(f"get_profiles_with_variable failed: {exc}") from exc
    finally:
        _timed("get_profiles_with_variable", start)


def invalidate_query_cache(redis_client: Redis) -> int:
    """
    Clear all ``query_cache:*`` keys from Redis.

    Delegates to ``redis_cache.invalidate_all_query_cache``.

    Returns:
        The number of keys deleted.
    """
    start = time.perf_counter()
    try:
        return invalidate_all_query_cache(redis_client)
    finally:
        _timed("invalidate_query_cache", start)


def refresh_materialized_views(*, db: Session) -> None:
    """
    Refresh both materialized views concurrently.

    Should be called after each successful ingestion job completes.

    Note: ``CONCURRENTLY`` requires at least one row in the view and a
    unique index.  On first run (empty views) we fall back to a normal refresh.
    """
    start = time.perf_counter()
    views = ["mv_float_latest_position", "mv_dataset_stats"]
    try:
        for view in views:
            try:
                db.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view}"))
            except Exception:
                # CONCURRENTLY fails on empty views — fall back to normal refresh
                db.rollback()
                db.execute(text(f"REFRESH MATERIALIZED VIEW {view}"))
        db.commit()
        logger.info("materialized_views_refreshed", views=views)
    except Exception as exc:
        raise RuntimeError(f"refresh_materialized_views failed: {exc}") from exc
    finally:
        _timed("refresh_materialized_views", start)
