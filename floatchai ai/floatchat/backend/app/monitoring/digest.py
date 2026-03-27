"""Daily ingestion digest aggregation and notification task."""

from __future__ import annotations

from datetime import date, datetime, time, timedelta, timezone
from typing import Any

import structlog
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.celery_app import celery
from app.db.models import GDACSyncRun, IngestionJob, Profile
from app.db.session import SessionLocal
from app.notifications.sender import notify

logger = structlog.get_logger(__name__)


def _utc_day_window(target_date: date) -> tuple[datetime, datetime]:
    start = datetime.combine(target_date, time.min, tzinfo=timezone.utc)
    end = start + timedelta(days=1)
    return start, end


def _resolve_gdac_status(session: Session, *, start: datetime, end: datetime) -> str:
    latest_status = session.execute(
        select(GDACSyncRun.status)
        .where(GDACSyncRun.started_at >= start, GDACSyncRun.started_at < end)
        .order_by(GDACSyncRun.started_at.desc())
        .limit(1)
    ).scalar_one_or_none()
    return latest_status or "not_run"


def build_digest_data(session: Session, target_date: date) -> dict[str, Any]:
    """Build ingestion digest payload for a UTC calendar day."""
    start, end = _utc_day_window(target_date)

    profiles_ingested_total = session.execute(
        select(func.coalesce(func.sum(IngestionJob.profiles_ingested), 0)).where(
            IngestionJob.created_at >= start,
            IngestionJob.created_at < end,
            IngestionJob.status == "succeeded",
        )
    ).scalar_one()

    new_floats_discovered = session.execute(
        select(func.count(func.distinct(Profile.platform_number))).where(
            Profile.created_at >= start,
            Profile.created_at < end,
        )
    ).scalar_one()

    failed_rows = session.execute(
        select(IngestionJob.original_filename)
        .where(
            IngestionJob.created_at >= start,
            IngestionJob.created_at < end,
            IngestionJob.status == "failed",
        )
        .order_by(IngestionJob.created_at.asc())
    ).all()
    failed_job_names = [row[0] or "unknown_file" for row in failed_rows]

    return {
        "target_date": target_date.isoformat(),
        "window_start_utc": start.isoformat(),
        "window_end_utc": end.isoformat(),
        "total_profiles_ingested": int(profiles_ingested_total or 0),
        "new_floats_discovered": int(new_floats_discovered or 0),
        "failed_jobs_count": len(failed_job_names),
        "failed_job_names": failed_job_names,
        "gdac_sync_status": _resolve_gdac_status(session, start=start, end=end),
    }


@celery.task(name="app.monitoring.digest.send_ingestion_digest_task")
def send_ingestion_digest_task() -> dict[str, Any]:
    """Send a daily digest for the previous UTC calendar day."""
    previous_utc_day = (datetime.now(timezone.utc) - timedelta(days=1)).date()
    db = SessionLocal()
    try:
        digest_data = build_digest_data(db, previous_utc_day)
        notify("ingestion_daily_digest", digest_data)
        logger.info(
            "ingestion_daily_digest_sent",
            target_date=digest_data["target_date"],
            failed_jobs_count=digest_data["failed_jobs_count"],
        )
        return {"ok": True, "target_date": digest_data["target_date"]}
    except Exception as exc:
        logger.error("ingestion_daily_digest_failed", error=str(exc), exc_info=True)
        return {"ok": False, "error": str(exc)}
    finally:
        db.close()
