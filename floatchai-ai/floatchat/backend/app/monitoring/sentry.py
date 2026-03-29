"""Sentry helpers for Feature 12 backend observability."""

from __future__ import annotations

from typing import Optional

import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


def _sanitize_sentry_event(event: dict, _hint: dict) -> dict:
    """Drop request payloads to avoid sending user content or PII."""
    request_data = event.get("request")
    if isinstance(request_data, dict):
        request_data.pop("data", None)
        request_data.pop("cookies", None)
        headers = request_data.get("headers")
        if isinstance(headers, dict):
            headers.pop("authorization", None)
            headers.pop("cookie", None)
    return event


def init_sentry() -> bool:
    """Initialize Sentry if backend DSN is configured; otherwise no-op."""
    dsn = settings.effective_sentry_dsn_backend
    if not dsn:
        logger.info("sentry_disabled", reason="missing_backend_dsn")
        return False

    if not settings.SENTRY_DSN_BACKEND and settings.SENTRY_DSN:
        logger.warning(
            "sentry_legacy_dsn_alias_in_use",
            deprecated="SENTRY_DSN",
            replacement="SENTRY_DSN_BACKEND",
        )

    try:
        import sentry_sdk
        from sentry_sdk.integrations.fastapi import FastApiIntegration
        from sentry_sdk.integrations.sqlalchemy import SqlalchemyIntegration

        sentry_sdk.init(
            dsn=dsn,
            environment=settings.ENVIRONMENT,
            release=settings.APP_VERSION,
            traces_sample_rate=settings.SENTRY_TRACES_SAMPLE_RATE,
            send_default_pii=False,
            integrations=[
                FastApiIntegration(transaction_style="endpoint"),
                SqlalchemyIntegration(),
            ],
            before_send=_sanitize_sentry_event,
        )
        logger.info("sentry_initialized", environment=settings.ENVIRONMENT, release=settings.APP_VERSION)
        return True
    except Exception as exc:
        logger.warning("sentry_init_failed", error=str(exc))
        return False


def set_sentry_request_tags(
    *,
    query_type: Optional[str] = None,
    dataset_id: Optional[str] = None,
    float_id: Optional[str] = None,
    provider: Optional[str] = None,
    user_id: Optional[str] = None,
    api_key_request: Optional[bool] = None,
) -> None:
    """Attach request-scoped Sentry tags when Sentry is enabled."""
    try:
        import sentry_sdk

        with sentry_sdk.configure_scope() as scope:
            if query_type:
                scope.set_tag("query_type", query_type)
            if dataset_id:
                scope.set_tag("dataset_id", str(dataset_id))
            if float_id:
                scope.set_tag("float_id", str(float_id))
            if provider:
                scope.set_tag("provider", provider)
            if user_id:
                scope.set_tag("user_id", str(user_id))
            if api_key_request is not None:
                scope.set_tag("api_key_request", str(bool(api_key_request)).lower())
    except Exception:
        # Monitoring helpers must never affect request flow.
        return None
