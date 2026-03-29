"""Feature 10 admin ingestion API tests."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest

from app.db.models import Dataset, IngestionJob


@pytest.fixture(autouse=True)
def _sqlite_geo_functions(db_session):
    raw = db_session.connection().connection
    raw.create_function("AsBinary", 1, lambda x: x)


def _create_dataset(db_session, name: str = "Dataset") -> Dataset:
    ds = Dataset(
        name=name,
        source_filename=f"{name}.nc",
        is_active=True,
        is_public=True,
        dataset_version=1,
    )
    db_session.add(ds)
    db_session.commit()
    return ds


def _create_job(
    db_session,
    *,
    dataset: Dataset,
    status: str,
    source: str = "manual_upload",
    filename: str = "file.nc",
    raw_file_path: str | None = "s3://bucket/file.nc",
) -> IngestionJob:
    job = IngestionJob(
        dataset_id=dataset.dataset_id,
        original_filename=filename,
        raw_file_path=raw_file_path,
        status=status,
        source=source,
        progress_pct=55 if status == "failed" else 0,
        profiles_total=100,
        profiles_ingested=25,
        error_log="boom" if status == "failed" else None,
        errors=[{"stage": "parse", "error": "boom"}] if status == "failed" else None,
        started_at=datetime.now(UTC),
        completed_at=datetime.now(UTC) if status == "failed" else None,
    )
    db_session.add(job)
    db_session.commit()
    db_session.refresh(job)
    return job


def test_admin_ingestion_list_requires_admin(client, researcher_headers):
    response = client.get("/api/v1/admin/ingestion-jobs", headers=researcher_headers)
    assert response.status_code == 403


def test_admin_ingestion_list_filters_status_and_source(client, db_session, admin_headers):
    dataset = _create_dataset(db_session, name="IngestionFilters")
    _create_job(db_session, dataset=dataset, status="failed", source="manual_upload", filename="failed.nc")
    _create_job(db_session, dataset=dataset, status="succeeded", source="gdac_sync", filename="success.nc")

    response = client.get(
        "/api/v1/admin/ingestion-jobs?status=failed&source=manual_upload",
        headers=admin_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["jobs"][0]["status"] == "failed"
    assert payload["jobs"][0]["source"] == "manual_upload"


def test_retry_failed_job_dispatches_file_task_and_resets_state(client, db_session, admin_headers, monkeypatch):
    dataset = _create_dataset(db_session, name="RetryFile")
    job = _create_job(
        db_session,
        dataset=dataset,
        status="failed",
        filename="retry.nc",
        raw_file_path="tmp/retry.nc",
    )

    from app.api.v1 import admin as admin_api

    file_delay = MagicMock()
    monkeypatch.setattr(admin_api.ingest_file_task, "delay", file_delay)
    monkeypatch.setattr(admin_api.ingest_zip_task, "delay", MagicMock())

    response = client.post(
        f"/api/v1/admin/ingestion-jobs/{job.job_id}/retry",
        headers=admin_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "pending"

    db_session.refresh(job)
    assert job.status == "pending"
    assert job.progress_pct == 0
    assert job.profiles_ingested == 0
    assert job.error_log is None
    assert job.errors is None

    file_delay.assert_called_once_with(
        job_id=str(job.job_id),
        file_path="tmp/retry.nc",
        dataset_id=dataset.dataset_id,
        original_filename="retry.nc",
    )


def test_retry_failed_zip_job_dispatches_zip_task(client, db_session, admin_headers, monkeypatch):
    dataset = _create_dataset(db_session, name="RetryZip")
    job = _create_job(
        db_session,
        dataset=dataset,
        status="failed",
        filename="archive.zip",
        raw_file_path="tmp/archive.zip",
    )

    from app.api.v1 import admin as admin_api

    zip_delay = MagicMock()
    monkeypatch.setattr(admin_api.ingest_zip_task, "delay", zip_delay)
    monkeypatch.setattr(admin_api.ingest_file_task, "delay", MagicMock())

    response = client.post(
        f"/api/v1/admin/ingestion-jobs/{job.job_id}/retry",
        headers=admin_headers,
    )

    assert response.status_code == 200
    zip_delay.assert_called_once_with(
        job_id=str(job.job_id),
        zip_path="tmp/archive.zip",
        dataset_id=dataset.dataset_id,
    )


def test_retry_non_failed_job_returns_409(client, db_session, admin_headers):
    dataset = _create_dataset(db_session, name="NoRetry")
    job = _create_job(db_session, dataset=dataset, status="running", filename="running.nc")

    response = client.post(
        f"/api/v1/admin/ingestion-jobs/{job.job_id}/retry",
        headers=admin_headers,
    )

    assert response.status_code == 409


def test_ingestion_stream_endpoint_requires_admin(client, researcher_headers):
    response = client.get("/api/v1/admin/ingestion-jobs/stream", headers=researcher_headers)
    assert response.status_code == 403
