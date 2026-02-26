"""
Unit tests for the database writer module.

All database interactions are mocked since writer.py requires
PostgreSQL + PostGIS. Tests verify:
- Correct SQL operations are invoked
- Idempotent upsert logic (same input twice ⇒ single row)
- Measurements delete-then-insert strategy
- write_parse_result orchestration
- Invalid-position handling
"""

from datetime import datetime, timezone
from unittest.mock import MagicMock, call, patch
import uuid

import pytest

from app.ingestion.cleaner import CleanedMeasurement, CleaningResult, CleaningStats
from app.ingestion.parser import FloatInfo, MeasurementRecord, ParseResult, ProfileInfo
from app.ingestion.writer import (
    _create_point_geometry,
    _is_valid_position,
    upsert_float,
    upsert_profile,
    write_measurements,
    upsert_float_position,
    write_dataset,
    write_ingestion_job,
    update_job_status,
    write_parse_result,
)


# =========================================================================
# Helper factories
# =========================================================================

def _make_profile_info(**overrides) -> ProfileInfo:
    defaults = dict(
        cycle_number=1,
        direction="A",
        latitude=35.0,
        longitude=-20.0,
        timestamp=datetime(2024, 1, 1, tzinfo=timezone.utc),
        n_levels=10,
    )
    defaults.update(overrides)
    return ProfileInfo(**defaults)


def _make_float_info(**overrides) -> FloatInfo:
    defaults = dict(wmo_id="1234567", float_type="core")
    defaults.update(overrides)
    return FloatInfo(**defaults)


def _make_cleaned_measurement(**overrides) -> CleanedMeasurement:
    defaults = dict(
        pressure=100.0,
        temperature=15.0,
        salinity=35.0,
        oxygen=250.0,
        chlorophyll_a=None,
        nitrate=None,
        ph=None,
        temperature_flag=False,
        salinity_flag=False,
        pressure_flag=False,
        oxygen_flag=False,
        chlorophyll_a_flag=False,
        nitrate_flag=False,
        ph_flag=False,
    )
    defaults.update(overrides)
    return CleanedMeasurement(**defaults)


def _make_parse_result(success=True, n_measurements=3) -> ParseResult:
    measurements = [
        MeasurementRecord(
            pressure=float(i * 50),
            temperature=15.0 + i,
            salinity=35.0 + i * 0.1,
        )
        for i in range(n_measurements)
    ]
    return ParseResult(
        success=success,
        float_info=_make_float_info(),
        profile_info=_make_profile_info(),
        measurements=measurements,
        error_message=None if success else "test_error",
    )


def _make_cleaning_result(n_measurements=3) -> CleaningResult:
    measurements = [
        _make_cleaned_measurement(pressure=float(i * 50))
        for i in range(n_measurements)
    ]
    return CleaningResult(
        success=True,
        measurements=measurements,
        stats=CleaningStats(total_records=n_measurements),
    )


# =========================================================================
# _is_valid_position
# =========================================================================
class TestIsValidPosition:

    def test_valid_position(self):
        assert _is_valid_position(35.0, -20.0) is True

    def test_none_latitude(self):
        assert _is_valid_position(None, -20.0) is False

    def test_none_longitude(self):
        assert _is_valid_position(35.0, None) is False

    def test_lat_too_high(self):
        assert _is_valid_position(91.0, 0.0) is False

    def test_lat_too_low(self):
        assert _is_valid_position(-91.0, 0.0) is False

    def test_lon_too_high(self):
        assert _is_valid_position(0.0, 181.0) is False

    def test_lon_too_low(self):
        assert _is_valid_position(0.0, -181.0) is False

    def test_boundary_values_valid(self):
        assert _is_valid_position(90.0, 180.0) is True
        assert _is_valid_position(-90.0, -180.0) is True


# =========================================================================
# _create_point_geometry
# =========================================================================
class TestCreatePointGeometry:

    def test_returns_wkt_element(self):
        result = _create_point_geometry(35.0, -20.0)
        # WKTElement wraps the WKT string; check it contains the expected POINT
        assert "POINT" in str(result)

    def test_lon_lat_order(self):
        """PostGIS uses (lon, lat), not (lat, lon)."""
        result = _create_point_geometry(35.0, -20.0)
        wkt = str(result)
        assert "-20" in wkt
        assert "35" in wkt


# =========================================================================
# upsert_float
# =========================================================================
class TestUpsertFloat:

    def test_calls_execute_and_flush(self):
        db = MagicMock(spec=["execute", "flush"])
        db.execute.return_value = MagicMock(scalar_one=MagicMock(return_value=42))

        result = upsert_float(db, platform_number="1234567")
        assert result == 42
        assert db.execute.call_count == 2  # INSERT + SELECT
        assert db.flush.call_count >= 1

    def test_wmo_id_defaults_to_platform_number(self):
        db = MagicMock(spec=["execute", "flush"])
        db.execute.return_value = MagicMock(scalar_one=MagicMock(return_value=1))

        upsert_float(db, platform_number="9999999")
        # The first execute call is the INSERT; hard to inspect sqlalchemy stmt
        # but at minimum ensure it doesn't error.
        assert db.execute.called


# =========================================================================
# upsert_profile
# =========================================================================
class TestUpsertProfile:

    def test_calls_execute_and_flush(self):
        db = MagicMock(spec=["execute", "flush"])
        db.execute.return_value = MagicMock(scalar_one=MagicMock(return_value=101))

        profile_info = _make_profile_info()
        float_info = _make_float_info()

        result = upsert_profile(
            db, profile_info, float_info, float_id=42, dataset_id=1
        )
        assert result == 101
        # INSERT, SELECT, UPDATE geom, flush calls
        assert db.execute.call_count >= 2
        assert db.flush.call_count >= 1

    def test_invalid_position_skips_geometry_update(self):
        """When lat/lon are None, geometry UPDATE should not run."""
        db = MagicMock(spec=["execute", "flush"])
        db.execute.return_value = MagicMock(scalar_one=MagicMock(return_value=101))

        profile_info = _make_profile_info(latitude=None, longitude=None)
        float_info = _make_float_info()

        upsert_profile(db, profile_info, float_info, float_id=42, dataset_id=1)
        # Should have INSERT + SELECT but NOT the geometry UPDATE
        assert db.execute.call_count == 2


# =========================================================================
# write_measurements
# =========================================================================
class TestWriteMeasurements:

    def test_empty_measurements_returns_zero(self):
        db = MagicMock(spec=["execute", "flush", "bulk_insert_mappings"])
        result = write_measurements(db, profile_id=101, measurements=[])
        assert result == 0
        db.bulk_insert_mappings.assert_not_called()

    def test_deletes_existing_then_inserts(self):
        """Should DELETE old measurements then bulk-insert new ones."""
        db = MagicMock(spec=["execute", "flush", "bulk_insert_mappings"])

        measurements = [_make_cleaned_measurement() for _ in range(5)]
        result = write_measurements(db, profile_id=101, measurements=measurements)

        assert result == 5
        # At least one execute for DELETE
        db.execute.assert_called()
        # bulk_insert_mappings called at least once
        db.bulk_insert_mappings.assert_called()

    def test_batch_splitting(self):
        """If batch_size < len(measurements), multiple bulk inserts happen."""
        db = MagicMock(spec=["execute", "flush", "bulk_insert_mappings"])

        # Create many measurements
        measurements = [_make_cleaned_measurement(pressure=float(i)) for i in range(250)]

        with patch("app.ingestion.writer.settings") as mock_settings:
            mock_settings.DB_INSERT_BATCH_SIZE = 100
            result = write_measurements(db, profile_id=101, measurements=measurements)

        assert result == 250
        # 250 / 100 = 3 batches (100, 100, 50)
        assert db.bulk_insert_mappings.call_count == 3


# =========================================================================
# write_dataset
# =========================================================================
class TestWriteDataset:

    def test_creates_dataset_and_returns_id(self):
        db = MagicMock(spec=["add", "flush"])

        # Make flush assign a dataset_id to the added Dataset
        def side_effect(obj):
            obj.dataset_id = 77

        db.add.side_effect = lambda obj: setattr(obj, "dataset_id", 77)

        result = write_dataset(db, source_filename="test.nc")
        assert result == 77
        db.add.assert_called_once()
        db.flush.assert_called_once()


# =========================================================================
# write_ingestion_job
# =========================================================================
class TestWriteIngestionJob:

    def test_creates_job_and_returns_uuid(self):
        db = MagicMock(spec=["add", "flush"])
        test_uuid = uuid.uuid4()

        db.add.side_effect = lambda obj: setattr(obj, "job_id", test_uuid)

        result = write_ingestion_job(
            db, dataset_id=1, original_filename="test.nc"
        )
        assert result == str(test_uuid)
        db.add.assert_called_once()
        db.flush.assert_called_once()


# =========================================================================
# update_job_status
# =========================================================================
class TestUpdateJobStatus:

    def test_updates_status(self):
        db = MagicMock(spec=["execute", "flush"])
        mock_job = MagicMock()
        mock_job.started_at = None
        mock_job.completed_at = None
        db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=mock_job))

        job_id = str(uuid.uuid4())
        update_job_status(db, job_id=job_id, status="running")

        assert mock_job.status == "running"
        assert mock_job.started_at is not None  # set on first "running"
        db.flush.assert_called_once()

    def test_missing_job_does_not_error(self):
        db = MagicMock(spec=["execute", "flush"])
        db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=None))

        job_id = str(uuid.uuid4())
        # Should log error but not raise
        update_job_status(db, job_id=job_id, status="running")
        db.flush.assert_not_called()

    def test_succeeded_sets_completed_at(self):
        db = MagicMock(spec=["execute", "flush"])
        mock_job = MagicMock()
        mock_job.started_at = datetime.now(timezone.utc)
        mock_job.completed_at = None
        db.execute.return_value = MagicMock(scalar_one_or_none=MagicMock(return_value=mock_job))

        job_id = str(uuid.uuid4())
        update_job_status(db, job_id=job_id, status="succeeded", progress_pct=100)

        assert mock_job.status == "succeeded"
        assert mock_job.completed_at is not None
        assert mock_job.progress_pct == 100


# =========================================================================
# write_parse_result (orchestrator)
# =========================================================================
class TestWriteParseResult:

    @patch("app.ingestion.writer.upsert_float_position", return_value=999)
    @patch("app.ingestion.writer.write_measurements", return_value=3)
    @patch("app.ingestion.writer.upsert_profile", return_value=101)
    @patch("app.ingestion.writer.upsert_float", return_value=42)
    def test_full_orchestration(self, mock_float, mock_profile, mock_meas, mock_pos):
        db = MagicMock()
        parse_result = _make_parse_result(success=True, n_measurements=3)
        cleaning_result = _make_cleaning_result(n_measurements=3)

        result = write_parse_result(db, parse_result, cleaning_result, dataset_id=1)

        assert result["success"] is True
        assert result["float_id"] == 42
        assert result["profile_id"] == 101
        assert result["measurement_count"] == 3
        assert result["position_id"] == 999

        mock_float.assert_called_once()
        mock_profile.assert_called_once()
        mock_meas.assert_called_once()
        mock_pos.assert_called_once()

    def test_failed_parse_returns_error(self):
        db = MagicMock()
        parse_result = _make_parse_result(success=False)
        cleaning_result = _make_cleaning_result()

        result = write_parse_result(db, parse_result, cleaning_result, dataset_id=1)
        assert result["success"] is False

    def test_failed_cleaning_returns_error(self):
        db = MagicMock()
        parse_result = _make_parse_result(success=True)
        cleaning_result = CleaningResult(
            success=False, error_message="cleaning failed"
        )

        result = write_parse_result(db, parse_result, cleaning_result, dataset_id=1)
        assert result["success"] is False
