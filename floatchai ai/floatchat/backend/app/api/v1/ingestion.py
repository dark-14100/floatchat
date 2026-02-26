"""
FloatChat Ingestion API Router

REST API endpoints for file upload and ingestion job management.
All endpoints require admin JWT authentication.

Endpoints:
    POST   /datasets/upload          — Upload .nc/.nc4/.zip file
    GET    /datasets/jobs/{job_id}   — Get job status
    GET    /datasets/jobs            — List jobs (paginated)
    POST   /datasets/jobs/{job_id}/retry — Retry a failed job
"""

import os
import tempfile
import uuid
from pathlib import Path
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, File, Form, HTTPException, UploadFile, status
from fastapi.responses import JSONResponse
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.api.auth import get_current_admin_user
from app.config import settings
from app.db.models import Dataset, IngestionJob
from app.db.session import get_db
from app.ingestion.tasks import ingest_file_task, ingest_zip_task

logger = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/datasets",
    tags=["Ingestion"],
    dependencies=[Depends(get_current_admin_user)],
)

# Allowed file extensions
ALLOWED_EXTENSIONS = {".nc", ".nc4", ".zip"}


# =============================================================================
# POST /datasets/upload
# =============================================================================
@router.post(
    "/upload",
    status_code=status.HTTP_202_ACCEPTED,
    summary="Upload a NetCDF or ZIP file for ingestion",
    response_description="Returns job_id for tracking the ingestion",
)
async def upload_file(
    file: UploadFile = File(..., description="NetCDF (.nc/.nc4) or ZIP file"),
    dataset_name: Optional[str] = Form(None, description="Optional dataset name"),
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin_user),
):
    """
    Upload a NetCDF file or ZIP archive for ingestion.

    The file is streamed to a temporary location in chunks (never loaded
    entirely into memory), then a Celery task is dispatched for async
    processing. Returns immediately with a job_id.

    - **.nc / .nc4**: Single NetCDF file → dispatches `ingest_file_task`
    - **.zip**: ZIP archive of NetCDF files → dispatches `ingest_zip_task`
    """
    log = logger.bind(
        filename=file.filename,
        user_id=admin.get("sub"),
    )
    log.info("upload_received")

    # -------------------------------------------------------------------------
    # Validate file extension
    # -------------------------------------------------------------------------
    if not file.filename:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Filename is required",
        )

    file_ext = Path(file.filename).suffix.lower()
    if file_ext not in ALLOWED_EXTENSIONS:
        log.warning("upload_rejected_bad_extension", extension=file_ext)
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Unsupported file type. Only .nc, .nc4, and .zip files are accepted. Got: {file_ext}",
        )

    # -------------------------------------------------------------------------
    # Stream file to temp path in chunks (never load entire file into memory)
    # -------------------------------------------------------------------------
    try:
        suffix = file_ext
        tmp_fd, tmp_path = tempfile.mkstemp(suffix=suffix, prefix="floatchat_upload_")
        bytes_written = 0
        chunk_size = 1024 * 1024  # 1 MB chunks

        with os.fdopen(tmp_fd, "wb") as tmp_file:
            while True:
                chunk = await file.read(chunk_size)
                if not chunk:
                    break

                bytes_written += len(chunk)

                # Enforce max file size during streaming
                if bytes_written > settings.MAX_UPLOAD_SIZE_BYTES:
                    # Clean up temp file
                    try:
                        os.unlink(tmp_path)
                    except OSError:
                        pass
                    log.warning(
                        "upload_rejected_too_large",
                        bytes=bytes_written,
                        max_bytes=settings.MAX_UPLOAD_SIZE_BYTES,
                    )
                    raise HTTPException(
                        status_code=status.HTTP_413_REQUEST_ENTITY_TOO_LARGE,
                        detail=f"File exceeds maximum size of {settings.MAX_UPLOAD_SIZE_BYTES} bytes",
                    )

                tmp_file.write(chunk)

        log.info("upload_saved_to_temp", tmp_path=tmp_path, bytes=bytes_written)

    except HTTPException:
        raise
    except Exception as e:
        log.error("upload_stream_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to save uploaded file",
        )

    # -------------------------------------------------------------------------
    # Create Dataset and IngestionJob records synchronously
    # -------------------------------------------------------------------------
    try:
        dataset = Dataset(
            name=dataset_name or file.filename,
            source_filename=file.filename,
            is_active=True,
            dataset_version=1,
        )
        db.add(dataset)
        db.flush()

        job = IngestionJob(
            dataset_id=dataset.dataset_id,
            original_filename=file.filename,
            status="pending",
            progress_pct=0,
            profiles_ingested=0,
        )
        db.add(job)
        db.flush()

        job_id = str(job.job_id)
        dataset_id = dataset.dataset_id

        db.commit()

        log.info(
            "records_created",
            job_id=job_id,
            dataset_id=dataset_id,
        )

    except Exception as e:
        db.rollback()
        # Clean up temp file
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        log.error("record_creation_failed", error=str(e))
        raise HTTPException(
            status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
            detail="Failed to create ingestion records",
        )

    # -------------------------------------------------------------------------
    # Dispatch the appropriate Celery task
    # -------------------------------------------------------------------------
    try:
        if file_ext == ".zip":
            ingest_zip_task.delay(
                job_id=job_id,
                zip_path=tmp_path,
                dataset_id=dataset_id,
            )
            log.info("zip_task_dispatched", job_id=job_id)
        else:
            ingest_file_task.delay(
                job_id=job_id,
                file_path=tmp_path,
                dataset_id=dataset_id,
                original_filename=file.filename,
            )
            log.info("file_task_dispatched", job_id=job_id)

    except Exception as e:
        log.error("task_dispatch_failed", error=str(e), job_id=job_id)
        # Mark the job as failed since the task couldn't be dispatched
        try:
            job_record = db.execute(
                select(IngestionJob).where(IngestionJob.job_id == uuid.UUID(job_id))
            ).scalar_one_or_none()
            if job_record:
                job_record.status = "failed"
                job_record.error_log = f"Task dispatch failed: {str(e)}"
                db.commit()
        except Exception:
            pass

        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Task queue unavailable. Please try again later.",
        )

    # -------------------------------------------------------------------------
    # Return 202 Accepted
    # -------------------------------------------------------------------------
    return JSONResponse(
        status_code=status.HTTP_202_ACCEPTED,
        content={
            "job_id": job_id,
            "dataset_id": dataset_id,
            "status": "pending",
            "message": f"File '{file.filename}' accepted for ingestion",
        },
    )


# =============================================================================
# GET /datasets/jobs/{job_id}
# =============================================================================
@router.get(
    "/jobs/{job_id}",
    summary="Get ingestion job status",
    response_description="Job status, progress, errors, and timestamps",
)
async def get_job_status(
    job_id: str,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin_user),
):
    """
    Get the current status of an ingestion job.

    Returns status, progress percentage, error list, and timestamps.
    """
    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid job_id format. Must be a valid UUID.",
        )

    job = db.execute(
        select(IngestionJob).where(IngestionJob.job_id == job_uuid)
    ).scalar_one_or_none()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    return {
        "job_id": str(job.job_id),
        "dataset_id": job.dataset_id,
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


# =============================================================================
# GET /datasets/jobs
# =============================================================================
@router.get(
    "/jobs",
    summary="List ingestion jobs",
    response_description="Paginated list of ingestion jobs",
)
async def list_jobs(
    status_filter: Optional[str] = None,
    limit: int = 20,
    offset: int = 0,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin_user),
):
    """
    List ingestion jobs with optional status filter and pagination.

    Query params:
    - **status_filter**: Filter by status (pending, running, succeeded, failed)
    - **limit**: Max results per page (default 20, max 100)
    - **offset**: Pagination offset (default 0)
    """
    # Clamp limit
    limit = min(max(1, limit), 100)
    offset = max(0, offset)

    # Validate status filter
    valid_statuses = {"pending", "running", "succeeded", "failed"}
    if status_filter and status_filter not in valid_statuses:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Invalid status filter. Must be one of: {', '.join(valid_statuses)}",
        )

    # Build query
    query = select(IngestionJob).order_by(IngestionJob.created_at.desc())

    if status_filter:
        query = query.where(IngestionJob.status == status_filter)

    # Get total count
    from sqlalchemy import func

    count_query = select(func.count(IngestionJob.job_id))
    if status_filter:
        count_query = count_query.where(IngestionJob.status == status_filter)
    total = db.execute(count_query).scalar() or 0

    # Apply pagination
    query = query.limit(limit).offset(offset)
    jobs = db.execute(query).scalars().all()

    return {
        "jobs": [
            {
                "job_id": str(j.job_id),
                "dataset_id": j.dataset_id,
                "original_filename": j.original_filename,
                "status": j.status,
                "progress_pct": j.progress_pct,
                "profiles_total": j.profiles_total,
                "profiles_ingested": j.profiles_ingested,
                "started_at": j.started_at.isoformat() if j.started_at else None,
                "completed_at": j.completed_at.isoformat() if j.completed_at else None,
                "created_at": j.created_at.isoformat() if j.created_at else None,
            }
            for j in jobs
        ],
        "total": total,
        "limit": limit,
        "offset": offset,
    }


# =============================================================================
# POST /datasets/jobs/{job_id}/retry
# =============================================================================
@router.post(
    "/jobs/{job_id}/retry",
    summary="Retry a failed ingestion job",
    response_description="Returns new job status after retry",
)
async def retry_job(
    job_id: str,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin_user),
):
    """
    Retry a failed ingestion job.

    Only jobs with status 'failed' can be retried. Resets the job's
    status, progress, errors, and timestamps, then re-dispatches
    the Celery task.
    """
    log = logger.bind(job_id=job_id, user_id=admin.get("sub"))

    try:
        job_uuid = uuid.UUID(job_id)
    except ValueError:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid job_id format. Must be a valid UUID.",
        )

    job = db.execute(
        select(IngestionJob).where(IngestionJob.job_id == job_uuid)
    ).scalar_one_or_none()

    if not job:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Job {job_id} not found",
        )

    if job.status != "failed":
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"Only failed jobs can be retried. Current status: {job.status}",
        )

    # Reset job fields
    job.status = "pending"
    job.progress_pct = 0
    job.profiles_ingested = 0
    job.error_log = None
    job.errors = None
    job.started_at = None
    job.completed_at = None

    db.commit()

    log.info("job_retry_initiated")

    # Re-dispatch the appropriate Celery task
    try:
        filename = job.original_filename or ""
        file_ext = Path(filename).suffix.lower()
        file_path = job.raw_file_path

        if file_ext == ".zip":
            ingest_zip_task.delay(
                job_id=str(job.job_id),
                zip_path=file_path,
                dataset_id=job.dataset_id,
            )
        else:
            ingest_file_task.delay(
                job_id=str(job.job_id),
                file_path=file_path,
                dataset_id=job.dataset_id,
                original_filename=job.original_filename,
            )

        log.info("retry_task_dispatched")

    except Exception as e:
        log.error("retry_dispatch_failed", error=str(e))
        job.status = "failed"
        job.error_log = f"Retry dispatch failed: {str(e)}"
        db.commit()
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Task queue unavailable. Please try again later.",
        )

    return {
        "job_id": str(job.job_id),
        "dataset_id": job.dataset_id,
        "status": "pending",
        "message": "Job retry initiated",
    }
