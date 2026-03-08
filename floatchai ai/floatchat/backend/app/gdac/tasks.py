"""Celery task wrapper for GDAC synchronization."""

from __future__ import annotations

from typing import Any

import structlog

from app.celery_app import celery
from app.config import settings
from app.gdac.sync import run_gdac_sync


logger = structlog.get_logger(__name__)


@celery.task(name="app.gdac.tasks.run_gdac_sync_task", bind=True, acks_late=True)
def run_gdac_sync_task(
    self,
    triggered_by: str = "scheduled",
    lookback_days: int | None = None,
) -> dict[str, Any]:
    """Execute one GDAC sync cycle with a non-raising task contract."""
    _ = self

    try:
        result = run_gdac_sync(triggered_by=triggered_by, lookback_days=lookback_days)

        sync_enabled = bool(settings.GDAC_SYNC_ENABLED)
        success = result.status in {"completed", "partial"}
        if not sync_enabled:
            success = True

        return {
            "success": success,
            "sync_enabled": sync_enabled,
            "run_id": str(result.run_id),
            "status": result.status,
            "profiles_found": result.profiles_found,
            "profiles_downloaded": result.profiles_downloaded,
            "profiles_ingested": result.profiles_ingested,
            "profiles_skipped": result.profiles_skipped,
            "duration_seconds": result.duration_seconds,
            "error": result.error,
        }

    except Exception as exc:
        logger.error(
            "gdac_sync_task_failed",
            error=str(exc),
            triggered_by=triggered_by,
            lookback_days=lookback_days,
        )
        return {
            "success": False,
            "sync_enabled": bool(settings.GDAC_SYNC_ENABLED),
            "run_id": None,
            "status": "failed",
            "profiles_found": 0,
            "profiles_downloaded": 0,
            "profiles_ingested": 0,
            "profiles_skipped": 0,
            "duration_seconds": 0.0,
            "error": str(exc),
        }
