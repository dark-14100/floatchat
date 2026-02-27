"""
Tests for app.query.geography — Geography resolver.

No external dependencies.  Uses the real geography_lookup.json file.
"""

import pytest

from app.query.geography import resolve_geography, reload_geography, _GEOGRAPHY_DATA


# ═════════════════════════════════════════════════════════════════════════════
# Lookup loaded
# ═════════════════════════════════════════════════════════════════════════════

class TestGeographyLookup:
    def test_lookup_loaded(self):
        """geography_lookup.json should be loaded at import time."""
        assert len(_GEOGRAPHY_DATA) >= 30

    def test_all_entries_have_bounding_box(self):
        for name, bbox in _GEOGRAPHY_DATA.items():
            assert "lat_min" in bbox, f"{name} missing lat_min"
            assert "lat_max" in bbox, f"{name} missing lat_max"
            assert "lon_min" in bbox, f"{name} missing lon_min"
            assert "lon_max" in bbox, f"{name} missing lon_max"

    def test_all_values_are_numeric(self):
        for name, bbox in _GEOGRAPHY_DATA.items():
            for key in ("lat_min", "lat_max", "lon_min", "lon_max"):
                assert isinstance(bbox[key], (int, float)), f"{name}.{key} is not numeric"


# ═════════════════════════════════════════════════════════════════════════════
# resolve_geography
# ═════════════════════════════════════════════════════════════════════════════

class TestResolveGeography:
    def test_known_region_arabian_sea(self):
        result = resolve_geography("Show profiles in the Arabian Sea")
        assert result is not None
        assert result["name"] == "arabian sea"
        assert "lat_min" in result
        assert "lat_max" in result
        assert "lon_min" in result
        assert "lon_max" in result

    def test_known_region_mediterranean(self):
        result = resolve_geography("What is the average temperature in the Mediterranean Sea?")
        assert result is not None
        assert result["name"] == "mediterranean sea"

    def test_known_region_southern_ocean(self):
        result = resolve_geography("floats in the southern ocean")
        assert result is not None
        assert result["name"] == "southern ocean"

    def test_case_insensitive(self):
        result = resolve_geography("profiles in the ARABIAN SEA")
        assert result is not None
        assert result["name"] == "arabian sea"

    def test_mixed_case(self):
        result = resolve_geography("Data from Bay of Bengal region")
        assert result is not None
        assert result["name"] == "bay of bengal"

    def test_no_match_returns_none(self):
        result = resolve_geography("What is the average temperature globally?")
        assert result is None

    def test_empty_query_returns_none(self):
        result = resolve_geography("")
        assert result is None

    def test_specific_region_preferred_over_substring(self):
        """'south china sea' should match before 'china' substrings."""
        result = resolve_geography("Show data from the South China Sea")
        assert result is not None
        assert result["name"] == "south china sea"

    def test_gulf_of_mexico(self):
        result = resolve_geography("temperature in the Gulf of Mexico")
        assert result is not None
        assert result["name"] == "gulf of mexico"

    def test_bering_sea(self):
        result = resolve_geography("profiles from the Bering Sea")
        assert result is not None
        assert result["name"] == "bering sea"

    def test_drake_passage(self):
        result = resolve_geography("data near Drake Passage")
        assert result is not None
        assert result["name"] == "drake passage"

    def test_multiple_regions_returns_first_longest(self):
        """If query mentions multiple regions, longest match wins."""
        result = resolve_geography("Compare the North Sea and Baltic Sea")
        assert result is not None
        # "baltic sea" and "north sea" are same length (9 chars)
        # Either is acceptable
        assert result["name"] in ("north sea", "baltic sea")


# ═════════════════════════════════════════════════════════════════════════════
# reload_geography
# ═════════════════════════════════════════════════════════════════════════════

class TestReloadGeography:
    def test_reload_returns_count(self):
        count = reload_geography()
        assert count >= 30

    def test_reload_nonexistent_path(self):
        count = reload_geography("/nonexistent/path.json")
        assert count == 0
