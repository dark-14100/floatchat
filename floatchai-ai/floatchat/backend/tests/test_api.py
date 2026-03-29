"""
API endpoint integration tests.

Tests the FastAPI ingestion endpoints with:
- SQLite in-memory database (via conftest fixtures)
- Mocked Celery tasks (no broker needed)
- Real JWT auth validation

PRD §9.2 coverage:
- test_upload_file_returns_202
- test_upload_creates_dataset_and_job
- test_upload_rejects_bad_extension
- test_upload_requires_auth
- test_upload_requires_admin
- test_get_job_status
- test_list_jobs_paginated
- test_list_jobs_status_filter
- test_retry_failed_job (partial — §9.2 bullet 5)
- test_retry_non_failed_job_rejected
"""

import io
import uuid
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import Dataset, IngestionJob

FIXTURES_DIR = Path(__file__).parent / "fixtures"
CORE_FILE = FIXTURES_DIR / "core_single_profile.nc"


# =========================================================================
# Helpers
# =========================================================================
def _auth_header(token: str) -> dict:
    return {"Authorization": f"Bearer {token}"}


def _create_job(db: Session, *, status: str = "pending", filename: str = "f.nc") -> str:
    """Create a Dataset + IngestionJob directly and return job_id string."""
    ds = Dataset(
        name=filename,
        source_filename=filename,
        is_active=True,
        dataset_version=1,
    )
    db.add(ds)
    db.flush()

    job = IngestionJob(
        dataset_id=ds.dataset_id,
        original_filename=filename,
        status=status,
        progress_pct=0,
        profiles_ingested=0,
    )
    db.add(job)
    db.flush()
    db.commit()
    return str(job.job_id)


# =========================================================================
# POST /api/v1/datasets/upload
# =========================================================================
class TestUploadFile:

    @patch("app.api.v1.ingestion.ingest_file_task")
    def test_upload_nc_returns_202(self, mock_task, client: TestClient, admin_token: str):
        """Valid .nc upload returns 202 Accepted with job_id."""
        mock_task.delay = MagicMock()

        data = b"fake-netcdf-data"
        resp = client.post(
            "/api/v1/datasets/upload",
            files={"file": ("test.nc", io.BytesIO(data), "application/octet-stream")},
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 202
        body = resp.json()
        assert "job_id" in body
        assert body["status"] == "pending"
        # Celery task dispatched
        mock_task.delay.assert_called_once()

    @patch("app.api.v1.ingestion.ingest_file_task")
    def test_upload_creates_db_records(self, mock_task, client: TestClient, admin_token: str, db_session: Session):
        """Upload should create a Dataset and IngestionJob row."""
        mock_task.delay = MagicMock()

        resp = client.post(
            "/api/v1/datasets/upload",
            files={"file": ("ocean.nc", io.BytesIO(b"x"), "application/octet-stream")},
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 202
        job_id = resp.json()["job_id"]

        # Verify records exist in DB
        job = db_session.get(IngestionJob, uuid.UUID(job_id))
        assert job is not None
        assert job.status == "pending"
        assert job.original_filename == "ocean.nc"
        assert job.dataset_id is not None

    @patch("app.api.v1.ingestion.ingest_zip_task")
    def test_upload_zip_dispatches_zip_task(self, mock_task, client: TestClient, admin_token: str):
        """.zip upload dispatches ingest_zip_task."""
        mock_task.delay = MagicMock()

        resp = client.post(
            "/api/v1/datasets/upload",
            files={"file": ("archive.zip", io.BytesIO(b"PK"), "application/zip")},
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 202
        mock_task.delay.assert_called_once()

    def test_upload_rejects_bad_extension(self, client: TestClient, admin_token: str):
        """Non-.nc/.nc4/.zip files should be rejected with 400."""
        resp = client.post(
            "/api/v1/datasets/upload",
            files={"file": ("data.csv", io.BytesIO(b"x"), "text/csv")},
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 400
        assert "Unsupported file type" in resp.json()["detail"]

    def test_upload_requires_auth(self, client: TestClient):
        """Upload without token returns 401."""
        resp = client.post(
            "/api/v1/datasets/upload",
            files={"file": ("test.nc", io.BytesIO(b"x"), "application/octet-stream")},
        )
        assert resp.status_code == 401

    def test_upload_requires_admin(self, client: TestClient, user_token: str):
        """Upload with non-admin token returns 403."""
        resp = client.post(
            "/api/v1/datasets/upload",
            files={"file": ("test.nc", io.BytesIO(b"x"), "application/octet-stream")},
            headers=_auth_header(user_token),
        )
        assert resp.status_code == 403


# =========================================================================
# GET /api/v1/datasets/jobs/{job_id}
# =========================================================================
class TestGetJobStatus:

    def test_get_existing_job(self, client: TestClient, admin_token: str, db_session: Session):
        """Fetch an existing job should return its status."""
        job_id = _create_job(db_session, status="running", filename="a.nc")

        resp = client.get(
            f"/api/v1/datasets/jobs/{job_id}",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["job_id"] == job_id
        assert body["status"] == "running"
        assert body["original_filename"] == "a.nc"

    def test_get_nonexistent_job_404(self, client: TestClient, admin_token: str):
        """Non-existent job_id should return 404."""
        fake_id = str(uuid.uuid4())
        resp = client.get(
            f"/api/v1/datasets/jobs/{fake_id}",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 404

    def test_get_job_bad_uuid_400(self, client: TestClient, admin_token: str):
        """Invalid UUID format should return 400."""
        resp = client.get(
            "/api/v1/datasets/jobs/not-a-uuid",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 400


# =========================================================================
# GET /api/v1/datasets/jobs
# =========================================================================
class TestListJobs:

    def test_list_empty(self, client: TestClient, admin_token: str):
        """No jobs → empty list."""
        resp = client.get(
            "/api/v1/datasets/jobs",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 0
        assert body["jobs"] == []

    def test_list_returns_created_jobs(self, client: TestClient, admin_token: str, db_session: Session):
        """Created jobs should appear in listing."""
        _create_job(db_session, status="pending", filename="one.nc")
        _create_job(db_session, status="succeeded", filename="two.nc")

        resp = client.get(
            "/api/v1/datasets/jobs",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 2
        assert len(body["jobs"]) == 2

    def test_list_status_filter(self, client: TestClient, admin_token: str, db_session: Session):
        """status_filter should narrow results."""
        _create_job(db_session, status="pending", filename="p.nc")
        _create_job(db_session, status="failed", filename="f.nc")

        resp = client.get(
            "/api/v1/datasets/jobs?status_filter=failed",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["total"] == 1
        assert body["jobs"][0]["status"] == "failed"

    def test_list_pagination(self, client: TestClient, admin_token: str, db_session: Session):
        """limit & offset should paginate correctly."""
        for i in range(5):
            _create_job(db_session, filename=f"{i}.nc")

        resp = client.get(
            "/api/v1/datasets/jobs?limit=2&offset=0",
            headers=_auth_header(admin_token),
        )
        body = resp.json()
        assert len(body["jobs"]) == 2
        assert body["total"] == 5
        assert body["limit"] == 2
        assert body["offset"] == 0

    def test_list_invalid_status_filter_400(self, client: TestClient, admin_token: str):
        """Invalid status filter value returns 400."""
        resp = client.get(
            "/api/v1/datasets/jobs?status_filter=bogus",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 400


# =========================================================================
# POST /api/v1/datasets/jobs/{job_id}/retry
# =========================================================================
class TestRetryJob:

    @patch("app.api.v1.ingestion.ingest_file_task")
    def test_retry_failed_job(self, mock_task, client: TestClient, admin_token: str, db_session: Session):
        """Retrying a failed job should reset status to pending and dispatch task."""
        mock_task.delay = MagicMock()

        job_id = _create_job(db_session, status="failed", filename="retry.nc")

        resp = client.post(
            f"/api/v1/datasets/jobs/{job_id}/retry",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "pending"
        assert body["message"] == "Job retry initiated"

        # Verify DB was updated
        job = db_session.get(IngestionJob, uuid.UUID(job_id))
        assert job.status == "pending"
        assert job.progress_pct == 0

    def test_retry_non_failed_job_rejected(self, client: TestClient, admin_token: str, db_session: Session):
        """Retrying a non-failed job should return 400."""
        job_id = _create_job(db_session, status="running", filename="r.nc")

        resp = client.post(
            f"/api/v1/datasets/jobs/{job_id}/retry",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 400
        assert "Only failed jobs" in resp.json()["detail"]

    def test_retry_nonexistent_job_404(self, client: TestClient, admin_token: str):
        """Retrying a non-existent job returns 404."""
        resp = client.post(
            f"/api/v1/datasets/jobs/{uuid.uuid4()}/retry",
            headers=_auth_header(admin_token),
        )
        assert resp.status_code == 404
