"""Feature 15 baseline computation for seasonal anomaly detection."""

from __future__ import annotations

from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.dialects.postgresql import insert
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import AnomalyBaseline, Measurement, OceanRegion, Profile

logger = structlog.get_logger(__name__)

# Oceanographic variables supported by anomaly detectors.
BASELINE_VARIABLES: tuple[str, ...] = (
    "temperature",
    "salinity",
    "dissolved_oxygen",
    "chlorophyll",
    "nitrate",
    "ph",
    "bbp700",
    "downwelling_irradiance",
)


def compute_all_baselines(db: Session) -> dict[str, Any]:
    """
    Compute and upsert monthly regional baselines for all supported variables.

    Returns a summary dict suitable for logs/API responses.
    """
    min_samples = settings.ANOMALY_SEASONAL_MIN_SAMPLES

    regions = db.execute(
        select(OceanRegion).order_by(OceanRegion.region_name.asc())
    ).scalars().all()

    summary: dict[str, Any] = {
        "regions_total": len(regions),
        "variables_total": len(BASELINE_VARIABLES),
        "combinations_total": 0,
        "upserts": 0,
        "skipped_no_data": 0,
        "skipped_low_samples": 0,
        "errors": 0,
        "min_samples": min_samples,
    }

    log = logger.bind(
        regions_total=summary["regions_total"],
        variables_total=summary["variables_total"],
        min_samples=min_samples,
    )
    log.info("baseline_compute_started")

    for region in regions:
        region_name = region.region_name
        for variable in BASELINE_VARIABLES:
            for month in range(1, 13):
                summary["combinations_total"] += 1

                try:
                    value_col = getattr(Measurement, variable)

                    stats_stmt = (
                        select(
                            func.avg(value_col).label("mean_value"),
                            func.stddev_pop(value_col).label("std_dev"),
                            func.count(value_col).label("sample_count"),
                        )
                        .select_from(Measurement)
                        .join(Profile, Measurement.profile_id == Profile.profile_id)
                        .where(
                            Measurement.is_outlier.is_(False),
                            value_col.is_not(None),
                            Profile.timestamp.is_not(None),
                            Profile.geom.is_not(None),
                            func.ST_Within(Profile.geom, region.geom),
                            func.extract("month", Profile.timestamp) == month,
                        )
                    )

                    row = db.execute(stats_stmt).one()
                    sample_count = int(row.sample_count or 0)

                    if sample_count == 0:
                        summary["skipped_no_data"] += 1
                        continue

                    if sample_count < min_samples:
                        summary["skipped_low_samples"] += 1
                        continue

                    mean_value = float(row.mean_value)
                    std_dev = float(row.std_dev or 0.0)

                    upsert_stmt = insert(AnomalyBaseline).values(
                        region=region_name,
                        variable=variable,
                        month=month,
                        mean_value=mean_value,
                        std_dev=std_dev,
                        sample_count=sample_count,
                    )
                    upsert_stmt = upsert_stmt.on_conflict_do_update(
                        index_elements=["region", "variable", "month"],
                        set_={
                            "mean_value": mean_value,
                            "std_dev": std_dev,
                            "sample_count": sample_count,
                            "computed_at": func.now(),
                        },
                    )

                    db.execute(upsert_stmt)
                    summary["upserts"] += 1

                except Exception as exc:
                    summary["errors"] += 1
                    logger.error(
                        "baseline_compute_combo_failed",
                        region=region_name,
                        variable=variable,
                        month=month,
                        error=str(exc),
                    )

    log.info("baseline_compute_complete", **summary)
    return summary
