"""Admin API endpoints for dataset management, ingestion monitoring, and audit log."""

from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone
import json
from typing import Any, Optional
import uuid

import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, ConfigDict, Field
from sqlalchemy import func, select
from sqlalchemy.orm import Session

from app.admin.tasks import hard_delete_dataset_task, regenerate_summary_task
from app.auth.dependencies import get_current_admin_user
from app.db.models import (
    AdminAuditLog,
    Anomaly,
    Dataset,
    IngestionJob,
    Measurement,
    Profile,
    User,
)
from app.db.session import get_db
from app.ingestion.tasks import ingest_file_task, ingest_zip_task
from app.storage.s3 import get_s3_client

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/admin",
    tags=["Admin"],
    dependencies=[Depends(get_current_admin_user)],
)


class DatasetMetadataPatch(BaseModel):
    """Partial metadata update payload for datasets."""

    model_config = ConfigDict(extra="forbid")

    name: Optional[str] = None
    description: Optional[str] = None
    tags: Optional[list[str]] = None
    is_public: Optional[bool] = None


class HardDeleteRequest(BaseModel):
    """Confirmation payload required before hard-delete dispatch."""

    model_config = ConfigDict(extra="forbid")

    confirm: bool
    confirm_dataset_name: str = Field(min_length=1)


def _sse_event(event_type: str, payload: dict[str, Any]) -> str:
    """Format an SSE event string."""
    return f"event: {event_type}\\ndata: {json.dumps(payload)}\\n\\n"


def _serialize_dataset(dataset: Dataset) -> dict[str, Any]:
    """Serialize dataset fields used by admin endpoints."""
    return {
        "dataset_id": dataset.dataset_id,
        "name": dataset.name,
        "description": dataset.description,
        "source_filename": dataset.source_filename,
        "raw_file_path": dataset.raw_file_path,
        "ingestion_date": dataset.ingestion_date.isoformat() if dataset.ingestion_date else None,
        "date_range_start": dataset.date_range_start.isoformat() if dataset.date_range_start else None,
        "date_range_end": dataset.date_range_end.isoformat() if dataset.date_range_end else None,
        "float_count": dataset.float_count,
        "profile_count": dataset.profile_count,
        "variable_list": dataset.variable_list,
        "summary_text": dataset.summary_text,
        "is_active": dataset.is_active,
        "is_public": dataset.is_public,
        "tags": dataset.tags,
        "dataset_version": dataset.dataset_version,
        "created_at": dataset.created_at.isoformat() if dataset.created_at else None,
        "deleted_at": dataset.deleted_at.isoformat() if dataset.deleted_at else None,
        "deleted_by": str(dataset.deleted_by) if dataset.deleted_by else None,
    }


def _write_audit_log(
    db: Session,
    *,
    admin_user_id: uuid.UUID,
    action: str,
    entity_type: str,
    entity_id: str,
    details: Optional[dict[str, Any]] = None,
) -> None:
    """Create one audit log row in the current transaction."""
    db.add(
        AdminAuditLog(
            admin_user_id=admin_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
        )
    )


def _get_latest_job_status(dataset_id: int, db: Session) -> Optional[str]:
    """Fetch latest ingestion job status for a dataset."""
    return db.execute(
        select(IngestionJob.status)
        .where(IngestionJob.dataset_id == dataset_id)
        .order_by(IngestionJob.created_at.desc())
        .limit(1)
    ).scalar_one_or_none()


def _get_ingestion_job_count(dataset_id: int, db: Session) -> int:
    """Fetch ingestion job count for a dataset."""
    return (
        db.execute(
            select(func.count(IngestionJob.job_id)).where(IngestionJob.dataset_id == dataset_id)
        ).scalar_one()
        or 0
    )


def _estimate_storage_bytes(dataset: Dataset, db: Session) -> int:
    """Estimate total raw storage bytes from dataset/job object paths."""
    paths = set()
    if dataset.raw_file_path:
        paths.add(dataset.raw_file_path)

    job_paths = db.execute(
        select(IngestionJob.raw_file_path).where(
            IngestionJob.dataset_id == dataset.dataset_id,
            IngestionJob.raw_file_path.isnot(None),
        )
    ).scalars().all()
    for path in job_paths:
        if path:
            paths.add(path)

    if not paths:
        return 0

    total_bytes = 0
    try:
        client = get_s3_client()
    except Exception:
        return 0

    from app.config import settings

    for key in paths:
        try:
            result = client.head_object(Bucket=settings.S3_BUCKET_NAME, Key=key)
            total_bytes += int(result.get("ContentLength", 0))
        except Exception:
            # Storage estimate is best-effort and should not fail endpoint responses.
            continue

    return total_bytes


@router.get("/datasets")
async def list_admin_datasets(
    include_deleted: bool = Query(False),
    is_public: Optional[bool] = Query(None),
    tags: Optional[str] = Query(None, description="Comma-separated tags"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return paginated dataset list for admins, with optional filters."""
    query = select(Dataset).order_by(Dataset.created_at.desc())

    if not include_deleted:
        query = query.where(Dataset.deleted_at.is_(None))

    if is_public is not None:
        query = query.where(Dataset.is_public == is_public)

    requested_tags = [item.strip() for item in (tags or "").split(",") if item.strip()]

    datasets = db.execute(query).scalars().all()
    if requested_tags:
        datasets = [
            d for d in datasets if all(tag in (d.tags or []) for tag in requested_tags)
        ]

    total = len(datasets)
    datasets_page = datasets[offset : offset + limit]

    rows = []
    for dataset in datasets_page:
        row = _serialize_dataset(dataset)
        row["ingestion_job_count"] = _get_ingestion_job_count(dataset.dataset_id, db)
        row["latest_job_status"] = _get_latest_job_status(dataset.dataset_id, db)
        rows.append(row)

    return {
        "datasets": rows,
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.get("/datasets/{dataset_id}")
async def get_admin_dataset_detail(
    dataset_id: int,
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return full admin detail for one dataset including ingestion history."""
    dataset = db.execute(
        select(Dataset).where(Dataset.dataset_id == dataset_id)
    ).scalar_one_or_none()

    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    measurement_count = (
        db.execute(
            select(func.count(Measurement.measurement_id))
            .select_from(Measurement)
            .join(Profile, Measurement.profile_id == Profile.profile_id)
            .where(Profile.dataset_id == dataset_id)
        ).scalar_one()
        or 0
    )

    ingestion_jobs = db.execute(
        select(IngestionJob)
        .where(IngestionJob.dataset_id == dataset_id)
        .order_by(IngestionJob.created_at.desc())
    ).scalars().all()

    storage_size_bytes = _estimate_storage_bytes(dataset, db)

    return {
        **_serialize_dataset(dataset),
        "measurement_count": int(measurement_count),
        "ingestion_job_history": [
            {
                "job_id": str(job.job_id),
                "status": job.status,
                "source": job.source,
                "original_filename": job.original_filename,
                "raw_file_path": job.raw_file_path,
                "progress_pct": job.progress_pct,
                "profiles_total": job.profiles_total,
                "profiles_ingested": job.profiles_ingested,
                "error_log": job.error_log,
                "errors": job.errors,
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                "created_at": job.created_at.isoformat() if job.created_at else None,
            }
            for job in ingestion_jobs
        ],
        "storage_size_bytes": storage_size_bytes,
    }


@router.patch("/datasets/{dataset_id}/metadata")
async def patch_admin_dataset_metadata(
    dataset_id: int,
    payload: DatasetMetadataPatch,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """Update dataset metadata and record an audit log entry."""
    dataset = db.execute(
        select(Dataset).where(Dataset.dataset_id == dataset_id)
    ).scalar_one_or_none()

    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    updates = payload.model_dump(exclude_unset=True)
    old_is_public = dataset.is_public

    for field, value in updates.items():
        setattr(dataset, field, value)

    action = "dataset_visibility_changed" if ("is_public" in updates and updates["is_public"] != old_is_public) else "dataset_metadata_updated"
    _write_audit_log(
        db,
        admin_user_id=current_admin.user_id,
        action=action,
        entity_type="dataset",
        entity_id=str(dataset_id),
        details={"updated_fields": sorted(list(updates.keys()))},
    )

    db.commit()
    db.refresh(dataset)

    return _serialize_dataset(dataset)


@router.post("/datasets/{dataset_id}/regenerate-summary")
async def regenerate_dataset_summary(
    dataset_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """Queue async summary regeneration for a dataset."""
    dataset = db.execute(
        select(Dataset).where(Dataset.dataset_id == dataset_id)
    ).scalar_one_or_none()
    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    task = regenerate_summary_task.delay(dataset_id=dataset_id)

    _write_audit_log(
        db,
        admin_user_id=current_admin.user_id,
        action="dataset_summary_regenerated",
        entity_type="dataset",
        entity_id=str(dataset_id),
        details={"task_id": task.id},
    )
    db.commit()

    return {"task_id": task.id, "status": "queued"}


@router.post("/datasets/{dataset_id}/soft-delete")
async def soft_delete_dataset(
    dataset_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """Soft-delete a dataset and record audit trail."""
    dataset = db.execute(
        select(Dataset).where(Dataset.dataset_id == dataset_id)
    ).scalar_one_or_none()

    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    if dataset.deleted_at is not None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Dataset already soft-deleted")

    profile_count = dataset.profile_count or 0
    dataset.deleted_at = datetime.now(timezone.utc)
    dataset.deleted_by = current_admin.user_id

    _write_audit_log(
        db,
        admin_user_id=current_admin.user_id,
        action="dataset_soft_deleted",
        entity_type="dataset",
        entity_id=str(dataset_id),
        details={"profile_count": int(profile_count)},
    )

    db.commit()
    db.refresh(dataset)

    return _serialize_dataset(dataset)


@router.post("/datasets/{dataset_id}/restore")
async def restore_dataset(
    dataset_id: int,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """Restore a previously soft-deleted dataset."""
    dataset = db.execute(
        select(Dataset).where(Dataset.dataset_id == dataset_id)
    ).scalar_one_or_none()

    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    if dataset.deleted_at is None:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Dataset is not soft-deleted")

    dataset.deleted_at = None
    dataset.deleted_by = None

    _write_audit_log(
        db,
        admin_user_id=current_admin.user_id,
        action="dataset_metadata_updated",
        entity_type="dataset",
        entity_id=str(dataset_id),
        details={"action": "restore"},
    )

    db.commit()
    db.refresh(dataset)

    return _serialize_dataset(dataset)


@router.post("/datasets/{dataset_id}/hard-delete")
async def hard_delete_dataset(
    dataset_id: int,
    payload: HardDeleteRequest,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """Validate hard-delete confirmation and queue async deletion task."""
    dataset = db.execute(
        select(Dataset).where(Dataset.dataset_id == dataset_id)
    ).scalar_one_or_none()

    if dataset is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Dataset not found")

    expected_name = (dataset.name or dataset.source_filename or "").strip()
    if not payload.confirm or not expected_name:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid confirmation payload")

    if payload.confirm_dataset_name.strip().casefold() != expected_name.casefold():
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Dataset name confirmation mismatch")

    task = hard_delete_dataset_task.delay(
        dataset_id=dataset_id,
        admin_user_id=str(current_admin.user_id),
        expected_dataset_name=expected_name,
    )

    _write_audit_log(
        db,
        admin_user_id=current_admin.user_id,
        action="hard_delete_requested",
        entity_type="dataset",
        entity_id=str(dataset_id),
        details={"dataset_name": expected_name, "task_id": task.id},
    )
    db.commit()

    return {"task_id": task.id, "status": "queued"}


@router.get("/ingestion-jobs")
async def list_admin_ingestion_jobs(
    status_filter: Optional[str] = Query(None, alias="status"),
    source: Optional[str] = Query(None),
    dataset_id: Optional[int] = Query(None),
    days: int = Query(7, ge=1),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """List ingestion jobs with admin filters and pagination."""
    valid_statuses = {"pending", "running", "succeeded", "failed"}
    if status_filter and status_filter not in valid_statuses:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid status filter")

    valid_sources = {"manual_upload", "gdac_sync"}
    if source and source not in valid_sources:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid source filter")

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    query = (
        select(IngestionJob, Dataset.name)
        .outerjoin(Dataset, Dataset.dataset_id == IngestionJob.dataset_id)
        .where(IngestionJob.created_at >= cutoff)
        .order_by(IngestionJob.created_at.desc())
    )

    if status_filter:
        query = query.where(IngestionJob.status == status_filter)
    if source:
        query = query.where(IngestionJob.source == source)
    if dataset_id is not None:
        query = query.where(IngestionJob.dataset_id == dataset_id)

    total = len(db.execute(query).all())
    rows = db.execute(query.limit(limit).offset(offset)).all()

    return {
        "jobs": [
            {
                "job_id": str(job.job_id),
                "dataset_id": job.dataset_id,
                "dataset_name": dataset_name,
                "source": job.source,
                "original_filename": job.original_filename,
                "raw_file_path": job.raw_file_path,
                "status": job.status,
                "progress_pct": job.progress_pct,
                "profiles_total": job.profiles_total,
                "profiles_ingested": job.profiles_ingested,
                "error_log": job.error_log,
                "errors": job.errors,
                "started_at": job.started_at.isoformat() if job.started_at else None,
                "completed_at": job.completed_at.isoformat() if job.completed_at else None,
                "created_at": job.created_at.isoformat() if job.created_at else None,
            }
            for job, dataset_name in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


@router.post("/ingestion-jobs/{job_id}/retry")
async def retry_ingestion_job(
    job_id: str,
    db: Session = Depends(get_db),
    current_admin: User = Depends(get_current_admin_user),
) -> dict[str, Any]:
    """Retry a failed ingestion job and reset it to pending."""
    try:
        parsed_job_id = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid job_id")

    job = db.execute(
        select(IngestionJob).where(IngestionJob.job_id == parsed_job_id)
    ).scalar_one_or_none()

    if job is None:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail="Job not found")

    if job.status != "failed":
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Only failed jobs can be retried")

    retry_path = job.raw_file_path
    if not retry_path:
        dataset = db.execute(
            select(Dataset).where(Dataset.dataset_id == job.dataset_id)
        ).scalar_one_or_none()
        retry_path = dataset.raw_file_path if dataset else None

    if not retry_path:
        raise HTTPException(status_code=status.HTTP_409_CONFLICT, detail="Job has no retriable file path")

    filename = job.original_filename or ""
    if "." in filename:
        ext = filename.lower().rsplit(".", 1)[-1]
    elif "." in retry_path:
        ext = retry_path.lower().rsplit(".", 1)[-1]
    else:
        ext = ""

    job.status = "pending"
    job.progress_pct = 0
    job.profiles_ingested = 0
    job.error_log = None
    job.errors = None
    job.started_at = None
    job.completed_at = None

    try:
        if ext == "zip":
            ingest_zip_task.delay(
                job_id=str(job.job_id),
                zip_path=retry_path,
                dataset_id=job.dataset_id,
            )
        else:
            ingest_file_task.delay(
                job_id=str(job.job_id),
                file_path=retry_path,
                dataset_id=job.dataset_id,
                original_filename=job.original_filename,
            )
    except Exception as exc:
        job.status = "failed"
        job.error_log = f"Retry dispatch failed: {str(exc)}"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Task queue unavailable. Please try again later.",
        )

    _write_audit_log(
        db,
        admin_user_id=current_admin.user_id,
        action="ingestion_job_retried",
        entity_type="ingestion_job",
        entity_id=str(job.job_id),
        details={"dataset_id": job.dataset_id},
    )

    db.commit()

    return {
        "job_id": str(job.job_id),
        "dataset_id": job.dataset_id,
        "status": "pending",
        "message": "Job retry initiated",
    }


@router.get("/ingestion-jobs/stream")
async def stream_ingestion_jobs(
    db: Session = Depends(get_db),
    _current_admin: User = Depends(get_current_admin_user),
) -> StreamingResponse:
    """Stream ingestion job updates via SSE with global polling."""

    async def event_generator():
        last_sent: dict[str, dict[str, Any]] = {}
        last_heartbeat = datetime.now(timezone.utc)

        while True:
            try:
                cutoff = datetime.now(timezone.utc) - timedelta(days=7)
                rows = db.execute(
                    select(IngestionJob, Dataset.name)
                    .outerjoin(Dataset, Dataset.dataset_id == IngestionJob.dataset_id)
                    .where(IngestionJob.created_at >= cutoff)
                    .order_by(IngestionJob.created_at.desc())
                    .limit(500)
                ).all()

                current: dict[str, dict[str, Any]] = {}
                for job, dataset_name in rows:
                    payload = {
                        "job_id": str(job.job_id),
                        "dataset_id": job.dataset_id,
                        "dataset_name": dataset_name,
                        "source": job.source,
                        "status": job.status,
                        "progress_pct": job.progress_pct,
                        "profiles_ingested": job.profiles_ingested,
                        "error_message": job.error_log,
                        "updated_at": (
                            job.completed_at.isoformat()
                            if job.completed_at
                            else (job.started_at.isoformat() if job.started_at else None)
                        ),
                    }
                    current[payload["job_id"]] = payload

                    if last_sent.get(payload["job_id"]) != payload:
                        yield _sse_event("job_update", payload)

                now = datetime.now(timezone.utc)
                if (now - last_heartbeat).total_seconds() >= 15:
                    yield _sse_event("heartbeat", {"status": "ok"})
                    last_heartbeat = now

                last_sent = current
                await asyncio.sleep(2)
            except asyncio.CancelledError:
                break
            except Exception as exc:
                logger.error("admin_ingestion_stream_error", error=str(exc))
                yield _sse_event("error", {"error": "stream_error"})
                await asyncio.sleep(2)

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


@router.get("/audit-log")
async def list_audit_log(
    admin_user_id: Optional[str] = Query(None),
    action: Optional[str] = Query(None),
    entity_type: Optional[str] = Query(None),
    days: int = Query(30, ge=1),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
    db: Session = Depends(get_db),
) -> dict[str, Any]:
    """Return paginated audit log with optional filters and admin email join."""
    parsed_admin_user_id = None
    if admin_user_id:
        try:
            parsed_admin_user_id = uuid.UUID(admin_user_id)
        except ValueError:
            raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail="Invalid admin_user_id")

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)

    query = (
        select(AdminAuditLog, User.email)
        .outerjoin(User, User.user_id == AdminAuditLog.admin_user_id)
        .where(AdminAuditLog.created_at >= cutoff)
        .order_by(AdminAuditLog.created_at.desc())
    )

    if parsed_admin_user_id:
        query = query.where(AdminAuditLog.admin_user_id == parsed_admin_user_id)
    if action:
        query = query.where(AdminAuditLog.action == action)
    if entity_type:
        query = query.where(AdminAuditLog.entity_type == entity_type)

    total = len(db.execute(query).all())
    rows = db.execute(query.limit(limit).offset(offset)).all()

    return {
        "logs": [
            {
                "log_id": str(log.log_id),
                "admin_user_id": str(log.admin_user_id) if log.admin_user_id else None,
                "admin_user_email": admin_email,
                "action": log.action,
                "entity_type": log.entity_type,
                "entity_id": log.entity_id,
                "details": log.details,
                "created_at": log.created_at.isoformat() if log.created_at else None,
            }
            for log, admin_email in rows
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }
