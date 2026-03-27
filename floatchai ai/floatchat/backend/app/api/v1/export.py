"""Feature 8 Data Export API router."""

import gzip
import json
import uuid
from datetime import datetime, timezone
from io import BytesIO
from typing import Any, Literal, Optional

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Request, status
from fastapi.responses import JSONResponse, StreamingResponse
from pydantic import BaseModel, Field
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_api_key_or_user
from app.config import get_settings
from app.db.models import ApiKey, ChatMessage, ChatSession, User
from app.db.session import SessionLocal, get_db
from app.export import (
    estimate_export_size_bytes,
    generate_csv,
    generate_json,
    generate_netcdf,
    should_use_async_export,
)
from app.export.tasks import generate_export_task
from app.rate_limiter import limiter

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/export", tags=["Export"], dependencies=[Depends(get_api_key_or_user)])


def _export_rate_limit(key: str) -> str:
    settings = get_settings()
    if isinstance(key, str) and key.startswith("apikey:"):
        api_key_id = key.split(":", 1)[1]
        db = SessionLocal()
        try:
            api_key = db.scalar(select(ApiKey).where(ApiKey.key_id == uuid.UUID(api_key_id)))
            if api_key and api_key.rate_limit_override:
                return f"{int(api_key.rate_limit_override)}/minute"
        except Exception:
            pass
        finally:
            db.close()
        return f"{settings.API_KEY_RATE_LIMIT_PER_MINUTE}/minute"
    return f"{settings.JWT_RATE_LIMIT_PER_MINUTE}/minute"


class ExportFilters(BaseModel):
    variables: Optional[list[str]] = None
    min_pressure: Optional[float] = None
    max_pressure: Optional[float] = None


class ExportRequest(BaseModel):
    message_id: str = Field(..., description="Chat message_id to export")
    format: Literal["csv", "netcdf", "json"]
    rows: list[dict[str, Any]] = Field(default_factory=list)
    filters: Optional[ExportFilters] = None


class ExportQueuedResponse(BaseModel):
    task_id: str
    status: Literal["queued"]
    poll_url: str


class ExportStatusResponse(BaseModel):
    status: Literal["queued", "processing", "complete", "failed"]
    task_id: str
    download_url: Optional[str] = None
    expires_at: Optional[str] = None
    error: Optional[str] = None


class ExportErrorResponse(BaseModel):
    error: str
    detail: str


def _get_redis_client() -> Redis:
    settings = get_settings()
    try:
        client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        client.ping()
        return client
    except Exception as exc:
        log.error("export_redis_unavailable", error=str(exc))
        raise HTTPException(status_code=503, detail="Export service unavailable")


def _status_key(task_id: str) -> str:
    return f"export_task:{task_id}"


def _rows_key(task_id: str) -> str:
    return f"export_rows:{task_id}"


def _iso_utc_now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _apply_filters(
    rows: list[dict[str, Any]],
    columns: list[str],
    filters: Optional[ExportFilters],
) -> tuple[list[dict[str, Any]], list[str]]:
    if not filters:
        return rows, columns

    filtered_rows = rows
    filtered_columns = list(columns)

    if filters.min_pressure is not None or filters.max_pressure is not None:
        pr_min = filters.min_pressure
        pr_max = filters.max_pressure
        next_rows: list[dict[str, Any]] = []
        for row in filtered_rows:
            pressure_raw = row.get("pressure", row.get("PRES"))
            if pressure_raw is None:
                next_rows.append(row)
                continue

            try:
                pressure_value = float(pressure_raw)
            except (TypeError, ValueError):
                continue

            if pr_min is not None and pressure_value < pr_min:
                continue
            if pr_max is not None and pressure_value > pr_max:
                continue

            next_rows.append(row)

        filtered_rows = next_rows

    if filters.variables:
        allowed = set(filters.variables)
        filtered_columns = [column for column in filtered_columns if column in allowed]
        filtered_rows = [
            {key: value for key, value in row.items() if key in allowed}
            for row in filtered_rows
        ]

    return filtered_rows, filtered_columns


def _build_filename(export_format: Literal["csv", "netcdf", "json"]) -> str:
    timestamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
    ext = "nc" if export_format == "netcdf" else export_format
    return f"floatchat_{export_format}_{timestamp}.{ext}"


def _content_type(export_format: Literal["csv", "netcdf", "json"]) -> str:
    if export_format == "csv":
        return "text/csv; charset=utf-8"
    if export_format == "netcdf":
        return "application/x-netcdf"
    return "application/json"


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


@router.post(
    "",
    response_model=ExportQueuedResponse,
    responses={
        200: {"content": {
            "text/csv": {},
            "application/x-netcdf": {},
            "application/json": {},
        }},
        413: {"model": ExportErrorResponse},
    },
)
@limiter.limit(_export_rate_limit)
def create_export(
    request: Request,
    payload: ExportRequest = Body(...),
    db: Session = Depends(get_db),
    current_user: User = Depends(get_api_key_or_user),
):
    settings = get_settings()

    try:
        message_uuid = uuid.UUID(payload.message_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid message_id format")

    stmt = (
        select(ChatMessage, ChatSession.user_identifier)
        .join(ChatSession, ChatMessage.session_id == ChatSession.session_id)
        .where(ChatMessage.message_id == message_uuid)
    )
    result = db.execute(stmt).first()

    if result is None:
        raise HTTPException(status_code=404, detail="Message not found")

    chat_message, owner_identifier = result
    if owner_identifier != str(current_user.user_id):
        raise HTTPException(
            status_code=403,
            detail="You do not have access to this message",
        )

    metadata = chat_message.result_metadata or {}
    metadata_row_count = int(metadata.get("row_count") or 0)
    metadata_columns = metadata.get("columns") or []

    if metadata_row_count <= 0 or not payload.rows:
        raise HTTPException(
            status_code=410,
            detail="Export data has expired. Please re-run your query and try again.",
        )

    rows = list(payload.rows)
    columns = [str(column) for column in metadata_columns] or list(rows[0].keys())

    try:
        json.dumps(rows, allow_nan=False)
    except (TypeError, ValueError) as exc:
        raise HTTPException(
            status_code=400,
            detail=f"Rows are not JSON-serializable: {exc}",
        )

    rows, columns = _apply_filters(rows, columns, payload.filters)
    row_count = len(rows)

    estimated_size = estimate_export_size_bytes(
        row_count=row_count,
        column_count=len(columns),
        export_format=payload.format,
    )

    max_size_bytes = settings.EXPORT_MAX_SIZE_MB * 1024 * 1024
    if estimated_size > max_size_bytes:
        return JSONResponse(
            status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
            content={
                "error": "Export too large",
                "detail": "Estimated export size exceeds the 500MB limit. Refine your query to return fewer rows.",
            },
        )

    nl_query = chat_message.nl_query or ""

    use_async = should_use_async_export(
        row_count=row_count,
        column_count=len(columns),
        export_format=payload.format,
        sync_limit_mb=settings.EXPORT_SYNC_SIZE_LIMIT_MB,
    )

    if not use_async:
        export_bytes = _generate_export_bytes(
            export_format=payload.format,
            rows=rows,
            columns=columns,
            nl_query=nl_query,
        )

        headers = {
            "Content-Disposition": f'attachment; filename="{_build_filename(payload.format)}"',
        }

        if payload.format in {"csv", "json"}:
            export_bytes = gzip.compress(export_bytes)
            headers["Content-Encoding"] = "gzip"

        return StreamingResponse(
            BytesIO(export_bytes),
            media_type=_content_type(payload.format),
            headers=headers,
        )

    redis_client = _get_redis_client()

    task_id = str(uuid.uuid4())
    task_status = {
        "task_id": task_id,
        "status": "queued",
        "created_at": _iso_utc_now(),
    }

    ttl = settings.EXPORT_TASK_STATUS_TTL_SECONDS
    redis_client.setex(_rows_key(task_id), ttl, json.dumps(rows, allow_nan=False))
    redis_client.setex(_status_key(task_id), ttl, json.dumps(task_status, allow_nan=False))

    generate_export_task.delay(
        task_id=task_id,
        export_format=payload.format,
        columns=columns,
        nl_query=nl_query,
        user_id=str(current_user.user_id),
    )

    return ExportQueuedResponse(
        task_id=task_id,
        status="queued",
        poll_url=f"/api/v1/export/status/{task_id}",
    )


@router.get("/status/{task_id}", response_model=ExportStatusResponse)
@limiter.limit(_export_rate_limit)
def export_status(
    request: Request,
    task_id: str,
    current_user: User = Depends(get_api_key_or_user),
):
    del request
    del current_user

    redis_client = _get_redis_client()
    raw = redis_client.get(_status_key(task_id))
    if raw is None:
        raise HTTPException(status_code=404, detail="Task not found")

    try:
        payload = json.loads(raw)
    except json.JSONDecodeError:
        raise HTTPException(status_code=500, detail="Invalid task status payload")

    return ExportStatusResponse(**payload)
