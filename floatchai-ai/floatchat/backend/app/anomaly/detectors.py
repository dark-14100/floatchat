"""Feature 15 anomaly detectors."""

from __future__ import annotations

import calendar
from dataclasses import dataclass
from datetime import UTC, datetime
import math
from typing import Any, Optional

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import Anomaly, AnomalyBaseline, Measurement, OceanRegion, Profile

logger = structlog.get_logger(__name__)

DETECTOR_VARIABLES: tuple[str, ...] = (
    "temperature",
    "salinity",
    "dissolved_oxygen",
    "chlorophyll",
    "nitrate",
    "ph",
    "bbp700",
    "downwelling_irradiance",
)

VARIABLE_UNITS: dict[str, str] = {
    "temperature": "degC",
    "salinity": "PSU",
    "dissolved_oxygen": "umol/kg",
    "chlorophyll": "mg/m3",
    "nitrate": "umol/kg",
    "ph": "pH",
    "bbp700": "m-1",
    "downwelling_irradiance": "W/m2/nm",
}


@dataclass
class _ClusterPoint:
    anomaly: Anomaly
    latitude: float
    longitude: float
    detected_at: datetime


class BaseDetector:
    """Base detector contract used by all anomaly detectors."""

    anomaly_type: str = ""

    def run(self, profiles: list[Profile], db: Session) -> list[Anomaly]:
        raise NotImplementedError


def _severity_from_zscore(z_score: float) -> Optional[str]:
    """Convert absolute z-score to severity bucket."""
    if z_score < 1.5:
        return None
    if z_score < 2.0:
        return "low"
    if z_score < 3.0:
        return "medium"
    return "high"


def _safe_deviation_percent(observed: float, baseline: float) -> float:
    """Compute percentage deviation safely for zero baselines."""
    if baseline == 0:
        return 0.0
    return abs((observed - baseline) / baseline) * 100.0


def _direction_text(observed: float, baseline: float) -> str:
    """Return above/below relative direction text."""
    return "above" if observed >= baseline else "below"


def _haversine_km(lat1: float, lon1: float, lat2: float, lon2: float) -> float:
    """Great-circle distance in kilometers between two points."""
    radius_km = 6371.0088

    phi1 = math.radians(lat1)
    phi2 = math.radians(lat2)
    delta_phi = math.radians(lat2 - lat1)
    delta_lambda = math.radians(lon2 - lon1)

    a = (
        math.sin(delta_phi / 2.0) ** 2
        + math.cos(phi1) * math.cos(phi2) * math.sin(delta_lambda / 2.0) ** 2
    )
    c = 2.0 * math.atan2(math.sqrt(a), math.sqrt(1.0 - a))
    return radius_km * c


def _within_window(a: datetime, b: datetime, window_days: int) -> bool:
    """Return True when two timestamps are within the configured day window."""
    seconds = abs((a - b).total_seconds())
    return seconds <= float(window_days * 86400)


def _get_profile_observed_values(db: Session, profile_id: int) -> dict[str, float]:
    """Return per-variable observed values for one profile, excluding QC outliers."""
    avg_columns = [func.avg(getattr(Measurement, var)).label(var) for var in DETECTOR_VARIABLES]

    row = db.execute(
        select(*avg_columns).where(
            Measurement.profile_id == profile_id,
            Measurement.is_outlier.is_(False),
        )
    ).one()

    observed: dict[str, float] = {}
    for var in DETECTOR_VARIABLES:
        value = getattr(row, var)
        if value is not None:
            observed[var] = float(value)
    return observed


def _anomaly_exists(db: Session, profile_id: int, anomaly_type: str, variable: str) -> bool:
    """Check persisted anomaly dedup key existence."""
    existing_id = db.execute(
        select(Anomaly.anomaly_id)
        .where(
            Anomaly.profile_id == profile_id,
            Anomaly.anomaly_type == anomaly_type,
            Anomaly.variable == variable,
        )
        .limit(1)
    ).scalar_one_or_none()
    return existing_id is not None


def _resolve_nearest_region_name(db: Session, profile: Profile) -> Optional[str]:
    """Resolve nearest ocean region for a profile geometry."""
    if profile.geom is None:
        return None

    return db.execute(
        select(OceanRegion.region_name)
        .where(OceanRegion.geom.is_not(None))
        .order_by(func.ST_Distance(profile.geom, OceanRegion.geom))
        .limit(1)
    ).scalar_one_or_none()


class SpatialBaselineDetector(BaseDetector):
    """Detect anomalies relative to nearby profiles in the same calendar month."""

    anomaly_type = "spatial_baseline"

    def run(self, profiles: list[Profile], db: Session) -> list[Anomaly]:
        anomalies: list[Anomaly] = []
        local_keys: set[tuple[int, str, str]] = set()

        try:
            radius_meters = settings.ANOMALY_SPATIAL_RADIUS_KM * 1000.0
            min_profiles = settings.ANOMALY_SPATIAL_MIN_PROFILES
            threshold_std = settings.ANOMALY_SPATIAL_THRESHOLD_STD

            for profile in profiles:
                try:
                    if profile.geom is None or profile.timestamp is None:
                        continue

                    observed_values = _get_profile_observed_values(db, profile.profile_id)
                    if not observed_values:
                        continue

                    month = int(profile.timestamp.month)
                    month_name = calendar.month_name[month]

                    for variable, observed in observed_values.items():
                        value_col = getattr(Measurement, variable)

                        stats_row = db.execute(
                            select(
                                func.avg(value_col).label("baseline"),
                                func.stddev_pop(value_col).label("std_dev"),
                                func.count(func.distinct(Profile.profile_id)).label("comparison_profiles"),
                            )
                            .select_from(Measurement)
                            .join(Profile, Measurement.profile_id == Profile.profile_id)
                            .where(
                                Measurement.is_outlier.is_(False),
                                value_col.is_not(None),
                                Profile.geom.is_not(None),
                                Profile.timestamp.is_not(None),
                                Profile.profile_id != profile.profile_id,
                                func.extract("month", Profile.timestamp) == month,
                                func.ST_DWithin(Profile.geom, profile.geom, radius_meters),
                            )
                        ).one()

                        comparison_profiles = int(stats_row.comparison_profiles or 0)
                        if comparison_profiles < min_profiles:
                            continue

                        baseline = stats_row.baseline
                        std_dev = stats_row.std_dev
                        if baseline is None or std_dev is None or float(std_dev) <= 0.0:
                            continue

                        baseline = float(baseline)
                        std_dev = float(std_dev)
                        z_score = abs((observed - baseline) / std_dev)

                        if z_score <= threshold_std:
                            continue

                        severity = _severity_from_zscore(z_score)
                        if severity is None:
                            continue

                        dedup_key = (profile.profile_id, self.anomaly_type, variable)
                        if dedup_key in local_keys or _anomaly_exists(db, *dedup_key):
                            continue

                        unit = VARIABLE_UNITS.get(variable, "")
                        deviation_percent = _safe_deviation_percent(observed, baseline)
                        anomaly = Anomaly(
                            float_id=profile.float_id,
                            profile_id=profile.profile_id,
                            anomaly_type=self.anomaly_type,
                            severity=severity,
                            variable=variable,
                            baseline_value=baseline,
                            observed_value=observed,
                            deviation_percent=deviation_percent,
                            description=(
                                f"{variable} reading of {observed:.3f} {unit} is "
                                f"{deviation_percent:.2f}% {_direction_text(observed, baseline)} the regional "
                                f"mean of {baseline:.3f} {unit} for {month_name} "
                                f"(based on {comparison_profiles} nearby profiles)."
                            ),
                            detected_at=datetime.now(UTC),
                            region=_resolve_nearest_region_name(db, profile),
                        )

                        anomalies.append(anomaly)
                        local_keys.add(dedup_key)

                except Exception as exc:
                    logger.error(
                        "spatial_detector_profile_failed",
                        profile_id=profile.profile_id,
                        error=str(exc),
                    )

            logger.info(
                "spatial_detector_complete",
                profiles_scanned=len(profiles),
                anomalies_found=len(anomalies),
            )
            return anomalies

        except Exception as exc:
            logger.error("spatial_detector_failed", error=str(exc))
            return []


class FloatSelfComparisonDetector(BaseDetector):
    """Detect anomalies relative to the float's own historical profiles."""

    anomaly_type = "float_self_comparison"

    def run(self, profiles: list[Profile], db: Session) -> list[Anomaly]:
        anomalies: list[Anomaly] = []
        local_keys: set[tuple[int, str, str]] = set()

        try:
            history_limit = settings.ANOMALY_SELF_COMPARISON_HISTORY
            min_profiles = settings.ANOMALY_SELF_COMPARISON_MIN_PROFILES
            threshold_std = settings.ANOMALY_SELF_COMPARISON_THRESHOLD_STD

            for profile in profiles:
                try:
                    if profile.timestamp is None:
                        continue

                    observed_values = _get_profile_observed_values(db, profile.profile_id)
                    if not observed_values:
                        continue

                    historical_profile_ids = db.execute(
                        select(Profile.profile_id)
                        .where(
                            Profile.float_id == profile.float_id,
                            Profile.profile_id != profile.profile_id,
                            Profile.timestamp.is_not(None),
                            Profile.timestamp < profile.timestamp,
                        )
                        .order_by(Profile.timestamp.desc())
                        .limit(history_limit)
                    ).scalars().all()

                    if not historical_profile_ids:
                        continue

                    for variable, observed in observed_values.items():
                        value_col = getattr(Measurement, variable)

                        stats_row = db.execute(
                            select(
                                func.avg(value_col).label("baseline"),
                                func.stddev_pop(value_col).label("std_dev"),
                                func.count(func.distinct(Measurement.profile_id)).label("comparison_profiles"),
                            ).where(
                                Measurement.profile_id.in_(historical_profile_ids),
                                Measurement.is_outlier.is_(False),
                                value_col.is_not(None),
                            )
                        ).one()

                        comparison_profiles = int(stats_row.comparison_profiles or 0)
                        if comparison_profiles < min_profiles:
                            continue

                        baseline = stats_row.baseline
                        std_dev = stats_row.std_dev
                        if baseline is None or std_dev is None or float(std_dev) <= 0.0:
                            continue

                        baseline = float(baseline)
                        std_dev = float(std_dev)
                        z_score = abs((observed - baseline) / std_dev)

                        if z_score <= threshold_std:
                            continue

                        severity = _severity_from_zscore(z_score)
                        if severity is None:
                            continue

                        dedup_key = (profile.profile_id, self.anomaly_type, variable)
                        if dedup_key in local_keys or _anomaly_exists(db, *dedup_key):
                            continue

                        deviation_percent = _safe_deviation_percent(observed, baseline)
                        anomaly = Anomaly(
                            float_id=profile.float_id,
                            profile_id=profile.profile_id,
                            anomaly_type=self.anomaly_type,
                            severity=severity,
                            variable=variable,
                            baseline_value=baseline,
                            observed_value=observed,
                            deviation_percent=deviation_percent,
                            description=(
                                f"{variable} reading of {observed:.3f} is {deviation_percent:.2f}% "
                                f"{_direction_text(observed, baseline)} this float's recent mean of "
                                f"{baseline:.3f} (based on last {comparison_profiles} profiles)."
                            ),
                            detected_at=datetime.now(UTC),
                            region=_resolve_nearest_region_name(db, profile),
                        )

                        anomalies.append(anomaly)
                        local_keys.add(dedup_key)

                except Exception as exc:
                    logger.error(
                        "self_comparison_detector_profile_failed",
                        profile_id=profile.profile_id,
                        error=str(exc),
                    )

            logger.info(
                "self_comparison_detector_complete",
                profiles_scanned=len(profiles),
                anomalies_found=len(anomalies),
            )
            return anomalies

        except Exception as exc:
            logger.error("self_comparison_detector_failed", error=str(exc))
            return []


class SeasonalBaselineDetector(BaseDetector):
    """Detect anomalies relative to pre-computed seasonal regional baselines."""

    anomaly_type = "seasonal_baseline"

    def run(self, profiles: list[Profile], db: Session) -> list[Anomaly]:
        anomalies: list[Anomaly] = []
        local_keys: set[tuple[int, str, str]] = set()

        try:
            min_samples = settings.ANOMALY_SEASONAL_MIN_SAMPLES
            threshold_std = settings.ANOMALY_SEASONAL_THRESHOLD_STD

            for profile in profiles:
                try:
                    if profile.timestamp is None:
                        continue

                    region_name = _resolve_nearest_region_name(db, profile)
                    if not region_name:
                        continue

                    observed_values = _get_profile_observed_values(db, profile.profile_id)
                    if not observed_values:
                        continue

                    month = int(profile.timestamp.month)
                    month_name = calendar.month_name[month]

                    for variable, observed in observed_values.items():
                        baseline = db.execute(
                            select(AnomalyBaseline).where(
                                AnomalyBaseline.region == region_name,
                                AnomalyBaseline.variable == variable,
                                AnomalyBaseline.month == month,
                            )
                        ).scalar_one_or_none()

                        if baseline is None:
                            continue

                        if baseline.sample_count < min_samples:
                            continue

                        if baseline.std_dev is None or float(baseline.std_dev) <= 0.0:
                            continue

                        z_score = abs((observed - baseline.mean_value) / baseline.std_dev)
                        if z_score <= threshold_std:
                            continue

                        severity = _severity_from_zscore(z_score)
                        if severity is None:
                            continue

                        dedup_key = (profile.profile_id, self.anomaly_type, variable)
                        if dedup_key in local_keys or _anomaly_exists(db, *dedup_key):
                            continue

                        deviation_percent = _safe_deviation_percent(observed, baseline.mean_value)
                        anomaly = Anomaly(
                            float_id=profile.float_id,
                            profile_id=profile.profile_id,
                            anomaly_type=self.anomaly_type,
                            severity=severity,
                            variable=variable,
                            baseline_value=float(baseline.mean_value),
                            observed_value=observed,
                            deviation_percent=deviation_percent,
                            description=(
                                f"{variable} reading of {observed:.3f} is {deviation_percent:.2f}% "
                                f"outside the climatological {month_name} baseline of "
                                f"{baseline.mean_value:.3f} +/- {baseline.std_dev:.3f} for {region_name}."
                            ),
                            detected_at=datetime.now(UTC),
                            region=region_name,
                        )

                        anomalies.append(anomaly)
                        local_keys.add(dedup_key)

                except Exception as exc:
                    logger.error(
                        "seasonal_detector_profile_failed",
                        profile_id=profile.profile_id,
                        error=str(exc),
                    )

            logger.info(
                "seasonal_detector_complete",
                profiles_scanned=len(profiles),
                anomalies_found=len(anomalies),
            )
            return anomalies

        except Exception as exc:
            logger.error("seasonal_detector_failed", error=str(exc))
            return []


class ClusterPatternDetector(BaseDetector):
    """Detect clusters of anomalous floats in space/time for the same variable."""

    anomaly_type = "cluster_pattern"

    def run(
        self,
        profiles: list[Profile],
        db: Session,
        existing_anomalies: Optional[list[Anomaly]] = None,
    ) -> list[Anomaly]:
        anomalies: list[Anomaly] = []
        local_keys: set[tuple[int, str, str]] = set()

        try:
            source_anomalies = [
                a
                for a in (existing_anomalies or [])
                if a.anomaly_type in {
                    "spatial_baseline",
                    "float_self_comparison",
                    "seasonal_baseline",
                }
            ]
            if not source_anomalies:
                logger.info("cluster_detector_complete", profiles_scanned=0, anomalies_found=0)
                return []

            radius_km = float(settings.ANOMALY_CLUSTER_RADIUS_KM)
            window_days = int(settings.ANOMALY_CLUSTER_WINDOW_DAYS)
            min_floats = int(settings.ANOMALY_CLUSTER_MIN_FLOATS)
            now = datetime.now(UTC)

            profile_ids = [a.profile_id for a in source_anomalies]
            rows = db.execute(
                select(Profile.profile_id, Profile.latitude, Profile.longitude)
                .where(Profile.profile_id.in_(profile_ids))
            ).all()
            profile_lookup: dict[int, tuple[Optional[float], Optional[float]]] = {
                int(r.profile_id): (r.latitude, r.longitude) for r in rows
            }

            points_by_variable: dict[str, list[_ClusterPoint]] = {}
            for anomaly in source_anomalies:
                lat_lon = profile_lookup.get(int(anomaly.profile_id))
                if not lat_lon:
                    continue
                latitude, longitude = lat_lon
                if latitude is None or longitude is None:
                    continue

                points_by_variable.setdefault(anomaly.variable, []).append(
                    _ClusterPoint(
                        anomaly=anomaly,
                        latitude=float(latitude),
                        longitude=float(longitude),
                        detected_at=anomaly.detected_at or now,
                    )
                )

            for variable, points in points_by_variable.items():
                if len(points) < min_floats:
                    continue

                adjacency: dict[int, set[int]] = {i: set() for i in range(len(points))}

                for i in range(len(points)):
                    for j in range(i + 1, len(points)):
                        if not _within_window(points[i].detected_at, points[j].detected_at, window_days):
                            continue

                        dist_km = _haversine_km(
                            points[i].latitude,
                            points[i].longitude,
                            points[j].latitude,
                            points[j].longitude,
                        )
                        if dist_km <= radius_km:
                            adjacency[i].add(j)
                            adjacency[j].add(i)

                visited: set[int] = set()
                components: list[list[int]] = []

                for i in range(len(points)):
                    if i in visited:
                        continue
                    stack = [i]
                    component: list[int] = []
                    while stack:
                        node = stack.pop()
                        if node in visited:
                            continue
                        visited.add(node)
                        component.append(node)
                        stack.extend(adjacency[node] - visited)
                    components.append(component)

                for component in components:
                    comp_points = [points[idx] for idx in component]
                    float_ids = {p.anomaly.float_id for p in comp_points}
                    if len(float_ids) < min_floats:
                        continue

                    observed_values = [
                        p.anomaly.observed_value for p in comp_points if p.anomaly.observed_value is not None
                    ]
                    baseline_values = [
                        p.anomaly.baseline_value for p in comp_points if p.anomaly.baseline_value is not None
                    ]
                    mean_observed = float(sum(observed_values) / len(observed_values)) if observed_values else 0.0
                    if baseline_values:
                        mean_baseline = float(sum(baseline_values) / len(baseline_values))
                    else:
                        mean_baseline = mean_observed
                    deviation_percent = _safe_deviation_percent(mean_observed, mean_baseline)

                    latest_point_by_float: dict[int, _ClusterPoint] = {}
                    for point in comp_points:
                        existing_point = latest_point_by_float.get(point.anomaly.float_id)
                        if existing_point is None or point.detected_at > existing_point.detected_at:
                            latest_point_by_float[point.anomaly.float_id] = point

                    for float_id, point in latest_point_by_float.items():
                        dedup_key = (point.anomaly.profile_id, self.anomaly_type, variable)
                        if dedup_key in local_keys or _anomaly_exists(db, *dedup_key):
                            continue

                        cluster_anomaly = Anomaly(
                            float_id=float_id,
                            profile_id=point.anomaly.profile_id,
                            anomaly_type=self.anomaly_type,
                            severity="high",
                            variable=variable,
                            baseline_value=mean_baseline,
                            observed_value=mean_observed,
                            deviation_percent=deviation_percent,
                            description=(
                                f"Cluster of {len(float_ids)} floats within {int(radius_km)}km all "
                                f"showing anomalous {variable} readings within {window_days} days "
                                "- possible regional event."
                            ),
                            detected_at=now,
                            region=point.anomaly.region,
                        )

                        anomalies.append(cluster_anomaly)
                        local_keys.add(dedup_key)

            logger.info(
                "cluster_detector_complete",
                profiles_scanned=len(source_anomalies),
                anomalies_found=len(anomalies),
            )
            return anomalies

        except Exception as exc:
            logger.error("cluster_detector_failed", error=str(exc))
            return []
