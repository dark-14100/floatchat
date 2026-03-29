"""Celery tasks for admin dataset management operations."""

from __future__ import annotations

from datetime import datetime, timezone
import uuid

import structlog
from sqlalchemy import delete, func, select

from app.celery_app import celery
from app.db.models import AdminAuditLog, Anomaly, Dataset, IngestionJob, Measurement, Profile
from app.db.session import SessionLocal
from app.ingestion.metadata import compute_dataset_metadata, generate_llm_summary
from app.storage.s3 import delete_file_from_s3

logger = structlog.get_logger(__name__)


def _write_audit_log(
    db,
    *,
    admin_user_id: uuid.UUID | None,
    action: str,
    entity_type: str,
    entity_id: str,
    details: dict | None = None,
) -> None:
    """Insert a single audit log row in the active DB transaction."""
    db.add(
        AdminAuditLog(
            admin_user_id=admin_user_id,
            action=action,
            entity_type=entity_type,
            entity_id=entity_id,
            details=details,
        )
    )


@celery.task(name="app.admin.tasks.regenerate_summary_task", bind=True)
def regenerate_summary_task(self, dataset_id: int) -> dict:
    """Recompute metadata context and regenerate LLM summary for one dataset."""
    log = logger.bind(task="regenerate_summary_task", dataset_id=dataset_id)
    db = SessionLocal()

    try:
        dataset = db.execute(
            select(Dataset).where(Dataset.dataset_id == dataset_id)
        ).scalar_one_or_none()

        if dataset is None:
            log.warning("regenerate_summary_dataset_not_found")
            return {"success": False, "error": "dataset_not_found", "dataset_id": dataset_id}

        metadata = compute_dataset_metadata(db, dataset_id)
        summary = generate_llm_summary(
            metadata=metadata,
            dataset_name=dataset.name,
            job_id=str(getattr(self.request, "id", "")) or None,
        )

        dataset.summary_text = summary
        db.commit()

        log.info("regenerate_summary_complete", summary_length=len(summary))
        return {
            "success": True,
            "dataset_id": dataset_id,
            "summary_length": len(summary),
        }

    except Exception as exc:
        db.rollback()
        log.error("regenerate_summary_failed", error=str(exc))
        return {"success": False, "error": str(exc), "dataset_id": dataset_id}
    finally:
        db.close()


@celery.task(name="app.admin.tasks.hard_delete_dataset_task", bind=True)
def hard_delete_dataset_task(
    self,
    dataset_id: int,
    admin_user_id: str,
    expected_dataset_name: str,
) -> dict:
    """Hard-delete a dataset and related rows, then best-effort delete storage files."""
    log = logger.bind(task="hard_delete_dataset_task", dataset_id=dataset_id)
    db = SessionLocal()

    s3_paths: list[str] = []

    try:
        dataset = db.execute(
            select(Dataset).where(Dataset.dataset_id == dataset_id)
        ).scalar_one_or_none()
        if dataset is None:
            log.warning("hard_delete_dataset_not_found")
            return {"success": False, "error": "dataset_not_found", "dataset_id": dataset_id}

        dataset_name_for_match = (dataset.name or dataset.source_filename or "").strip()
        if dataset_name_for_match.casefold() != expected_dataset_name.strip().casefold():
            log.warning("hard_delete_name_mismatch")
            return {
                "success": False,
                "error": "dataset_name_mismatch",
                "dataset_id": dataset_id,
            }

        # Collect all candidate S3 paths before deleting ingestion jobs/dataset.
        job_paths = db.execute(
            select(IngestionJob.raw_file_path).where(
                IngestionJob.dataset_id == dataset_id,
                IngestionJob.raw_file_path.isnot(None),
            )
        ).scalars().all()
        s3_paths.extend([p for p in job_paths if p])
        if dataset.raw_file_path:
            s3_paths.append(dataset.raw_file_path)
        s3_paths = sorted(set(s3_paths))

        profile_ids = db.execute(
            select(Profile.profile_id).where(Profile.dataset_id == dataset_id)
        ).scalars().all()

        profiles_deleted = len(profile_ids)
        measurements_deleted = 0
        anomalies_deleted = 0

        if profile_ids:
            measurements_deleted = db.execute(
                select(func.count(Measurement.measurement_id)).where(
                    Measurement.profile_id.in_(profile_ids)
                )
            ).scalar_one() or 0

            anomalies_deleted = db.execute(
                select(func.count(Anomaly.anomaly_id)).where(
                    Anomaly.profile_id.in_(profile_ids)
                )
            ).scalar_one() or 0

            db.execute(delete(Anomaly).where(Anomaly.profile_id.in_(profile_ids)))

        # Measurements are removed by FK cascade when profiles are deleted.
        db.execute(delete(Profile).where(Profile.dataset_id == dataset_id))
        ingestion_jobs_deleted = db.execute(
            delete(IngestionJob).where(IngestionJob.dataset_id == dataset_id)
        ).rowcount or 0
        db.execute(delete(Dataset).where(Dataset.dataset_id == dataset_id))

        admin_uuid = None
        try:
            admin_uuid = uuid.UUID(admin_user_id)
        except ValueError:
            pass

        _write_audit_log(
            db,
            admin_user_id=admin_uuid,
            action="hard_delete_completed",
            entity_type="dataset",
            entity_id=str(dataset_id),
            details={
                "profiles_deleted": int(profiles_deleted),
                "measurements_deleted": int(measurements_deleted),
                "anomalies_deleted": int(anomalies_deleted),
                "ingestion_jobs_deleted": int(ingestion_jobs_deleted),
                "files_deleted": len(s3_paths),
                "completed_at": datetime.now(timezone.utc).isoformat(),
            },
        )

        db.commit()

        files_deleted = 0
        for s3_key in s3_paths:
            try:
                delete_file_from_s3(s3_key, job_id=str(getattr(self.request, "id", "")) or None)
                files_deleted += 1
            except Exception as exc:
                # Storage cleanup is best-effort by design.
                log.error("hard_delete_s3_cleanup_failed", s3_key=s3_key, error=str(exc))

        result = {
            "success": True,
            "dataset_id": dataset_id,
            "profiles_deleted": int(profiles_deleted),
            "measurements_deleted": int(measurements_deleted),
            "anomalies_deleted": int(anomalies_deleted),
            "ingestion_jobs_deleted": int(ingestion_jobs_deleted),
            "files_deleted": int(files_deleted),
            "files_targeted": len(s3_paths),
        }
        log.info("hard_delete_completed", **result)
        return result

    except Exception as exc:
        db.rollback()
        log.error("hard_delete_failed", error=str(exc))
        return {"success": False, "error": str(exc), "dataset_id": dataset_id}
    finally:
        db.close()
