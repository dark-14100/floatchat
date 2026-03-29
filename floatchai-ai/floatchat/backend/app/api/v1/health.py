"""Component-aware health endpoint for infrastructure readiness checks."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass
from datetime import datetime, timezone
import time

from celery import Celery
from fastapi import APIRouter
from fastapi.responses import JSONResponse
from redis import Redis
from sqlalchemy import text

from app.celery_app import celery
from app.config import settings
from app.db.session import engine

router = APIRouter(prefix="/health", tags=["Health"])

_DB_TIMEOUT_SECONDS = 1.0
_REDIS_TIMEOUT_SECONDS = 0.5
_CELERY_TIMEOUT_SECONDS = 2.0
_OVERALL_TIMEOUT_SECONDS = 3.0


@dataclass
class _ComponentResult:
    status: str
    message: str | None = None


def _check_db_sync() -> None:
    with engine.connect() as conn:
        conn.execute(text("SELECT 1"))


async def _check_db() -> _ComponentResult:
    try:
        await asyncio.wait_for(asyncio.to_thread(_check_db_sync), timeout=_DB_TIMEOUT_SECONDS)
        return _ComponentResult(status="ok")
    except asyncio.TimeoutError:
        return _ComponentResult(status="error", message="db_check_timed_out")
    except Exception as exc:
        return _ComponentResult(status="error", message=str(exc))


def _check_redis_sync() -> None:
    client = Redis.from_url(
        settings.REDIS_URL,
        decode_responses=True,
        socket_connect_timeout=_REDIS_TIMEOUT_SECONDS,
        socket_timeout=_REDIS_TIMEOUT_SECONDS,
    )
    try:
        client.ping()
    finally:
        client.close()


async def _check_redis() -> _ComponentResult:
    try:
        await asyncio.wait_for(asyncio.to_thread(_check_redis_sync), timeout=_REDIS_TIMEOUT_SECONDS)
        return _ComponentResult(status="ok")
    except asyncio.TimeoutError:
        return _ComponentResult(status="error", message="redis_check_timed_out")
    except Exception as exc:
        return _ComponentResult(status="error", message=str(exc))


def _check_celery_sync(celery_app: Celery) -> dict | None:
    inspector = celery_app.control.inspect(timeout=_CELERY_TIMEOUT_SECONDS)
    return inspector.ping()


async def _check_celery() -> _ComponentResult:
    try:
        response = await asyncio.wait_for(
            asyncio.to_thread(_check_celery_sync, celery),
            timeout=_CELERY_TIMEOUT_SECONDS,
        )
    except asyncio.TimeoutError:
        return _ComponentResult(status="error", message="celery_check_timed_out")
    except Exception as exc:
        return _ComponentResult(status="error", message=str(exc))

    if not response:
        return _ComponentResult(status="degraded", message="no_celery_workers_responded")

    return _ComponentResult(status="ok")


def _resolve_overall_status(db_status: str, redis_status: str, celery_status: str) -> str:
    if "error" in {db_status, redis_status, celery_status}:
        return "error"
    if "degraded" in {db_status, redis_status, celery_status}:
        return "degraded"
    return "ok"


@router.get("")
async def health_check_v1() -> JSONResponse:
    started = time.perf_counter()

    try:
        checks = await asyncio.wait_for(
            asyncio.gather(
                _check_db(),
                _check_redis(),
                _check_celery(),
            ),
            timeout=_OVERALL_TIMEOUT_SECONDS,
        )
        db_result, redis_result, celery_result = checks
    except asyncio.TimeoutError:
        payload = {
            "status": "error",
            "db": "error",
            "redis": "error",
            "celery": "error",
            "timestamp": datetime.now(timezone.utc).isoformat(),
            "version": settings.APP_VERSION,
            "message": "health_check_overall_timeout",
            "duration_ms": round((time.perf_counter() - started) * 1000, 2),
        }
        return JSONResponse(content=payload, status_code=503)

    overall_status = _resolve_overall_status(
        db_result.status,
        redis_result.status,
        celery_result.status,
    )

    payload: dict[str, object] = {
        "status": overall_status,
        "db": db_result.status,
        "redis": redis_result.status,
        "celery": celery_result.status,
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "version": settings.APP_VERSION,
    }

    # Error detail fields are additive and help operators diagnose non-ok checks.
    if db_result.message:
        payload["db_message"] = db_result.message
    if redis_result.message:
        payload["redis_message"] = redis_result.message
    if celery_result.message:
        payload["celery_message"] = celery_result.message

    payload["duration_ms"] = round((time.perf_counter() - started) * 1000, 2)

    status_code = 503 if overall_status == "error" else 200
    return JSONResponse(content=payload, status_code=status_code)
