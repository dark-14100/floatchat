"""Prometheus metric definitions for Feature 12."""

from __future__ import annotations

from contextvars import ContextVar
from typing import Any


class _NoopMetric:
    """No-op metric fallback when prometheus_client is unavailable."""

    def labels(self, **_kwargs: Any) -> "_NoopMetric":
        return self

    def inc(self, _amount: float = 1.0) -> None:
        return None

    def observe(self, _value: float) -> None:
        return None

    def set(self, _value: float) -> None:
        return None


try:
    from prometheus_client import REGISTRY, Counter, Gauge, Histogram  # type: ignore[import-not-found]
except Exception:
    REGISTRY = None
    floatchat_llm_call_duration_seconds = _NoopMetric()
    floatchat_db_query_duration_seconds = _NoopMetric()
    floatchat_redis_cache_hits_total = _NoopMetric()
    floatchat_redis_cache_misses_total = _NoopMetric()
    floatchat_celery_task_duration_seconds = _NoopMetric()
    floatchat_anomaly_scan_duration_seconds = _NoopMetric()
else:
    floatchat_llm_call_duration_seconds = Histogram(
        "floatchat_llm_call_duration_seconds",
        "Wall-clock duration of LLM provider calls.",
        labelnames=("provider", "model"),
        registry=REGISTRY,
    )

    floatchat_db_query_duration_seconds = Histogram(
        "floatchat_db_query_duration_seconds",
        "Database query duration grouped by API endpoint.",
        labelnames=("endpoint",),
        registry=REGISTRY,
    )

    floatchat_redis_cache_hits_total = Counter(
        "floatchat_redis_cache_hits_total",
        "Total Redis cache hits by operation.",
        labelnames=("operation",),
        registry=REGISTRY,
    )

    floatchat_redis_cache_misses_total = Counter(
        "floatchat_redis_cache_misses_total",
        "Total Redis cache misses by operation.",
        labelnames=("operation",),
        registry=REGISTRY,
    )

    floatchat_celery_task_duration_seconds = Histogram(
        "floatchat_celery_task_duration_seconds",
        "Duration of Celery tasks by task name.",
        labelnames=("task_name",),
        registry=REGISTRY,
    )

    floatchat_anomaly_scan_duration_seconds = Gauge(
        "floatchat_anomaly_scan_duration_seconds",
        "Duration of the latest anomaly scan run in seconds.",
        registry=REGISTRY,
    )


_CURRENT_ENDPOINT: ContextVar[str] = ContextVar("floatchat_current_endpoint", default="unknown")


def set_current_endpoint(endpoint: str | None) -> Any:
    """Store endpoint path in request-local context for DB query labels."""
    return _CURRENT_ENDPOINT.set(endpoint or "unknown")


def reset_current_endpoint(token: Any) -> None:
    """Restore previous request endpoint context."""
    try:
        _CURRENT_ENDPOINT.reset(token)
    except Exception:
        return None


def current_endpoint() -> str:
    """Return current request endpoint label for DB query metrics."""
    try:
        return _CURRENT_ENDPOINT.get()
    except Exception:
        return "unknown"


def observe_llm_call_duration(duration_seconds: float, provider: str, model: str) -> None:
    try:
        floatchat_llm_call_duration_seconds.labels(
            provider=(provider or "unknown"),
            model=(model or "unknown"),
        ).observe(duration_seconds)
    except Exception:
        return None


def observe_db_query_duration(duration_seconds: float, endpoint: str | None = None) -> None:
    try:
        floatchat_db_query_duration_seconds.labels(endpoint=(endpoint or current_endpoint())).observe(
            duration_seconds
        )
    except Exception:
        return None


def record_cache_hit(operation: str) -> None:
    try:
        floatchat_redis_cache_hits_total.labels(operation=(operation or "unknown")).inc()
    except Exception:
        return None


def record_cache_miss(operation: str) -> None:
    try:
        floatchat_redis_cache_misses_total.labels(operation=(operation or "unknown")).inc()
    except Exception:
        return None


def observe_celery_task_duration(duration_seconds: float, task_name: str) -> None:
    try:
        floatchat_celery_task_duration_seconds.labels(task_name=(task_name or "unknown")).observe(
            duration_seconds
        )
    except Exception:
        return None


def set_anomaly_scan_duration(duration_seconds: float) -> None:
    try:
        floatchat_anomaly_scan_duration_seconds.set(duration_seconds)
    except Exception:
        return None
