"""Unified notification dispatcher for enabled channels."""

from typing import Any

import structlog

from app.config import settings
from app.notifications.email import send_notification as send_email_notification
from app.notifications.slack import send_notification as send_slack_notification

logger = structlog.get_logger(__name__)


def notify(event: str, context: dict[str, Any]) -> None:
    """Dispatch an event notification to configured channels.

    This function is intentionally synchronous because it is called from
    synchronous Celery tasks.
    """
    if not settings.NOTIFICATIONS_ENABLED:
        return

    if settings.NOTIFICATION_EMAIL_ENABLED:
        try:
            send_email_notification(event, context)
        except Exception as exc:
            logger.error(
                "email_notification_failed",
                event=event,
                error=str(exc),
            )

    if settings.NOTIFICATION_SLACK_ENABLED:
        try:
            send_slack_notification(event, context)
        except Exception as exc:
            logger.error(
                "slack_notification_failed",
                event=event,
                error=str(exc),
            )
