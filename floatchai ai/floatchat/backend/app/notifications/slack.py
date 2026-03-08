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
