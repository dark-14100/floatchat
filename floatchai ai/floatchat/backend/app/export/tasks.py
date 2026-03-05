"""Feature 8 export Celery task."""

from __future__ import annotations

import json
import os
import tempfile
from datetime import datetime, timedelta, timezone
from typing import Any, Literal

import structlog
from redis import Redis

from app.celery_app import celery
from app.config import get_settings
from app.export import generate_csv, generate_json, generate_netcdf
from app.storage.s3 import get_s3_client

log = structlog.get_logger(__name__)


def _status_key(task_id: str) -> str:
    return f"export_task:{task_id}"


def _rows_key(task_id: str) -> str:
    return f"export_rows:{task_id}"


def _get_redis() -> Redis:
    settings = get_settings()
    return Redis.from_url(settings.REDIS_URL, decode_responses=True)


def _set_status(task_id: str, payload: dict[str, Any]) -> None:
    settings = get_settings()
    redis_client = _get_redis()
    redis_client.setex(
        _status_key(task_id),
        settings.EXPORT_TASK_STATUS_TTL_SECONDS,
        json.dumps(payload, allow_nan=False),
    )


def _content_type(export_format: Literal["csv", "netcdf", "json"]) -> str:
    if export_format == "csv":
        return "text/csv; charset=utf-8"
    if export_format == "netcdf":
        return "application/x-netcdf"
    return "application/json"


def _extension(export_format: Literal["csv", "netcdf", "json"]) -> str:
    if export_format == "netcdf":
        return "nc"
    return export_format


def _generate_export_bytes(
    export_format: Literal["csv", "netcdf", "json"],
    rows: list[dict[str, Any]],
    columns: list[str],
    nl_query: str,
) -> bytes:
    if export_format == "csv":
        return generate_csv(rows=rows, columns=columns, nl_query=nl_query)
    if export_format == "netcdf":
        return generate_netcdf(rows=rows, columns=columns, nl_query=nl_query)
    return generate_json(rows=rows, columns=columns, nl_query=nl_query)


@celery.task(name="app.export.tasks.generate_export_task", bind=True)
def generate_export_task(
    self,
    task_id: str,
    export_format: Literal["csv", "netcdf", "json"],
    columns: list[str],
    nl_query: str,
    user_id: str,
) -> dict[str, Any]:
    settings = get_settings()
    redis_client = _get_redis()

    rows_payload = redis_client.get(_rows_key(task_id))
    if rows_payload is None:
        failure = {
            "task_id": task_id,
            "status": "failed",
            "error": "Export rows not found or expired",
        }
        _set_status(task_id, failure)
        return failure

    try:
        rows = json.loads(rows_payload)
        if not isinstance(rows, list):
            raise ValueError("Rows payload is not a list")

        _set_status(
            task_id,
            {
                "task_id": task_id,
                "status": "processing",
            },
        )

        payload = _generate_export_bytes(
            export_format=export_format,
            rows=rows,
            columns=columns,
            nl_query=nl_query,
        )

        s3_key = f"exports/{user_id}/{task_id}.{_extension(export_format)}"
        temp_path: str | None = None

        try:
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                temp_file.write(payload)
                temp_file.flush()
                temp_path = temp_file.name

            s3_client = get_s3_client()
            with open(temp_path, "rb") as file_handle:
                s3_client.put_object(
                    Bucket=settings.EXPORT_BUCKET_NAME,
                    Key=s3_key,
                    Body=file_handle,
                    ContentType=_content_type(export_format),
                )
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

        download_url = s3_client.generate_presigned_url(
            ClientMethod="get_object",
            Params={
                "Bucket": settings.EXPORT_BUCKET_NAME,
                "Key": s3_key,
            },
            ExpiresIn=settings.EXPORT_PRESIGNED_URL_EXPIRY_SECONDS,
        )

        expires_at = (
            datetime.now(timezone.utc)
            + timedelta(seconds=settings.EXPORT_PRESIGNED_URL_EXPIRY_SECONDS)
        ).isoformat()

        complete_payload = {
            "task_id": task_id,
            "status": "complete",
            "download_url": download_url,
            "expires_at": expires_at,
        }
        _set_status(task_id, complete_payload)
        redis_client.delete(_rows_key(task_id))

        return complete_payload

    except Exception as exc:
        log.error(
            "export_task_failed",
            task_id=task_id,
            error_type=type(exc).__name__,
            error=str(exc),
            retries=self.request.retries,
        )

        failure_payload = {
            "task_id": task_id,
            "status": "failed",
            "error": str(exc),
        }
        _set_status(task_id, failure_payload)
        raise
