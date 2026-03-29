"""
Feature 2 — Data Access Layer (DAL) tests.

Verifies that all DAL functions return correct results against a
PostgreSQL+PostGIS database with representative test data.

Requires:
    - Docker PostgreSQL+PostGIS running on port 5432
    - ``alembic upgrade head`` completed
"""

from datetime import datetime, timezone

import pytest
from sqlalchemy import text

from app.db import dal


# ============================================================================
# get_profiles_by_radius
# ============================================================================
class TestGetProfilesByRadius:
    """Spatial proximity queries using PostGIS ST_DWithin."""

    def test_returns_profiles_within_radius(self, pg_session, seed_test_data):
        """Profile at (10, 72) should be found within 10 km of that point."""
        result = dal.get_profiles_by_radius(
            10.0, 72.0, 10_000,  # 10 km radius
            start_date=None,
            end_date=None,
            db=pg_session,
        )
        platforms = {r["platform_number"] for r in result}
        assert "FCTEST001" in platforms

    def test_excludes_profiles_outside_radius(self, pg_session, seed_test_data):
        """Atlantic profile at (45, -30) should NOT appear near (10, 72)."""
        result = dal.get_profiles_by_radius(
            10.0, 72.0, 10_000,
            start_date=None,
            end_date=None,
            db=pg_session,
        )
        platforms = {r["platform_number"] for r in result}
        assert "FCTEST002" not in platforms

    def test_excludes_position_invalid(self, pg_session, seed_test_data):
        """Profile with position_invalid=True must be excluded."""
        result = dal.get_profiles_by_radius(
            10.0, 72.0, 10_000,
            start_date=None,
            end_date=None,
            db=pg_session,
        )
        cycles = {(r["platform_number"], r["cycle_number"]) for r in result}
        assert ("FCTEST001", 1) in cycles       # valid position
        assert ("FCTEST001", 2) not in cycles   # position_invalid=True

    def test_date_range_filter(self, pg_session, seed_test_data):
        """Date window should narrow results."""
        result = dal.get_profiles_by_radius(
            10.0, 72.0, 10_000,
            start_date=datetime(2024, 6, 1, tzinfo=timezone.utc),
            end_date=datetime(2024, 6, 30, tzinfo=timezone.utc),
            db=pg_session,
        )
        # Profile 1 is June 15 — should be within range
        platforms = {r["platform_number"] for r in result}
        assert "FCTEST001" in platforms

    def test_returns_plain_dicts(self, pg_session, seed_test_data):
        """DAL must return plain dicts, not ORM instances."""
        result = dal.get_profiles_by_radius(
            10.0, 72.0, 10_000,
            start_date=None,
            end_date=None,
            db=pg_session,
        )
        assert isinstance(result, list)
        if result:
            assert isinstance(result[0], dict)
            assert "profile_id" in result[0]
            assert "platform_number" in result[0]


# ============================================================================
# get_profiles_by_basin
# ============================================================================
class TestGetProfilesByBasin:
    """Named-region spatial queries using PostGIS ST_Within."""

    def test_returns_profiles_in_region(self, pg_session, seed_test_data):
        """Profile at (10, 72) should be found inside 'Test Arabian Sea'."""
        result = dal.get_profiles_by_basin(
            "Test Arabian Sea",
            start_date=None,
            end_date=None,
            db=pg_session,
        )
        platforms = {r["platform_number"] for r in result}
        assert "FCTEST001" in platforms

    def test_excludes_profiles_outside_region(self, pg_session, seed_test_data):
        """Atlantic profile (45, -30) should NOT appear in 'Test Arabian Sea'."""
        result = dal.get_profiles_by_basin(
            "Test Arabian Sea",
            start_date=None,
            end_date=None,
            db=pg_session,
        )
        platforms = {r["platform_number"] for r in result}
        assert "FCTEST002" not in platforms

    def test_unknown_region_raises_value_error(self, pg_session, seed_test_data):
        """Unknown region name must raise ValueError."""
        with pytest.raises(ValueError, match="Unknown ocean region"):
            dal.get_profiles_by_basin(
                "Nonexistent Ocean",
                start_date=None,
                end_date=None,
                db=pg_session,
            )


# ============================================================================
# get_measurements_by_profile
# ============================================================================
class TestGetMeasurementsByProfile:
    """Depth-level queries with optional pressure filtering."""

    def test_returns_all_measurements(self, pg_session, seed_test_data):
        """Without pressure filters, return all depth levels for the profile."""
        pid = seed_test_data["profile_arabian"].profile_id
        result = dal.get_measurements_by_profile(pid, db=pg_session)
        assert len(result) == 4  # 50, 200, 500, 1000 dbar

    def test_pressure_range_filter(self, pg_session, seed_test_data):
        """Only measurements within the given pressure range are returned."""
        pid = seed_test_data["profile_arabian"].profile_id
        result = dal.get_measurements_by_profile(
            pid, min_pressure=100.0, max_pressure=500.0, db=pg_session,
        )
        pressures = [r["pressure"] for r in result]
        assert all(100.0 <= p <= 500.0 for p in pressures)
        assert 200.0 in pressures
        assert 500.0 in pressures
        assert 50.0 not in pressures
        assert 1000.0 not in pressures

    def test_ordered_by_pressure_ascending(self, pg_session, seed_test_data):
        """Results must be sorted shallowest-first."""
        pid = seed_test_data["profile_arabian"].profile_id
        result = dal.get_measurements_by_profile(pid, db=pg_session)
        pressures = [r["pressure"] for r in result]
        assert pressures == sorted(pressures)

    def test_returns_plain_dicts(self, pg_session, seed_test_data):
        """Each measurement must be a plain dict."""
        pid = seed_test_data["profile_arabian"].profile_id
        result = dal.get_measurements_by_profile(pid, db=pg_session)
        assert isinstance(result, list)
        if result:
            assert isinstance(result[0], dict)
            assert "temperature" in result[0]
            assert "is_outlier" in result[0]


# ============================================================================
# get_float_latest_positions (materialized view)
# ============================================================================
class TestGetFloatLatestPositions:
    """Queries against the mv_float_latest_position materialized view."""

    def test_returns_list_with_test_data(self, pg_session, seed_test_data):
        """After refreshing the MV, test floats must appear."""
        # Refresh MV within the current transaction (non-CONCURRENTLY)
        pg_session.execute(
            text("REFRESH MATERIALIZED VIEW mv_float_latest_position")
        )
        result = dal.get_float_latest_positions(db=pg_session)
        assert isinstance(result, list)
        platforms = {r["platform_number"] for r in result}
        assert "FCTEST001" in platforms
        assert "FCTEST002" in platforms

    def test_result_dict_shape(self, pg_session, seed_test_data):
        """Each dict must contain the expected keys."""
        pg_session.execute(
            text("REFRESH MATERIALIZED VIEW mv_float_latest_position")
        )
        result = dal.get_float_latest_positions(db=pg_session)
        if result:
            keys = set(result[0].keys())
            for expected in ("platform_number", "latitude", "longitude", "cycle_number"):
                assert expected in keys


# ============================================================================
# get_active_datasets
# ============================================================================
class TestGetActiveDatasets:
    """Active dataset listing queries."""

    def test_returns_active_datasets(self, pg_session, seed_test_data):
        """Our test dataset (is_active=True) must appear."""
        result = dal.get_active_datasets(db=pg_session)
        names = {r["name"] for r in result}
        assert "Test Dataset" in names

    def test_result_is_list_of_dicts(self, pg_session, seed_test_data):
        result = dal.get_active_datasets(db=pg_session)
        assert isinstance(result, list)
        if result:
            assert isinstance(result[0], dict)
            assert "dataset_id" in result[0]


# ============================================================================
# get_dataset_by_id
# ============================================================================
class TestGetDatasetById:
    """Single dataset lookup."""

    def test_returns_dataset(self, pg_session, seed_test_data):
        did = seed_test_data["dataset"].dataset_id
        result = dal.get_dataset_by_id(did, db=pg_session)
        assert result["name"] == "Test Dataset"

    def test_raises_for_missing_dataset(self, pg_session):
        """Non-existent dataset_id must raise ValueError."""
        with pytest.raises(ValueError, match="Dataset not found"):
            dal.get_dataset_by_id(999_999, db=pg_session)


# ============================================================================
# search_floats_by_type
# ============================================================================
class TestSearchFloatsByType:
    """Float type filter."""

    def test_bgc_filter(self, pg_session, seed_test_data):
        result = dal.search_floats_by_type("BGC", db=pg_session)
        platforms = {r["platform_number"] for r in result}
        assert "FCTEST002" in platforms
        assert "FCTEST001" not in platforms

    def test_core_filter(self, pg_session, seed_test_data):
        result = dal.search_floats_by_type("core", db=pg_session)
        platforms = {r["platform_number"] for r in result}
        assert "FCTEST001" in platforms
        assert "FCTEST002" not in platforms


# ============================================================================
# get_profiles_with_variable
# ============================================================================
class TestGetProfilesWithVariable:
    """Variable-availability filter."""

    def test_dissolved_oxygen(self, pg_session, seed_test_data):
        """Both profile 1 and profile 3 have doxy_qc measurements."""
        result = dal.get_profiles_with_variable("dissolved_oxygen", db=pg_session)
        pids = {r["profile_id"] for r in result}
        assert seed_test_data["profile_arabian"].profile_id in pids
        assert seed_test_data["profile_atlantic"].profile_id in pids

    def test_chlorophyll(self, pg_session, seed_test_data):
        """Only profile 3 has chlorophyll data."""
        result = dal.get_profiles_with_variable("chlorophyll", db=pg_session)
        pids = {r["profile_id"] for r in result}
        assert seed_test_data["profile_atlantic"].profile_id in pids
        assert seed_test_data["profile_arabian"].profile_id not in pids

    def test_invalid_variable_raises(self, pg_session):
        """Unsupported variable name must raise ValueError."""
        with pytest.raises(ValueError, match="Unsupported variable"):
            dal.get_profiles_with_variable("invalid_var", db=pg_session)


# ============================================================================
# invalidate_query_cache
# ============================================================================
class TestInvalidateQueryCache:
    """Redis cache invalidation through DAL."""

    def test_deletes_cache_keys(self, pg_session, redis_client):
        """invalidate_query_cache must clear all query_cache:* keys."""
        # Seed some cache keys
        redis_client.set("query_cache:test_a", b"data1", ex=60)
        redis_client.set("query_cache:test_b", b"data2", ex=60)

        deleted = dal.invalidate_query_cache(redis_client)
        assert deleted >= 2

        remaining = redis_client.keys("query_cache:*")
        assert len(remaining) == 0
