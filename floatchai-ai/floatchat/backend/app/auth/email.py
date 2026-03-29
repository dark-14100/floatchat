"""Password reset email sender for Feature 13."""

import structlog

from app.config import settings


log = structlog.get_logger(__name__)


def send_password_reset_email(to_email: str, reset_link: str) -> None:
    """Send password reset email (stdout logging fallback for v1)."""
    if settings.DEBUG:
        log.info(
            "password_reset_link_generated",
            to_email=to_email,
            reset_link=reset_link,
        )
        return

    # TODO: replace with SendGrid/SMTP in production
    log.info(
        "password_reset_link_generated",
        to_email=to_email,
        reset_link=reset_link,
    )
