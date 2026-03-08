"""SMTP email notification sender for ingestion and anomaly events."""

from email.message import EmailMessage
import smtplib
from typing import Any

import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


def _parse_recipients(raw_recipients: str | None) -> list[str]:
    """Parse comma-separated recipients into a cleaned list."""
    if not raw_recipients:
        return []
    recipients = [item.strip() for item in raw_recipients.split(",")]
    return [item for item in recipients if item]


def _build_message(event: str, context: dict[str, Any]) -> tuple[str, str]:
    """Build event-specific email subject and body."""
    dataset_name = str(context.get("dataset_name") or "unknown dataset")

    if event == "ingestion_completed":
        profiles_ingested = context.get("profiles_ingested", 0)
        subject = f"[FloatChat] Ingestion Complete: {dataset_name}"
        body = (
            f"Ingestion completed successfully.\n\n"
            f"Dataset: {dataset_name}\n"
            f"Profiles ingested: {profiles_ingested}\n"
        )
        return subject, body

    if event == "ingestion_failed":
        error_message = str(context.get("error_message") or "Unknown error")
        subject = f"[FloatChat] Ingestion Failed: {dataset_name}"
        body = (
            f"Ingestion failed.\n\n"
            f"Dataset: {dataset_name}\n"
            f"Error: {error_message}\n"
        )
        return subject, body

    if event == "anomalies_detected":
        anomaly_count = context.get("anomaly_count", 0)
        subject = "[FloatChat] New Anomalies Detected"
        body = f"Anomaly scan detected {anomaly_count} new anomalies.\n"
        return subject, body

    subject = f"[FloatChat] Notification: {event}"
    body = f"Event: {event}\nContext: {context}\n"
    return subject, body


def send_notification(event: str, context: dict[str, Any]) -> None:
    """Send a single event notification email using SMTP."""
    recipients = _parse_recipients(settings.NOTIFICATION_EMAIL_TO)
    smtp_host = settings.NOTIFICATION_EMAIL_SMTP_HOST
    sender = settings.NOTIFICATION_EMAIL_FROM

    if not recipients or not smtp_host or not sender:
        return

    subject, body = _build_message(event, context)

    message = EmailMessage()
    message["Subject"] = subject
    message["From"] = sender
    message["To"] = sender
    message["Bcc"] = ", ".join(recipients)
    message.set_content(body)

    with smtplib.SMTP(smtp_host, settings.NOTIFICATION_EMAIL_SMTP_PORT, timeout=20) as smtp:
        smtp.starttls()
        if settings.NOTIFICATION_EMAIL_SMTP_USER and settings.NOTIFICATION_EMAIL_SMTP_PASSWORD:
            smtp.login(
                settings.NOTIFICATION_EMAIL_SMTP_USER,
                settings.NOTIFICATION_EMAIL_SMTP_PASSWORD,
            )
        smtp.send_message(message)

    logger.info(
        "email_notification_sent",
        event=event,
        recipient_count=len(recipients),
    )
