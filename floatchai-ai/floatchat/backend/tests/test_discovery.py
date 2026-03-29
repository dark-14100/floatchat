"""
Tests for Feature 3: Discovery Module.

Tests:
    13. "Bengal Bay" → "Bay of Bengal" fuzzy match
    14. ValueError with suggestions for unrecognized names
    15. discover_floats_by_region returns only floats within polygon
    16. discover_floats_by_variable raises ValueError for unsupported variables
    17. get_all_summaries returns only active datasets
    18. get_dataset_summary raises ValueError for inactive dataset
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch, PropertyMock

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_ocean_region(region_name="Indian Ocean", region_id=1, geom="POLYGON(...)"):
    return SimpleNamespace(
        region_id=region_id,
        region_name=region_name,
        region_type="ocean",
        parent_region_id=None,
        geom=geom,
        description=None,
    )


def _make_dataset(
    dataset_id=1,
    name="Test Dataset",
    is_active=True,
    summary_text="A dataset summary.",
    float_count=10,
    profile_count=100,
    variable_list=None,
    bbox=None,
    ingestion_date=None,
    date_range_start=None,
    date_range_end=None,
):
    return SimpleNamespace(
        dataset_id=dataset_id,
        name=name,
        is_active=is_active,
        summary_text=summary_text,
        float_count=float_count,
        profile_count=profile_count,
        variable_list=variable_list or {"temperature": True},
        bbox=bbox,
        ingestion_date=ingestion_date or datetime(2025, 7, 1, tzinfo=timezone.utc),
        date_range_start=date_range_start or datetime(2025, 1, 1, tzinfo=timezone.utc),
        date_range_end=date_range_end or datetime(2025, 6, 1, tzinfo=timezone.utc),
    )


# ── Test 13: "Bengal Bay" → "Bay of Bengal" fuzzy match ─────────────────────


class TestResolveRegionName:
    @patch("app.search.discovery.settings")
    def test_bengal_bay_resolves_to_bay_of_bengal(self, mock_settings):
        from app.search.discovery import resolve_region_name

        mock_settings.FUZZY_MATCH_THRESHOLD = 0.3

        # Mock the DB to return ocean_regions ordered by similarity
        bay_of_bengal = _make_ocean_region(
            region_name="Bay of Bengal", region_id=5
        )

        mock_db = MagicMock()
        # db.execute(stmt).all() returns list of (OceanRegion, sim_score) tuples
        mock_db.execute.return_value.all.return_value = [
            (bay_of_bengal, 0.65),  # best match — above threshold
            (_make_ocean_region("Arabian Sea", region_id=2), 0.15),
            (_make_ocean_region("Indian Ocean", region_id=1), 0.10),
        ]

        result = resolve_region_name("Bengal Bay", mock_db)

        assert result.region_name == "Bay of Bengal"
        assert result.region_id == 5

    @patch("app.search.discovery.settings")
    def test_exact_match_works(self, mock_settings):
        from app.search.discovery import resolve_region_name

        mock_settings.FUZZY_MATCH_THRESHOLD = 0.3

        arabian_sea = _make_ocean_region("Arabian Sea", region_id=2)

        mock_db = MagicMock()
        mock_db.execute.return_value.all.return_value = [
            (arabian_sea, 1.0),
            (_make_ocean_region("Red Sea", region_id=10), 0.3),
        ]

        result = resolve_region_name("Arabian Sea", mock_db)
        assert result.region_name == "Arabian Sea"


# ── Test 14: ValueError with suggestions for unrecognized names ─────────────


class TestResolveRegionNameNotFound:
    @patch("app.search.discovery.settings")
    def test_raises_value_error_with_suggestions(self, mock_settings):
        from app.search.discovery import resolve_region_name

        mock_settings.FUZZY_MATCH_THRESHOLD = 0.4

        mock_db = MagicMock()
        mock_db.execute.return_value.all.return_value = [
            (_make_ocean_region("Indian Ocean", region_id=1), 0.2),
            (_make_ocean_region("Pacific Ocean", region_id=2), 0.15),
            (_make_ocean_region("Atlantic Ocean", region_id=3), 0.1),
        ]

        with pytest.raises(ValueError, match="Did you mean"):
            resolve_region_name("Atlantis Ocean", mock_db)

    @patch("app.search.discovery.settings")
    def test_raises_value_error_when_no_regions_exist(self, mock_settings):
        from app.search.discovery import resolve_region_name

        mock_settings.FUZZY_MATCH_THRESHOLD = 0.4

        mock_db = MagicMock()
        mock_db.execute.return_value.all.return_value = []

        with pytest.raises(ValueError, match="No ocean regions exist"):
            resolve_region_name("Some Region", mock_db)

    @patch("app.search.discovery.settings")
    def test_suggestions_include_top_3(self, mock_settings):
        from app.search.discovery import resolve_region_name

        mock_settings.FUZZY_MATCH_THRESHOLD = 0.5

        mock_db = MagicMock()
        mock_db.execute.return_value.all.return_value = [
            (_make_ocean_region("Mediterranean Sea", region_id=1), 0.35),
            (_make_ocean_region("Red Sea", region_id=2), 0.3),
            (_make_ocean_region("Caribbean Sea", region_id=3), 0.25),
            (_make_ocean_region("Persian Gulf", region_id=4), 0.1),
        ]

        with pytest.raises(ValueError) as exc_info:
            resolve_region_name("Meditteranean", mock_db)

        error_msg = str(exc_info.value)
        assert "Mediterranean Sea" in error_msg
        assert "Red Sea" in error_msg
        assert "Caribbean Sea" in error_msg


# ── Test 15: discover_floats_by_region returns only floats within polygon ───


class TestDiscoverFloatsByRegion:
    @patch("app.search.discovery.resolve_region_name")
    def test_returns_floats_within_region(self, mock_resolve):
        from app.search.discovery import discover_floats_by_region

        region = _make_ocean_region("Indian Ocean", region_id=1)
        mock_resolve.return_value = region

        # Mock DB results — floats that are within the region
        mock_row_1 = SimpleNamespace(
            platform_number="2902150",
            float_id=10,
            float_type="core",
            latitude=15.0,
            longitude=72.5,
            timestamp=datetime(2025, 6, 1, tzinfo=timezone.utc),
            cycle_number=42,
        )
        mock_row_2 = SimpleNamespace(
            platform_number="2902151",
            float_id=11,
            float_type="BGC",
            latitude=12.0,
            longitude=80.0,
            timestamp=datetime(2025, 5, 15, tzinfo=timezone.utc),
            cycle_number=38,
        )

        mock_db = MagicMock()
        mock_db.execute.return_value.all.return_value = [mock_row_1, mock_row_2]

        results = discover_floats_by_region("Indian Ocean", None, mock_db)

        assert len(results) == 2
        assert results[0]["platform_number"] == "2902150"
        assert results[1]["platform_number"] == "2902151"

        # resolve_region_name was called with the input name
        mock_resolve.assert_called_once_with("Indian Ocean", mock_db)

    @patch("app.search.discovery.resolve_region_name")
    def test_raises_on_invalid_region(self, mock_resolve):
        from app.search.discovery import discover_floats_by_region

        mock_resolve.side_effect = ValueError("Region 'Atlantis' not found.")

        mock_db = MagicMock()

        with pytest.raises(ValueError, match="not found"):
            discover_floats_by_region("Atlantis", None, mock_db)

    @patch("app.search.discovery.resolve_region_name")
    def test_empty_list_when_no_floats_in_region(self, mock_resolve):
        from app.search.discovery import discover_floats_by_region

        mock_resolve.return_value = _make_ocean_region("Arctic Ocean", region_id=9)

        mock_db = MagicMock()
        mock_db.execute.return_value.all.return_value = []

        results = discover_floats_by_region("Arctic Ocean", None, mock_db)
        assert results == []


# ── Test 16: discover_floats_by_variable raises ValueError for unsupported ──


class TestDiscoverFloatsByVariable:
    def test_raises_for_unsupported_variable(self):
        from app.search.discovery import discover_floats_by_variable

        mock_db = MagicMock()

        with pytest.raises(ValueError, match="Unsupported variable"):
            discover_floats_by_variable("magnetism", mock_db)

    def test_raises_for_pressure_not_in_allowed(self):
        from app.search.discovery import discover_floats_by_variable

        mock_db = MagicMock()

        with pytest.raises(ValueError, match="Unsupported variable"):
            discover_floats_by_variable("pressure", mock_db)

    def test_valid_variable_accepted(self):
        from app.search.discovery import discover_floats_by_variable

        mock_db = MagicMock()
        # Return empty scalars list (no floats have this variable)
        mock_db.execute.return_value.scalars.return_value.all.return_value = []

        # Should not raise — "temperature" is in the allowed list
        results = discover_floats_by_variable("temperature", mock_db)
        assert results == []


# ── Test 17: get_all_summaries returns only active datasets ─────────────────


class TestGetAllSummaries:
    def test_returns_only_active_datasets(self):
        from app.search.discovery import get_all_summaries

        active_ds = _make_dataset(dataset_id=1, name="Active DS", is_active=True)
        # The inactive dataset should NOT appear — it's filtered at SQL level.
        # We simulate the SQL returning only active datasets.

        mock_db = MagicMock()
        mock_db.execute.return_value.scalars.return_value.all.return_value = [active_ds]

        results = get_all_summaries(mock_db)

        assert len(results) == 1
        assert results[0]["dataset_id"] == 1
        assert results[0]["name"] == "Active DS"

    def test_truncates_summary_to_300_chars(self):
        from app.search.discovery import get_all_summaries

        long_summary = "A" * 500
        ds = _make_dataset(dataset_id=1, summary_text=long_summary)

        mock_db = MagicMock()
        mock_db.execute.return_value.scalars.return_value.all.return_value = [ds]

        results = get_all_summaries(mock_db)

        assert len(results[0]["summary_text"]) == 300

    def test_empty_when_no_active_datasets(self):
        from app.search.discovery import get_all_summaries

        mock_db = MagicMock()
        mock_db.execute.return_value.scalars.return_value.all.return_value = []

        results = get_all_summaries(mock_db)
        assert results == []

    def test_ordered_by_ingestion_date_desc(self):
        """
        The SQL query orders by ingestion_date desc, so the mock returns
        datasets in that order. We verify the results preserve the order.
        """
        from app.search.discovery import get_all_summaries

        ds1 = _make_dataset(
            dataset_id=1,
            name="Older",
            ingestion_date=datetime(2025, 1, 1, tzinfo=timezone.utc),
        )
        ds2 = _make_dataset(
            dataset_id=2,
            name="Newer",
            ingestion_date=datetime(2025, 7, 1, tzinfo=timezone.utc),
        )

        mock_db = MagicMock()
        # Simulate SQL ordering: newest first
        mock_db.execute.return_value.scalars.return_value.all.return_value = [ds2, ds1]

        results = get_all_summaries(mock_db)

        assert results[0]["name"] == "Newer"
        assert results[1]["name"] == "Older"


# ── Test 18: get_dataset_summary raises ValueError for inactive dataset ─────


class TestGetDatasetSummary:
    def test_raises_for_inactive_dataset(self):
        from app.search.discovery import get_dataset_summary

        inactive_ds = _make_dataset(dataset_id=5, is_active=False)

        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = inactive_ds

        with pytest.raises(ValueError, match="inactive"):
            get_dataset_summary(5, mock_db)

    def test_raises_for_nonexistent_dataset(self):
        from app.search.discovery import get_dataset_summary

        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        with pytest.raises(ValueError, match="not found"):
            get_dataset_summary(999, mock_db)

    def test_returns_complete_summary_for_active_dataset(self):
        from app.search.discovery import get_dataset_summary

        ds = _make_dataset(
            dataset_id=1,
            name="Argo Indian Ocean",
            summary_text="Temperature profiles from Indian Ocean",
            float_count=42,
            profile_count=500,
            is_active=True,
            bbox=None,
        )

        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = ds

        result = get_dataset_summary(1, mock_db)

        assert result["dataset_id"] == 1
        assert result["name"] == "Argo Indian Ocean"
        assert result["summary_text"] == "Temperature profiles from Indian Ocean"
        assert result["float_count"] == 42
        assert result["profile_count"] == 500
        assert result["is_active"] is True
        assert result["bbox"] is None  # no bbox geometry
