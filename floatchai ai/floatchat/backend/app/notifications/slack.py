"""Slack webhook notification sender for ingestion and anomaly events."""

from typing import Any

import httpx
import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


def _build_text(event: str, context: dict[str, Any]) -> str:
    """Build event-specific Slack message text."""
    dataset_name = str(context.get("dataset_name") or "unknown dataset")

    if event == "ingestion_completed":
        profiles_ingested = context.get("profiles_ingested", 0)
        return (
            f"Ingestion complete: dataset {dataset_name}, "
            f"{profiles_ingested} profiles ingested"
        )

    if event == "ingestion_failed":
        error_message = str(context.get("error_message") or "Unknown error")
        return f"Ingestion failed: dataset {dataset_name}, error: {error_message}"

    if event == "anomalies_detected":
        anomaly_count = context.get("anomaly_count", 0)
        return f"Anomaly scan detected {anomaly_count} new anomalies"

    if event == "ingestion_daily_digest":
        target_date = str(context.get("target_date") or "unknown")
        total_profiles = context.get("total_profiles_ingested", 0)
        new_floats = context.get("new_floats_discovered", 0)
        failed_count = context.get("failed_jobs_count", 0)
        gdac_status = str(context.get("gdac_sync_status") or "not_run")
        failed_names = context.get("failed_job_names") or []
        failed_preview = ", ".join(str(item) for item in failed_names[:5])
        if not failed_preview:
            failed_preview = "none"
        return (
            f"Daily ingestion digest ({target_date} UTC): "
            f"profiles={total_profiles}, new_floats={new_floats}, "
            f"failed_jobs={failed_count} [{failed_preview}], gdac={gdac_status}"
        )

    return f"Notification event: {event}"


def send_notification(event: str, context: dict[str, Any]) -> None:
    """Send a single event notification to Slack via incoming webhook."""
    webhook_url = settings.NOTIFICATION_SLACK_WEBHOOK_URL
    if not webhook_url:
        return

    payload = {"text": _build_text(event, context)}

    response = httpx.post(webhook_url, json=payload, timeout=20.0)
    response.raise_for_status()

    logger.info("slack_notification_sent", event=event)
