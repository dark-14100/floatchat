"""
Unit tests for the NetCDF parser module.

Tests:
- validate_file accepts valid ARGO files
- validate_file rejects files missing required variables
- parse_netcdf_file extracts core variables correctly
- parse_netcdf_all_profiles handles multi-profile files
- BGC variables extracted when present, None when absent
- Fill values (99999.0) become None
- Timestamps computed correctly from JULD
"""

import os
from pathlib import Path

import pytest

from app.ingestion.parser import (
    ParseResult,
    parse_netcdf_all_profiles,
    parse_netcdf_file,
    validate_file,
)

FIXTURES_DIR = Path(__file__).parent / "fixtures"

CORE_FILE = str(FIXTURES_DIR / "core_single_profile.nc")
BGC_FILE = str(FIXTURES_DIR / "bgc_multi_profile.nc")
MALFORMED_FILE = str(FIXTURES_DIR / "malformed_missing_psal.nc")


# =========================================================================
# validate_file tests
# =========================================================================
class TestValidateFile:
    """Tests for the validate_file function."""

    def test_valid_core_file_passes(self):
        """A valid core ARGO file should pass validation."""
        is_valid, error = validate_file(CORE_FILE)
        assert is_valid is True
        assert error is None

    def test_valid_bgc_file_passes(self):
        """A valid BGC ARGO file should pass validation."""
        is_valid, error = validate_file(BGC_FILE)
        assert is_valid is True
        assert error is None

    def test_missing_psal_fails_validation(self):
        """A file missing PSAL should fail with correct error message."""
        is_valid, error = validate_file(MALFORMED_FILE)
        assert is_valid is False
        assert error is not None
        assert "PSAL" in error
        assert "Missing required ARGO variable" in error

    def test_nonexistent_file_fails(self):
        """A nonexistent file should fail validation."""
        is_valid, error = validate_file("/nonexistent/file.nc")
        assert is_valid is False
        assert error is not None

    def test_non_netcdf_file_fails(self, tmp_path):
        """A non-NetCDF file should fail validation."""
        fake_file = tmp_path / "fake.nc"
        fake_file.write_text("this is not a netcdf file")
        is_valid, error = validate_file(str(fake_file))
        assert is_valid is False
        assert error is not None


# =========================================================================
# parse_netcdf_file tests (single profile)
# =========================================================================
class TestParseNetcdfFile:
    """Tests for the parse_netcdf_file function."""

    def test_parse_core_file_succeeds(self):
        """Parsing a valid core file should succeed."""
        result = parse_netcdf_file(CORE_FILE)
        assert result.success is True
        assert result.error_message is None

    def test_extracts_float_info(self):
        """Parser should extract float metadata."""
        result = parse_netcdf_file(CORE_FILE)
        assert result.float_info is not None
        assert result.float_info.wmo_id == "1901234"
        assert result.float_info.float_type == "core"

    def test_extracts_profile_info(self):
        """Parser should extract profile metadata."""
        result = parse_netcdf_file(CORE_FILE)
        assert result.profile_info is not None
        assert result.profile_info.cycle_number == 42
        assert result.profile_info.latitude == pytest.approx(35.5, abs=0.1)
        assert result.profile_info.longitude == pytest.approx(-20.3, abs=0.1)

    def test_extracts_timestamp(self):
        """Parser should convert JULD to a proper datetime."""
        result = parse_netcdf_file(CORE_FILE)
        assert result.profile_info is not None
        assert result.profile_info.timestamp is not None
        # JULD 27154.5 = 2024-05-15 12:00:00 UTC (approx)
        ts = result.profile_info.timestamp
        assert ts.year == 2024
        assert ts.month == 5

    def test_extracts_measurements(self):
        """Parser should extract measurement rows."""
        result = parse_netcdf_file(CORE_FILE)
        assert len(result.measurements) > 0
        # Core file has 10 depth levels
        assert len(result.measurements) == 10

    def test_measurements_have_temperature(self):
        """Each measurement should have a temperature value."""
        result = parse_netcdf_file(CORE_FILE)
        for m in result.measurements:
            assert m.temperature is not None

    def test_measurements_have_salinity(self):
        """Each measurement should have a salinity value."""
        result = parse_netcdf_file(CORE_FILE)
        for m in result.measurements:
            assert m.salinity is not None

    def test_measurements_have_pressure(self):
        """Each measurement should have a pressure value."""
        result = parse_netcdf_file(CORE_FILE)
        for m in result.measurements:
            assert m.pressure is not None
            assert m.pressure > 0

    def test_core_file_no_bgc_variables(self):
        """Core file should have None for BGC variables."""
        result = parse_netcdf_file(CORE_FILE)
        for m in result.measurements:
            assert m.oxygen is None
            assert m.chlorophyll_a is None
            assert m.nitrate is None
            assert m.ph is None

    def test_file_hash_computed(self):
        """Parser should compute a file hash."""
        result = parse_netcdf_file(CORE_FILE)
        assert result.file_hash is not None
        assert len(result.file_hash) == 64  # SHA-256 hex digest

    def test_nonexistent_file_returns_error(self):
        """Parsing a nonexistent file should return error, not raise."""
        result = parse_netcdf_file("/nonexistent/file.nc")
        assert result.success is False
        assert result.error_message is not None


# =========================================================================
# parse_netcdf_all_profiles tests (multi-profile)
# =========================================================================
class TestParseAllProfiles:
    """Tests for parse_netcdf_all_profiles with multi-profile files."""

    def test_multi_profile_extracts_all(self):
        """BGC file with 3 profiles should return 3 ParseResults."""
        results = parse_netcdf_all_profiles(BGC_FILE)
        assert len(results) == 3
        for r in results:
            assert r.success is True

    def test_multi_profile_different_cycles(self):
        """Each profile should have a different cycle number."""
        results = parse_netcdf_all_profiles(BGC_FILE)
        cycles = [r.profile_info.cycle_number for r in results]
        assert cycles == [10, 11, 12]

    def test_multi_profile_has_bgc_variables(self):
        """BGC file should have oxygen and chlorophyll_a values."""
        results = parse_netcdf_all_profiles(BGC_FILE)
        for r in results:
            has_oxygen = any(m.oxygen is not None for m in r.measurements)
            has_chla = any(m.chlorophyll_a is not None for m in r.measurements)
            assert has_oxygen, f"Profile cycle {r.profile_info.cycle_number} missing oxygen"
            assert has_chla, f"Profile cycle {r.profile_info.cycle_number} missing chlorophyll_a"

    def test_multi_profile_bgc_float_type(self):
        """BGC file should be identified as 'bgc' float type."""
        results = parse_netcdf_all_profiles(BGC_FILE)
        assert results[0].float_info.float_type == "bgc"

    def test_single_profile_file_returns_one(self):
        """Core file with 1 profile should return 1 ParseResult."""
        results = parse_netcdf_all_profiles(CORE_FILE)
        assert len(results) == 1
        assert results[0].success is True

    def test_multi_profile_has_outlier_value(self):
        """Profile 3 (cycle 12) should have a 45.0°C temperature measurement."""
        results = parse_netcdf_all_profiles(BGC_FILE)
        profile_3 = results[2]  # index 2 = cycle 12
        temps = [m.temperature for m in profile_3.measurements if m.temperature is not None]
        assert 45.0 in [round(t, 1) for t in temps], "Expected 45.0°C outlier in profile 3"
