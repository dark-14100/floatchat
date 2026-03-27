"""Feature 15 anomaly scanning Celery task."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from typing import Any, Callable

import structlog
from sqlalchemy import select

from app.anomaly.detectors import (
    ClusterPatternDetector,
    FloatSelfComparisonDetector,
    SeasonalBaselineDetector,
    SpatialBaselineDetector,
)
from app.celery_app import celery
from app.config import settings
from app.db.models import Anomaly, Profile
from app.db.session import SessionLocal
from app.monitoring.metrics import set_anomaly_scan_duration
from app.notifications.sender import notify

logger = structlog.get_logger(__name__)


def _notify_new_anomalies(created_anomalies: list[Anomaly]) -> None:
    """Best-effort anomaly notification dispatch via shared sender."""
    anomaly_count = len(created_anomalies)
    if anomaly_count == 0:
        return

    try:
        severity = _severity_breakdown(created_anomalies)
        notify(
            "anomalies_detected",
            {
                "anomaly_count": anomaly_count,
                "severity": severity,
            },
        )
    except Exception as exc:
        logger.warning("anomaly_notification_dispatch_failed", error=str(exc))


def _run_detector_safely(
    detector_name: str,
    run_fn: Callable[..., list[Anomaly]],
    *args: Any,
    **kwargs: Any,
) -> list[Anomaly]:
    """Run a detector with hard isolation: failures never stop scan execution."""
    try:
        rows = run_fn(*args, **kwargs)
        logger.info("anomaly_detector_complete", detector=detector_name, created=len(rows))
        return rows
    except Exception as exc:
        logger.error("anomaly_detector_failed", detector=detector_name, error=str(exc))
        return []


def _dedup_in_memory(anomalies: list[Anomaly]) -> list[Anomaly]:
    """Final dedup guard across detectors before insert."""
    deduped: list[Anomaly] = []
    seen: set[tuple[int, str, str]] = set()

    for anomaly in anomalies:
        key = (anomaly.profile_id, anomaly.anomaly_type, anomaly.variable)
        if key in seen:
            continue
        seen.add(key)
        deduped.append(anomaly)

    return deduped


def _severity_breakdown(anomalies: list[Anomaly]) -> dict[str, int]:
    """Count anomalies by severity bucket."""
    counts = {"low": 0, "medium": 0, "high": 0}
    for anomaly in anomalies:
        if anomaly.severity in counts:
            counts[anomaly.severity] += 1
    return counts


@celery.task(name="app.anomaly.tasks.run_anomaly_scan", bind=True, acks_late=True)
def run_anomaly_scan(self) -> dict[str, Any]:
    """Nightly anomaly scan across profiles ingested in the last 24 hours."""
    _ = self

    db = SessionLocal()
    started_at = datetime.now(UTC)

    try:
        if not settings.ANOMALY_SCAN_ENABLED:
            logger.info("anomaly_scan_skipped", reason="disabled_in_settings")
            return {
                "success": True,
                "scan_enabled": False,
                "profiles_scanned": 0,
                "created": 0,
                "detectors": {},
                "severity": {"low": 0, "medium": 0, "high": 0},
            }

        cutoff = started_at - timedelta(hours=settings.ANOMALY_SCAN_WINDOW_HOURS)
        profiles = db.execute(
            select(Profile)
            .where(Profile.created_at >= cutoff)
            .order_by(Profile.created_at.asc())
        ).scalars().all()

        if not profiles:
            logger.info(
                "anomaly_scan_complete",
                profiles_scanned=0,
                created=0,
                detectors={
                    "spatial_baseline": 0,
                    "float_self_comparison": 0,
                    "seasonal_baseline": 0,
                    "cluster_pattern": 0,
                },
                severity={"low": 0, "medium": 0, "high": 0},
            )
            return {
                "success": True,
                "scan_enabled": True,
                "profiles_scanned": 0,
                "created": 0,
                "detectors": {
                    "spatial_baseline": 0,
                    "float_self_comparison": 0,
                    "seasonal_baseline": 0,
                    "cluster_pattern": 0,
                },
                "severity": {"low": 0, "medium": 0, "high": 0},
            }

        spatial = SpatialBaselineDetector()
        self_comparison = FloatSelfComparisonDetector()
        seasonal = SeasonalBaselineDetector()
        cluster = ClusterPatternDetector()

        spatial_rows = _run_detector_safely(
            "spatial_baseline",
            spatial.run,
            profiles,
            db,
        )
        self_rows = _run_detector_safely(
            "float_self_comparison",
            self_comparison.run,
            profiles,
            db,
        )
        seasonal_rows = _run_detector_safely(
            "seasonal_baseline",
            seasonal.run,
            profiles,
            db,
        )

        pre_cluster_rows = [*spatial_rows, *self_rows, *seasonal_rows]

        cluster_rows = _run_detector_safely(
            "cluster_pattern",
            cluster.run,
            profiles,
            db,
            pre_cluster_rows,
        )

        all_rows = _dedup_in_memory([*pre_cluster_rows, *cluster_rows])

        if all_rows:
            db.add_all(all_rows)
        db.commit()

        detector_counts = {
            "spatial_baseline": len(spatial_rows),
            "float_self_comparison": len(self_rows),
            "seasonal_baseline": len(seasonal_rows),
            "cluster_pattern": len(cluster_rows),
        }
        severity_counts = _severity_breakdown(all_rows)

        _notify_new_anomalies(all_rows)

        logger.info(
            "anomaly_scan_complete",
            profiles_scanned=len(profiles),
            created=len(all_rows),
            detectors=detector_counts,
            severity=severity_counts,
            window_hours=settings.ANOMALY_SCAN_WINDOW_HOURS,
        )
        set_anomaly_scan_duration(max((datetime.now(UTC) - started_at).total_seconds(), 0.0))

        return {
            "success": True,
            "scan_enabled": True,
            "profiles_scanned": len(profiles),
            "created": len(all_rows),
            "detectors": detector_counts,
            "severity": severity_counts,
        }

    except Exception as exc:
        db.rollback()
        logger.error("anomaly_scan_failed", error=str(exc))
        set_anomaly_scan_duration(max((datetime.now(UTC) - started_at).total_seconds(), 0.0))
        return {
            "success": False,
            "scan_enabled": bool(settings.ANOMALY_SCAN_ENABLED),
            "profiles_scanned": 0,
            "created": 0,
            "detectors": {},
            "severity": {"low": 0, "medium": 0, "high": 0},
            "error": str(exc),
        }
    finally:
        db.close()
