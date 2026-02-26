"""
Unit tests for the data cleaner module.

Tests:
- Outlier detection flags values outside valid ranges
- Normal values are not flagged
- Invalid data_mode is handled (not tested here — cleaner doesn't handle data_mode)
- Outlier flag does not remove the measurement
- CleaningStats tracks counts correctly
"""

import pytest

from app.ingestion.cleaner import (
    CleanedMeasurement,
    CleaningResult,
    CleaningStats,
    clean_measurement,
    clean_measurements,
    clean_parse_result,
    validate_against_bounds,
)
from app.ingestion.parser import MeasurementRecord, ParseResult, FloatInfo, ProfileInfo


# =========================================================================
# Outlier detection tests
# =========================================================================
class TestOutlierDetection:
    """Tests for outlier flagging logic."""

    def test_temperature_outlier_high(self):
        """Temperature 45.0°C should be flagged as outlier."""
        record = MeasurementRecord(pressure=10.0, temperature=45.0, salinity=35.0)
        cleaned = clean_measurement(record)
        assert cleaned.temperature_flag is True
        assert cleaned.has_outlier is True

    def test_temperature_outlier_low(self):
        """Temperature -5.0°C should be flagged as outlier."""
        record = MeasurementRecord(pressure=10.0, temperature=-5.0, salinity=35.0)
        cleaned = clean_measurement(record)
        assert cleaned.temperature_flag is True

    def test_temperature_normal_not_flagged(self):
        """Temperature 20.0°C should NOT be flagged."""
        record = MeasurementRecord(pressure=10.0, temperature=20.0, salinity=35.0)
        cleaned = clean_measurement(record)
        assert cleaned.temperature_flag is False
        assert cleaned.has_outlier is False

    def test_temperature_boundary_low_valid(self):
        """Temperature -2.5°C (boundary) should NOT be flagged."""
        record = MeasurementRecord(pressure=10.0, temperature=-2.5, salinity=35.0)
        cleaned = clean_measurement(record)
        assert cleaned.temperature_flag is False

    def test_temperature_boundary_high_valid(self):
        """Temperature 40.0°C (boundary) should NOT be flagged."""
        record = MeasurementRecord(pressure=10.0, temperature=40.0, salinity=35.0)
        cleaned = clean_measurement(record)
        assert cleaned.temperature_flag is False

    def test_salinity_outlier_high(self):
        """Salinity 50.0 PSU should be flagged as outlier."""
        record = MeasurementRecord(pressure=10.0, temperature=20.0, salinity=50.0)
        cleaned = clean_measurement(record)
        assert cleaned.salinity_flag is True

    def test_salinity_outlier_negative(self):
        """Salinity -1.0 PSU should be flagged as outlier."""
        record = MeasurementRecord(pressure=10.0, temperature=20.0, salinity=-1.0)
        cleaned = clean_measurement(record)
        assert cleaned.salinity_flag is True

    def test_salinity_normal(self):
        """Salinity 35.0 PSU should NOT be flagged."""
        record = MeasurementRecord(pressure=10.0, temperature=20.0, salinity=35.0)
        cleaned = clean_measurement(record)
        assert cleaned.salinity_flag is False

    def test_pressure_outlier(self):
        """Pressure 15000 dbar should be flagged as outlier."""
        record = MeasurementRecord(pressure=15000.0, temperature=20.0, salinity=35.0)
        cleaned = clean_measurement(record)
        assert cleaned.pressure_flag is True

    def test_oxygen_outlier(self):
        """Dissolved oxygen 700 µmol/kg should be flagged."""
        record = MeasurementRecord(pressure=10.0, temperature=20.0, salinity=35.0, oxygen=700.0)
        cleaned = clean_measurement(record)
        assert cleaned.oxygen_flag is True

    def test_none_values_not_flagged(self):
        """None values should NOT be flagged as outliers."""
        record = MeasurementRecord(pressure=10.0, temperature=None, salinity=None)
        cleaned = clean_measurement(record)
        assert cleaned.temperature_flag is False
        assert cleaned.salinity_flag is False
        assert cleaned.has_outlier is False


# =========================================================================
# Data preservation tests
# =========================================================================
class TestDataPreservation:
    """Verify outlier flagging does not remove data."""

    def test_outlier_value_preserved(self):
        """Outlier values should be preserved (not set to None)."""
        record = MeasurementRecord(pressure=10.0, temperature=45.0, salinity=35.0)
        cleaned = clean_measurement(record)
        assert cleaned.temperature == 45.0
        assert cleaned.salinity == 35.0
        assert cleaned.pressure == 10.0

    def test_all_values_preserved_after_cleaning(self):
        """All original values should be present in cleaned output."""
        record = MeasurementRecord(
            pressure=100.0,
            temperature=15.0,
            salinity=35.5,
            oxygen=250.0,
            chlorophyll_a=0.5,
            nitrate=10.0,
            ph=8.1,
        )
        cleaned = clean_measurement(record)
        assert cleaned.pressure == 100.0
        assert cleaned.temperature == 15.0
        assert cleaned.salinity == 35.5
        assert cleaned.oxygen == 250.0
        assert cleaned.chlorophyll_a == 0.5
        assert cleaned.nitrate == 10.0
        assert cleaned.ph == 8.1


# =========================================================================
# clean_measurements (batch) tests
# =========================================================================
class TestCleanMeasurements:
    """Tests for batch cleaning."""

    def test_empty_list_returns_success(self):
        """Empty measurement list should return success with empty results."""
        result = clean_measurements([])
        assert result.success is True
        assert len(result.measurements) == 0
        assert result.stats.total_records == 0

    def test_stats_count_correct(self):
        """Stats should correctly count total and flagged records."""
        records = [
            MeasurementRecord(pressure=10.0, temperature=20.0, salinity=35.0),  # normal
            MeasurementRecord(pressure=10.0, temperature=45.0, salinity=35.0),  # outlier
            MeasurementRecord(pressure=10.0, temperature=15.0, salinity=35.0),  # normal
        ]
        result = clean_measurements(records)
        assert result.stats.total_records == 3
        assert result.stats.flagged_records == 1
        assert result.stats.flags_by_variable["temperature"] == 1

    def test_multiple_outliers_counted(self):
        """Multiple outlier types in one record should all be counted."""
        records = [
            MeasurementRecord(pressure=10.0, temperature=45.0, salinity=50.0),  # both outliers
        ]
        result = clean_measurements(records)
        assert result.stats.flagged_records == 1
        assert result.stats.flags_by_variable["temperature"] == 1
        assert result.stats.flags_by_variable["salinity"] == 1

    def test_all_records_preserved(self):
        """All records should be in output, including outliers."""
        records = [
            MeasurementRecord(pressure=10.0, temperature=20.0, salinity=35.0),
            MeasurementRecord(pressure=10.0, temperature=45.0, salinity=35.0),
        ]
        result = clean_measurements(records)
        assert len(result.measurements) == 2


# =========================================================================
# clean_parse_result tests
# =========================================================================
class TestCleanParseResult:
    """Tests for the clean_parse_result convenience function."""

    def test_failed_parse_returns_failure(self):
        """Cleaning a failed ParseResult should return failure."""
        parse_result = ParseResult(success=False, error_message="test error")
        result = clean_parse_result(parse_result)
        assert result.success is False

    def test_successful_parse_returns_cleaned(self):
        """Cleaning a successful ParseResult should return cleaned measurements."""
        from datetime import datetime, timezone

        parse_result = ParseResult(
            success=True,
            float_info=FloatInfo(wmo_id="1234567", float_type="core"),
            profile_info=ProfileInfo(
                cycle_number=1,
                direction="A",
                latitude=35.0,
                longitude=-20.0,
                timestamp=datetime.now(timezone.utc),
                n_levels=2,
            ),
            measurements=[
                MeasurementRecord(pressure=10.0, temperature=20.0, salinity=35.0),
                MeasurementRecord(pressure=50.0, temperature=15.0, salinity=35.5),
            ],
        )
        result = clean_parse_result(parse_result)
        assert result.success is True
        assert len(result.measurements) == 2


# =========================================================================
# validate_against_bounds tests
# =========================================================================
class TestValidateAgainstBounds:
    """Tests for the validate_against_bounds utility."""

    def test_valid_temperature(self):
        is_valid, msg = validate_against_bounds(20.0, "temperature")
        assert is_valid is True
        assert msg is None

    def test_invalid_temperature_high(self):
        is_valid, msg = validate_against_bounds(45.0, "temperature")
        assert is_valid is False
        assert "above maximum" in msg

    def test_invalid_temperature_low(self):
        is_valid, msg = validate_against_bounds(-5.0, "temperature")
        assert is_valid is False
        assert "below minimum" in msg

    def test_unknown_variable_always_valid(self):
        is_valid, msg = validate_against_bounds(999.0, "unknown_var")
        assert is_valid is True
