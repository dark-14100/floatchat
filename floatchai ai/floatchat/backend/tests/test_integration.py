"""
Full pipeline integration tests.

Tests the end-to-end data flow:
   NetCDF file → parser → cleaner → (writer mocked for SQLite)
   
Since writer.py requires PostgreSQL + PostGIS (upsert, geography),
we test the parse→clean chain with real fixture files and verify
the writer's orchestration logic with mocks.

PRD §9.2 coverage:
- test_full_ingestion_single_file()
- test_upsert_on_duplicate()
- test_job_status_transitions()
- test_retry_failed_job()
- test_malformed_file_fails_gracefully()
"""

import uuid
from datetime import datetime, timezone
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest
from sqlalchemy.orm import Session

from app.db.models import Dataset, Float, IngestionJob, Measurement, Profile
from app.ingestion.cleaner import clean_parse_result, clean_measurements
from app.ingestion.parser import parse_netcdf_file, parse_netcdf_all_profiles


FIXTURES_DIR = Path(__file__).parent / "fixtures"
CORE_FILE = str(FIXTURES_DIR / "core_single_profile.nc")
BGC_FILE = str(FIXTURES_DIR / "bgc_multi_profile.nc")
MALFORMED_FILE = str(FIXTURES_DIR / "malformed_missing_psal.nc")


# =========================================================================
# Full pipeline: parse → clean → verify
# =========================================================================
class TestFullIngestionSingleFile:
    """
    PRD §9.2: test_full_ingestion_single_file()
    Upload a real ARGO .nc file, assert all rows/structures created.
    (DB writes are simulated since SQLite lacks PostGIS.)
    """

    def test_parse_clean_core_file(self):
        """Parse + clean the core single-profile fixture end-to-end."""
        result = parse_netcdf_file(CORE_FILE)
        assert result.success is True
        assert result.float_info is not None
        assert result.float_info.wmo_id == "1901234"
        assert result.profile_info is not None
        assert len(result.measurements) > 0

        cleaned = clean_parse_result(result)
        assert cleaned.success is True
        assert cleaned.stats.total_records == len(result.measurements)

    def test_parse_clean_bgc_file(self):
        """Parse + clean the multi-profile BGC fixture end-to-end."""
        results = parse_netcdf_all_profiles(BGC_FILE)
        assert len(results) == 3  # 3 profiles in fixture

        for res in results:
            assert res.success is True
            cleaned = clean_parse_result(res)
            assert cleaned.success is True

    def test_bgc_outlier_detected(self):
        """The BGC fixture has a 45.0°C temp outlier — should be flagged."""
        results = parse_netcdf_all_profiles(BGC_FILE)
        # Profile index 2 has the outlier (temp=45.0)
        outlier_profile = results[2]
        cleaned = clean_parse_result(outlier_profile)
        assert cleaned.stats.flagged_records >= 1
        assert cleaned.stats.flags_by_variable["temperature"] >= 1

    @patch("app.ingestion.writer.upsert_float_position", return_value=1)
    @patch("app.ingestion.writer.write_measurements", return_value=10)
    @patch("app.ingestion.writer.upsert_profile", return_value=1)
    @patch("app.ingestion.writer.upsert_float", return_value=1)
    def test_write_parse_result_called_correctly(
        self, mock_float, mock_profile, mock_meas, mock_pos
    ):
        """write_parse_result calls all 4 sub-writers for a valid result."""
        from app.ingestion.writer import write_parse_result

        result = parse_netcdf_file(CORE_FILE)
        cleaned = clean_parse_result(result)
        db = MagicMock()

        outcome = write_parse_result(db, result, cleaned, dataset_id=1)
        assert outcome["success"] is True
        mock_float.assert_called_once()
        mock_profile.assert_called_once()
        mock_meas.assert_called_once()
        mock_pos.assert_called_once()


# =========================================================================
# Idempotency: same file twice → no duplicates
# =========================================================================
class TestUpsertOnDuplicate:
    """
    PRD §9.2: test_upsert_on_duplicate()
    Ingest same file twice, assert no duplicate rows.
    
    Since we can't run real PostgreSQL upserts in SQLite, we verify:
    1. Float upsert uses ON CONFLICT DO NOTHING  (tested in unit tests)
    2. Profile upsert uses ON CONFLICT DO UPDATE (tested in unit tests)
    3. Measurements do DELETE + INSERT (tested in unit tests)
    4. Here we verify the full parse→clean→write is deterministic:
       same input produces same output.
    """

    def test_parse_same_file_twice_identical(self):
        """Parsing the same file twice produces identical results."""
        r1 = parse_netcdf_file(CORE_FILE)
        r2 = parse_netcdf_file(CORE_FILE)

        assert r1.success is True and r2.success is True
        assert r1.file_hash == r2.file_hash
        assert r1.float_info.wmo_id == r2.float_info.wmo_id
        assert r1.profile_info.cycle_number == r2.profile_info.cycle_number
        assert len(r1.measurements) == len(r2.measurements)

    def test_clean_same_data_deterministic(self):
        """Cleaning the same parse result twice gives identical stats."""
        result = parse_netcdf_file(CORE_FILE)
        c1 = clean_parse_result(result)
        c2 = clean_parse_result(result)

        assert c1.stats.total_records == c2.stats.total_records
        assert c1.stats.flagged_records == c2.stats.flagged_records

    @patch("app.ingestion.writer.upsert_float_position")
    @patch("app.ingestion.writer.write_measurements")
    @patch("app.ingestion.writer.upsert_profile")
    @patch("app.ingestion.writer.upsert_float")
    def test_write_called_with_same_args_twice(
        self, mock_float, mock_profile, mock_meas, mock_pos
    ):
        """Two writes for the same parse result use identical arguments."""
        from app.ingestion.writer import write_parse_result

        mock_float.return_value = 1
        mock_profile.return_value = 1
        mock_meas.return_value = 10
        mock_pos.return_value = 1

        result = parse_netcdf_file(CORE_FILE)
        cleaned = clean_parse_result(result)
        db = MagicMock()

        write_parse_result(db, result, cleaned, dataset_id=1)
        write_parse_result(db, result, cleaned, dataset_id=1)

        assert mock_float.call_count == 2
        # Both calls should use the same platform_number
        assert (
            mock_float.call_args_list[0].kwargs["platform_number"]
            == mock_float.call_args_list[1].kwargs["platform_number"]
        )


# =========================================================================
# Job status transitions
# =========================================================================
class TestJobStatusTransitions:
    """
    PRD §9.2: test_job_status_transitions()
    Assert job moves through pending → running → succeeded.
    """

    def test_pending_to_running_to_succeeded(self, db_session: Session):
        """Manually transition a job through all states."""
        ds = Dataset(
            name="transit.nc", source_filename="transit.nc",
            is_active=True, dataset_version=1,
        )
        db_session.add(ds)
        db_session.flush()

        job = IngestionJob(
            dataset_id=ds.dataset_id,
            original_filename="transit.nc",
            status="pending",
            progress_pct=0,
            profiles_ingested=0,
        )
        db_session.add(job)
        db_session.flush()
        job_id = job.job_id

        # Pending → Running
        job.status = "running"
        job.started_at = datetime.now(timezone.utc)
        db_session.flush()
        assert job.status == "running"
        assert job.started_at is not None

        # Running → Succeeded
        job.status = "succeeded"
        job.progress_pct = 100
        job.completed_at = datetime.now(timezone.utc)
        db_session.flush()
        assert job.status == "succeeded"
        assert job.completed_at is not None

    def test_pending_to_failed(self, db_session: Session):
        """Job can transition from pending directly to failed."""
        ds = Dataset(
            name="fail.nc", source_filename="fail.nc",
            is_active=True, dataset_version=1,
        )
        db_session.add(ds)
        db_session.flush()

        job = IngestionJob(
            dataset_id=ds.dataset_id,
            original_filename="fail.nc",
            status="pending",
            progress_pct=0,
            profiles_ingested=0,
        )
        db_session.add(job)
        db_session.flush()

        job.status = "failed"
        job.error_log = "S3 upload failed"
        job.completed_at = datetime.now(timezone.utc)
        db_session.flush()

        assert job.status == "failed"
        assert job.error_log == "S3 upload failed"


# =========================================================================
# Retry failed job
# =========================================================================
class TestRetryFailedJob:
    """
    PRD §9.2: test_retry_failed_job()
    Simulate failure, then assert retry resets status and re-runs.
    """

    @patch("app.api.v1.ingestion.ingest_file_task")
    def test_retry_via_api(self, mock_task, client, admin_token, db_session: Session):
        """Full API flow: create failed job → POST retry → verify reset."""
        mock_task.delay = MagicMock()

        # Create a failed job
        ds = Dataset(
            name="retry.nc", source_filename="retry.nc",
            is_active=True, dataset_version=1,
        )
        db_session.add(ds)
        db_session.flush()

        job = IngestionJob(
            dataset_id=ds.dataset_id,
            original_filename="retry.nc",
            raw_file_path="/tmp/retry.nc",
            status="failed",
            progress_pct=50,
            profiles_ingested=3,
            error_log="Connection lost",
        )
        db_session.add(job)
        db_session.flush()
        db_session.commit()
        job_id = str(job.job_id)

        # Retry via API
        resp = client.post(
            f"/api/v1/datasets/jobs/{job_id}/retry",
            headers={"Authorization": f"Bearer {admin_token}"},
        )
        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "pending"

        # Verify DB was reset
        refreshed = db_session.get(IngestionJob, job.job_id)
        assert refreshed.status == "pending"
        assert refreshed.progress_pct == 0
        assert refreshed.profiles_ingested == 0
        assert refreshed.error_log is None
        assert refreshed.started_at is None
        assert refreshed.completed_at is None

        # Celery task was dispatched
        mock_task.delay.assert_called_once()


# =========================================================================
# Malformed file handling
# =========================================================================
class TestMalformedFileHandling:

    def test_malformed_file_fails_gracefully(self):
        """Missing PSAL should still parse (salinity=None), not crash."""
        result = parse_netcdf_file(MALFORMED_FILE)
        # Parser may succeed (PSAL is optional in parser) or fail validation
        # Either way it should not raise an exception
        if result.success:
            # If it parsed, salinity should be None for all measurements
            for m in result.measurements:
                assert m.salinity is None

    def test_nonexistent_file_graceful_error(self):
        """Parsing a non-existent path returns error, doesn't crash."""
        result = parse_netcdf_file("/nonexistent/path/file.nc")
        assert result.success is False
        assert result.error_message is not None


# =========================================================================
# Multi-profile pipeline
# =========================================================================
class TestMultiProfilePipeline:

    def test_all_profiles_parsed_and_cleaned(self):
        """All 3 BGC profiles should parse and clean successfully."""
        results = parse_netcdf_all_profiles(BGC_FILE)
        assert len(results) == 3

        total_measurements = 0
        total_flagged = 0
        for res in results:
            assert res.success is True
            cleaned = clean_parse_result(res)
            assert cleaned.success is True
            total_measurements += cleaned.stats.total_records
            total_flagged += cleaned.stats.flagged_records

        assert total_measurements > 0
        # At least one outlier from the temp=45.0 in fixture
        assert total_flagged >= 1

    def test_profiles_have_different_cycles(self):
        """Each profile in a multi-profile file has a unique cycle number."""
        results = parse_netcdf_all_profiles(BGC_FILE)
        cycles = [r.profile_info.cycle_number for r in results]
        assert len(set(cycles)) == len(cycles)  # all unique

    def test_file_hash_consistent(self):
        """All profiles from the same file should share the same file_hash."""
        results = parse_netcdf_all_profiles(BGC_FILE)
        hashes = {r.file_hash for r in results}
        assert len(hashes) == 1
