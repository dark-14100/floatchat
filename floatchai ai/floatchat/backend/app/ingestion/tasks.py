"""
FloatChat Celery Task Definitions

Async task processing for the data ingestion pipeline.
Orchestrates the full pipeline: upload → validate → parse → clean → write → metadata.

Tasks:
    ingest_file_task: Process a single NetCDF file
    ingest_zip_task: Process a ZIP archive containing NetCDF files
    retry_stale_jobs: Periodic task to retry stuck jobs

Pipeline Steps (ingest_file_task):
    1. Set job status to 'running' (0%)
    2. Upload raw file to S3/MinIO (10%)
    3. Validate the NetCDF file (15%)
    4. Parse all profiles from the file (20%)
    5. Clean and normalize the profiles (40%)
    6. Write all profiles and measurements to DB (80%)
    7. Update dataset metadata and generate LLM summary (90%)
    8. Set job status to 'succeeded' (100%)
"""

import os
import tempfile
import traceback
import zipfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

import structlog

from app.celery_app import celery
from app.config import settings
from app.db.session import SessionLocal
from app.ingestion.cleaner import clean_measurements, clean_parse_result
from app.ingestion.metadata import update_dataset_metadata
from app.ingestion.parser import (
    parse_netcdf_all_profiles,
    parse_netcdf_file,
    validate_file,
)
from app.ingestion.writer import (
    update_job_status,
    write_dataset,
    write_parse_result,
)
from app.storage.s3 import upload_file_to_s3

logger = structlog.get_logger(__name__)


@celery.task(
    name="app.ingestion.tasks.ingest_file_task",
    bind=True,
    autoretry_for=(ConnectionError, OSError),
    max_retries=3,
    retry_backoff=True,
    retry_backoff_max=300,
    retry_jitter=True,
    acks_late=True,
)
def ingest_file_task(
    self,
    job_id: str,
    file_path: str,
    dataset_id: int,
    original_filename: Optional[str] = None,
) -> dict:
    """
    Main pipeline task: process a single NetCDF file.

    This task is idempotent — running the same file twice produces
    identical DB state with no duplicates.

    Args:
        self: Celery task instance (bound)
        job_id: UUID of the ingestion job
        file_path: Local path to the NetCDF file
        dataset_id: FK to datasets table
        original_filename: Original uploaded filename

    Returns:
        Dict with ingestion results summary
    """
    log = logger.bind(
        job_id=job_id,
        file_path=file_path,
        dataset_id=dataset_id,
    )
    log.info("ingest_file_task_started")

    db = SessionLocal()

    try:
        # =====================================================================
        # Step 1: Set job to running (0%)
        # =====================================================================
        update_job_status(db, job_id, status="running", progress_pct=0)
        db.commit()
        log.info("job_status_set_running")

        # =====================================================================
        # Step 2: Upload raw file to S3/MinIO (10%)
        # =====================================================================
        filename = original_filename or Path(file_path).name
        s3_key = f"raw-uploads/{dataset_id}/{filename}"

        try:
            upload_file_to_s3(file_path, s3_key, job_id=job_id)
        except Exception as e:
            log.error("s3_upload_failed", error=str(e))
            update_job_status(
                db, job_id,
                status="failed",
                progress_pct=5,
                error_log=f"S3 upload failed: {str(e)}",
                errors=[{"stage": "s3_upload", "error": str(e)}],
            )
            db.commit()
            return {"success": False, "error": f"S3 upload failed: {str(e)}"}

        update_job_status(db, job_id, status="running", progress_pct=10)
        db.commit()
        log.info("s3_upload_complete", s3_key=s3_key)

        # =====================================================================
        # Step 3: Validate the NetCDF file (15%)
        # =====================================================================
        is_valid, validation_error = validate_file(file_path)
        if not is_valid:
            log.warning("validation_failed", error=validation_error)
            update_job_status(
                db, job_id,
                status="failed",
                progress_pct=15,
                error_log=f"Validation failed: {validation_error}",
                errors=[{"stage": "validation", "error": validation_error}],
            )
            db.commit()
            return {"success": False, "error": validation_error}

        update_job_status(db, job_id, status="running", progress_pct=15)
        db.commit()
        log.info("validation_passed")

        # =====================================================================
        # Step 4: Parse all profiles from the file (20%)
        # =====================================================================
        log.info("parsing_started")
        parse_results = parse_netcdf_all_profiles(file_path, job_id=job_id)

        # Filter out failed parses
        successful_parses = [pr for pr in parse_results if pr.success]
        failed_parses = [pr for pr in parse_results if not pr.success]

        if failed_parses:
            for fp in failed_parses:
                log.warning("profile_parse_failed", error=fp.error_message)

        if not successful_parses:
            error_msg = "No profiles could be parsed from file"
            if failed_parses:
                error_msg = failed_parses[0].error_message or error_msg
            log.error("all_parses_failed", error=error_msg)
            update_job_status(
                db, job_id,
                status="failed",
                progress_pct=20,
                error_log=error_msg,
                errors=[{"stage": "parsing", "error": error_msg}],
            )
            db.commit()
            return {"success": False, "error": error_msg}

        profiles_total = len(successful_parses)
        update_job_status(
            db, job_id,
            status="running",
            progress_pct=20,
            profiles_total=profiles_total,
        )
        db.commit()
        log.info("parsing_complete", profiles_total=profiles_total)

        # =====================================================================
        # Step 5: Clean and normalize the profiles (40%)
        # =====================================================================
        log.info("cleaning_started")
        cleaning_results = []
        total_outliers = 0

        for pr in successful_parses:
            cr = clean_parse_result(pr, job_id=job_id)
            cleaning_results.append(cr)
            if cr.success:
                total_outliers += cr.stats.flagged_records

        update_job_status(db, job_id, status="running", progress_pct=40)
        db.commit()
        log.info(
            "cleaning_complete",
            total_profiles=len(cleaning_results),
            total_outliers=total_outliers,
        )

        # =====================================================================
        # Step 6: Write all profiles and measurements to DB (80%)
        # =====================================================================
        log.info("db_write_started")
        profiles_ingested = 0
        write_errors = []

        try:
            for i, (pr, cr) in enumerate(zip(successful_parses, cleaning_results)):
                result = write_parse_result(
                    db=db,
                    parse_result=pr,
                    cleaning_result=cr,
                    dataset_id=dataset_id,
                    job_id=job_id,
                )

                if result.get("success"):
                    profiles_ingested += 1
                else:
                    write_errors.append({
                        "profile_index": i,
                        "error": result.get("error", "Unknown write error"),
                    })

                # Update progress between 40% and 80%
                if profiles_total > 0:
                    write_progress = 40 + int(40 * (i + 1) / profiles_total)
                    update_job_status(
                        db, job_id,
                        status="running",
                        progress_pct=write_progress,
                        profiles_ingested=profiles_ingested,
                    )

            # Commit the entire transaction
            db.commit()

        except Exception as e:
            db.rollback()
            error_msg = f"Database write failed: {str(e)}"
            log.error("db_write_failed", error=str(e), traceback=traceback.format_exc())
            update_job_status(
                db, job_id,
                status="failed",
                progress_pct=50,
                error_log=error_msg,
                errors=[{"stage": "db_write", "error": str(e)}],
            )
            db.commit()
            return {"success": False, "error": error_msg}

        update_job_status(
            db, job_id,
            status="running",
            progress_pct=80,
            profiles_ingested=profiles_ingested,
        )
        db.commit()
        log.info(
            "db_write_complete",
            profiles_ingested=profiles_ingested,
            write_errors=len(write_errors),
        )

        # =====================================================================
        # Step 7: Update dataset metadata and generate LLM summary (90%)
        # =====================================================================
        log.info("metadata_update_started")
        try:
            update_dataset_metadata(db, dataset_id, job_id=job_id)
            db.commit()
        except Exception as e:
            # Metadata failure should not fail the job
            db.rollback()
            log.warning("metadata_update_failed", error=str(e))

        update_job_status(db, job_id, status="running", progress_pct=90)
        db.commit()
        log.info("metadata_update_complete")

        # =====================================================================
        # Step 8: Set job to succeeded (100%)
        # =====================================================================
        errors_list = write_errors if write_errors else None
        update_job_status(
            db, job_id,
            status="succeeded",
            progress_pct=100,
            profiles_ingested=profiles_ingested,
            errors=errors_list,
        )
        db.commit()

        # =============================================================
        # Step 9: Enqueue post-ingestion search indexing (fire-and-forget)
        # =============================================================
        try:
            from app.search.tasks import index_dataset_task
            index_dataset_task.delay(dataset_id=dataset_id)
            log.info("search_indexing_enqueued", dataset_id=dataset_id)
        except Exception as idx_err:
            # Indexing failure must never fail the ingestion job
            log.warning(
                "search_indexing_enqueue_failed",
                dataset_id=dataset_id,
                error=str(idx_err),
            )

        summary = {
            "success": True,
            "job_id": job_id,
            "dataset_id": dataset_id,
            "profiles_total": profiles_total,
            "profiles_ingested": profiles_ingested,
            "outlier_measurements": total_outliers,
            "write_errors": len(write_errors),
        }

        log.info("job_complete", **summary)
        return summary

    except Exception as e:
        # Catch-all: roll back and mark job as failed
        db.rollback()
        error_msg = f"Unexpected error: {str(e)}"
        tb = traceback.format_exc()
        log.error("job_failed", error=str(e), traceback=tb)

        try:
            update_job_status(
                db, job_id,
                status="failed",
                error_log=f"{error_msg}\n\n{tb}",
                errors=[{"stage": "unexpected", "error": str(e)}],
            )
            db.commit()
        except Exception:
            log.error("failed_to_update_job_status_after_error")

        # Report to Sentry if configured
        try:
            import sentry_sdk
            sentry_sdk.capture_exception(e)
        except Exception:
            pass

        return {"success": False, "error": error_msg}

    finally:
        db.close()


@celery.task(
    name="app.ingestion.tasks.ingest_zip_task",
    bind=True,
    acks_late=True,
)
def ingest_zip_task(
    self,
    job_id: str,
    zip_path: str,
    dataset_id: int,
) -> dict:
    """
    Process a ZIP archive containing NetCDF files.

    Extracts the ZIP, validates each file, and dispatches
    ingest_file_task for each valid .nc/.nc4 file.

    Invalid files are recorded in the job's errors JSONB array
    but do not fail the entire job.

    Args:
        self: Celery task instance (bound)
        job_id: UUID of the ingestion job
        zip_path: Local path to the ZIP file
        dataset_id: FK to datasets table

    Returns:
        Dict with processing summary
    """
    log = logger.bind(job_id=job_id, zip_path=zip_path)
    log.info("ingest_zip_task_started")

    db = SessionLocal()

    try:
        update_job_status(db, job_id, status="running", progress_pct=0)
        db.commit()

        # Extract ZIP to temp directory
        with tempfile.TemporaryDirectory() as tmpdir:
            try:
                with zipfile.ZipFile(zip_path, "r") as zf:
                    zf.extractall(tmpdir)
            except zipfile.BadZipFile as e:
                error_msg = f"Invalid ZIP file: {str(e)}"
                log.error("zip_extraction_failed", error=error_msg)
                update_job_status(
                    db, job_id,
                    status="failed",
                    error_log=error_msg,
                    errors=[{"stage": "zip_extract", "error": str(e)}],
                )
                db.commit()
                return {"success": False, "error": error_msg}

            # Find all NetCDF files in extracted contents
            nc_files = []
            for root, _dirs, files in os.walk(tmpdir):
                for f in files:
                    if f.lower().endswith((".nc", ".nc4")):
                        nc_files.append(os.path.join(root, f))

            if not nc_files:
                error_msg = "No .nc or .nc4 files found in ZIP archive"
                log.warning("no_netcdf_in_zip")
                update_job_status(
                    db, job_id,
                    status="failed",
                    error_log=error_msg,
                    errors=[{"stage": "zip_scan", "error": error_msg}],
                )
                db.commit()
                return {"success": False, "error": error_msg}

            log.info("zip_extracted", file_count=len(nc_files))
            update_job_status(
                db, job_id,
                status="running",
                progress_pct=10,
                profiles_total=len(nc_files),
            )
            db.commit()

            # Validate and dispatch each file
            dispatched = 0
            errors = []

            for i, nc_path in enumerate(nc_files):
                filename = Path(nc_path).name

                # Validate before dispatching
                is_valid, validation_error = validate_file(nc_path)

                if not is_valid:
                    log.warning(
                        "zip_file_validation_failed",
                        filename=filename,
                        error=validation_error,
                    )
                    errors.append({
                        "filename": filename,
                        "stage": "validation",
                        "error": validation_error,
                    })
                    continue

                # Create a new dataset record for each file in the ZIP
                file_dataset_id = write_dataset(
                    db=db,
                    source_filename=filename,
                    name=filename,
                    job_id=job_id,
                )
                db.commit()

                # Dispatch subtask for this file
                ingest_file_task.delay(
                    job_id=job_id,
                    file_path=nc_path,
                    dataset_id=file_dataset_id,
                    original_filename=filename,
                )
                dispatched += 1

                # Update progress
                progress = 10 + int(90 * (i + 1) / len(nc_files))
                update_job_status(
                    db, job_id,
                    status="running",
                    progress_pct=progress,
                    profiles_ingested=dispatched,
                    errors=errors if errors else None,
                )
                db.commit()

            # Final status
            if dispatched == 0:
                update_job_status(
                    db, job_id,
                    status="failed",
                    progress_pct=100,
                    error_log="No valid NetCDF files in ZIP",
                    errors=errors,
                )
                db.commit()
                return {
                    "success": False,
                    "error": "No valid NetCDF files in ZIP",
                    "errors": errors,
                }
            else:
                update_job_status(
                    db, job_id,
                    status="succeeded",
                    progress_pct=100,
                    profiles_ingested=dispatched,
                    errors=errors if errors else None,
                )
                db.commit()

            summary = {
                "success": True,
                "job_id": job_id,
                "files_found": len(nc_files),
                "files_dispatched": dispatched,
                "files_failed": len(errors),
                "errors": errors,
            }
            log.info("zip_task_complete", **summary)
            return summary

    except Exception as e:
        db.rollback()
        tb = traceback.format_exc()
        log.error("zip_task_failed", error=str(e), traceback=tb)

        try:
            update_job_status(
                db, job_id,
                status="failed",
                error_log=f"Unexpected error: {str(e)}\n\n{tb}",
                errors=[{"stage": "unexpected", "error": str(e)}],
            )
            db.commit()
        except Exception:
            pass

        try:
            import sentry_sdk
            sentry_sdk.capture_exception(e)
        except Exception:
            pass

        return {"success": False, "error": str(e)}

    finally:
        db.close()


@celery.task(
    name="app.ingestion.tasks.retry_stale_jobs",
    bind=True,
)
def retry_stale_jobs(self) -> dict:
    """
    Periodic task to find and retry stale/stuck jobs.

    A job is considered stale if:
    - Status is 'running' and started_at is more than 30 minutes ago
    - Status is 'pending' and created_at is more than 15 minutes ago

    Marks stale jobs as 'failed' so they can be manually retried.

    Returns:
        Dict with count of stale jobs found
    """
    from sqlalchemy import select

    from app.db.models import IngestionJob

    log = logger.bind(task="retry_stale_jobs")
    log.info("retry_stale_jobs_started")

    db = SessionLocal()
    stale_count = 0

    try:
        now = datetime.now(timezone.utc)

        # Find stale running jobs (started > 30 min ago)
        stale_running = db.execute(
            select(IngestionJob).where(
                IngestionJob.status == "running",
                IngestionJob.started_at.isnot(None),
            )
        ).scalars().all()

        for job in stale_running:
            if job.started_at and (now - job.started_at).total_seconds() > 1800:
                log.warning(
                    "stale_running_job_found",
                    job_id=str(job.job_id),
                    started_at=str(job.started_at),
                )
                job.status = "failed"
                job.error_log = "Job marked as failed: exceeded 30-minute running limit"
                job.completed_at = now
                stale_count += 1

        # Find stale pending jobs (created > 15 min ago)
        stale_pending = db.execute(
            select(IngestionJob).where(
                IngestionJob.status == "pending",
            )
        ).scalars().all()

        for job in stale_pending:
            if job.created_at and (now - job.created_at).total_seconds() > 900:
                log.warning(
                    "stale_pending_job_found",
                    job_id=str(job.job_id),
                    created_at=str(job.created_at),
                )
                job.status = "failed"
                job.error_log = "Job marked as failed: exceeded 15-minute pending limit"
                job.completed_at = now
                stale_count += 1

        db.commit()

        log.info("retry_stale_jobs_complete", stale_count=stale_count)
        return {"stale_jobs_found": stale_count}

    except Exception as e:
        db.rollback()
        log.error("retry_stale_jobs_failed", error=str(e))
        return {"error": str(e)}
    finally:
        db.close()
