"""
Tests for Feature 3: Search Module.

Tests:
    6.  Results sorted by score descending
    7.  Results below threshold excluded
    8.  Variable filter excludes non-matching datasets
    9.  date_from filter works
    10. Recency boost increases score
    11. Limit respected and capped at max
    12. Empty list returned when no results meet threshold
"""

from datetime import datetime, timedelta, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_row(
    dataset_id,
    cosine_distance,
    name="Test Dataset",
    variable_list=None,
    ingestion_date=None,
    bbox=None,
    date_range_start=None,
    date_range_end=None,
    float_count=5,
    summary_text="A dataset",
    is_active=True,
    status="indexed",
):
    """Build a fake row as returned by db.execute() for search_datasets."""
    return SimpleNamespace(
        dataset_id=dataset_id,
        cosine_distance=cosine_distance,
        name=name,
        variable_list=variable_list or {"temperature": True},
        ingestion_date=ingestion_date or datetime(2025, 1, 1, tzinfo=timezone.utc),
        bbox=bbox,
        date_range_start=date_range_start or datetime(2024, 6, 1, tzinfo=timezone.utc),
        date_range_end=date_range_end or datetime(2025, 6, 1, tzinfo=timezone.utc),
        float_count=float_count,
        summary_text=summary_text,
        is_active=is_active,
        status=status,
    )


def _make_float_row(
    float_id,
    cosine_distance,
    platform_number="2902150",
    float_type="core",
    deployment_lat=15.0,
    deployment_lon=72.5,
    deployment_date=None,
    status="indexed",
):
    """Build a fake row for search_floats."""
    return SimpleNamespace(
        float_id=float_id,
        cosine_distance=cosine_distance,
        platform_number=platform_number,
        float_type=float_type,
        deployment_lat=deployment_lat,
        deployment_lon=deployment_lon,
        deployment_date=deployment_date,
        status=status,
    )


# Settings override for all tests — no real threshold / boost issues
_TEST_SETTINGS = {
    "SEARCH_DEFAULT_LIMIT": 10,
    "SEARCH_MAX_LIMIT": 50,
    "SEARCH_SIMILARITY_THRESHOLD": 0.3,
    "RECENCY_BOOST_DAYS": 90,
    "RECENCY_BOOST_VALUE": 0.05,
    "REGION_MATCH_BOOST_VALUE": 0.10,
    "EMBEDDING_BATCH_SIZE": 100,
    "EMBEDDING_MODEL": "text-embedding-3-small",
}


# ── Test 6: Results sorted by score descending ──────────────────────────────


class TestSearchDatasetsSorting:
    @patch("app.search.search.embed_single")
    @patch("app.search.search.settings")
    def test_results_sorted_by_score_descending(self, mock_settings, mock_embed):
        from app.search.search import search_datasets

        for k, v in _TEST_SETTINGS.items():
            setattr(mock_settings, k, v)

        mock_embed.return_value = [0.1] * 1536

        # Create rows with different cosine distances (lower = more similar)
        rows = [
            _make_row(dataset_id=1, cosine_distance=0.5),   # score ~0.5
            _make_row(dataset_id=2, cosine_distance=0.2),   # score ~0.8
            _make_row(dataset_id=3, cosine_distance=0.35),  # score ~0.65
        ]

        mock_db = MagicMock()
        mock_db.execute.return_value.all.return_value = rows

        results = search_datasets("ocean data", mock_db, MagicMock())

        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)
        assert len(results) == 3


# ── Test 7: Results below threshold excluded ────────────────────────────────


class TestSearchThresholdFiltering:
    @patch("app.search.search.embed_single")
    @patch("app.search.search.settings")
    def test_results_below_threshold_excluded(self, mock_settings, mock_embed):
        from app.search.search import search_datasets

        for k, v in _TEST_SETTINGS.items():
            setattr(mock_settings, k, v)
        mock_settings.SEARCH_SIMILARITY_THRESHOLD = 0.5

        mock_embed.return_value = [0.1] * 1536

        rows = [
            _make_row(dataset_id=1, cosine_distance=0.3),   # score=0.7 → above 0.5
            _make_row(dataset_id=2, cosine_distance=0.8),   # score=0.2 → below 0.5
            _make_row(dataset_id=3, cosine_distance=0.55),  # score=0.45 → below 0.5
        ]

        mock_db = MagicMock()
        mock_db.execute.return_value.all.return_value = rows

        results = search_datasets("test", mock_db, MagicMock())

        assert len(results) == 1
        assert results[0]["dataset_id"] == 1


# ── Test 8: Variable filter excludes non-matching datasets ──────────────────


class TestSearchVariableFilter:
    @patch("app.search.search.embed_single")
    @patch("app.search.search.settings")
    def test_variable_filter_applied_in_sql(self, mock_settings, mock_embed):
        """
        The variable filter is applied at the SQL level. We verify that
        passing a variable filter calls execute with the right statement
        by checking that the mock DB is invoked (the actual SQL filtering
        is tested in integration tests).
        """
        from app.search.search import search_datasets

        for k, v in _TEST_SETTINGS.items():
            setattr(mock_settings, k, v)

        mock_embed.return_value = [0.1] * 1536

        # Return rows that already passed the SQL filter (mock)
        rows = [
            _make_row(
                dataset_id=1,
                cosine_distance=0.2,
                variable_list={"temperature": True, "salinity": True},
            ),
        ]

        mock_db = MagicMock()
        mock_db.execute.return_value.all.return_value = rows

        results = search_datasets(
            "temperature data",
            mock_db,
            MagicMock(),
            filters={"variable": "temperature"},
        )

        # DB.execute was called (SQL with variable filter)
        assert mock_db.execute.called
        assert len(results) == 1


# ── Test 9: date_from filter works ──────────────────────────────────────────


class TestSearchDateFromFilter:
    @patch("app.search.search.embed_single")
    @patch("app.search.search.settings")
    def test_date_from_filter_applied(self, mock_settings, mock_embed):
        """
        The date_from filter is applied at SQL level. We verify the mock
        flow works and that the returned results reflect the filter.
        """
        from app.search.search import search_datasets

        for k, v in _TEST_SETTINGS.items():
            setattr(mock_settings, k, v)

        mock_embed.return_value = [0.1] * 1536

        # Simulate: only datasets whose date_range_end >= date_from survive
        rows = [
            _make_row(
                dataset_id=1,
                cosine_distance=0.2,
                date_range_start=datetime(2025, 1, 1, tzinfo=timezone.utc),
                date_range_end=datetime(2025, 6, 1, tzinfo=timezone.utc),
            ),
        ]

        mock_db = MagicMock()
        mock_db.execute.return_value.all.return_value = rows

        results = search_datasets(
            "test",
            mock_db,
            MagicMock(),
            filters={"date_from": "2025-01-01"},
        )

        assert mock_db.execute.called
        assert len(results) == 1


# ── Test 10: Recency boost increases score ──────────────────────────────────


class TestSearchRecencyBoost:
    @patch("app.search.search.embed_single")
    @patch("app.search.search.settings")
    def test_recency_boost_increases_score(self, mock_settings, mock_embed):
        from app.search.search import search_datasets

        for k, v in _TEST_SETTINGS.items():
            setattr(mock_settings, k, v)

        mock_embed.return_value = [0.1] * 1536

        now = datetime.now(timezone.utc)

        # Both datasets have the same cosine distance
        rows = [
            _make_row(
                dataset_id=1,
                cosine_distance=0.35,
                ingestion_date=now - timedelta(days=10),  # recent → gets boost
            ),
            _make_row(
                dataset_id=2,
                cosine_distance=0.35,
                ingestion_date=now - timedelta(days=365),  # old → no boost
            ),
        ]

        mock_db = MagicMock()
        mock_db.execute.return_value.all.return_value = rows

        results = search_datasets("test", mock_db, MagicMock())

        assert len(results) == 2
        # Recent dataset should have higher score due to recency boost
        recent = next(r for r in results if r["dataset_id"] == 1)
        old = next(r for r in results if r["dataset_id"] == 2)
        assert recent["score"] > old["score"]


# ── Test 11: Limit respected and capped at max ─────────────────────────────


class TestSearchLimit:
    @patch("app.search.search.embed_single")
    @patch("app.search.search.settings")
    def test_limit_respected(self, mock_settings, mock_embed):
        from app.search.search import search_datasets

        for k, v in _TEST_SETTINGS.items():
            setattr(mock_settings, k, v)

        mock_embed.return_value = [0.1] * 1536

        rows = [
            _make_row(dataset_id=i, cosine_distance=0.1 + i * 0.01)
            for i in range(20)
        ]

        mock_db = MagicMock()
        mock_db.execute.return_value.all.return_value = rows

        results = search_datasets("test", mock_db, MagicMock(), limit=3)
        assert len(results) == 3

    def test_limit_exceeds_max_raises_value_error(self):
        from app.search.search import search_datasets

        with patch("app.search.search.settings") as mock_settings:
            for k, v in _TEST_SETTINGS.items():
                setattr(mock_settings, k, v)

            with pytest.raises(ValueError, match="exceeds maximum"):
                search_datasets(
                    "test",
                    MagicMock(),
                    MagicMock(),
                    limit=100,  # exceeds SEARCH_MAX_LIMIT = 50
                )


# ── Test 12: Empty list when no results meet threshold ──────────────────────


class TestSearchEmptyResults:
    @patch("app.search.search.embed_single")
    @patch("app.search.search.settings")
    def test_empty_list_when_no_results_meet_threshold(self, mock_settings, mock_embed):
        from app.search.search import search_datasets

        for k, v in _TEST_SETTINGS.items():
            setattr(mock_settings, k, v)
        mock_settings.SEARCH_SIMILARITY_THRESHOLD = 0.9  # very high threshold

        mock_embed.return_value = [0.1] * 1536

        # All results have low similarity
        rows = [
            _make_row(dataset_id=1, cosine_distance=0.8),  # score=0.2
            _make_row(dataset_id=2, cosine_distance=0.75),  # score=0.25
        ]

        mock_db = MagicMock()
        mock_db.execute.return_value.all.return_value = rows

        results = search_datasets("test", mock_db, MagicMock())

        assert results == []

    @patch("app.search.search.embed_single")
    @patch("app.search.search.settings")
    def test_empty_list_when_no_candidates(self, mock_settings, mock_embed):
        from app.search.search import search_datasets

        for k, v in _TEST_SETTINGS.items():
            setattr(mock_settings, k, v)

        mock_embed.return_value = [0.1] * 1536

        mock_db = MagicMock()
        mock_db.execute.return_value.all.return_value = []

        results = search_datasets("nonexistent data", mock_db, MagicMock())
        assert results == []


# ── search_floats basic tests ───────────────────────────────────────────────


class TestSearchFloats:
    @patch("app.search.search.embed_single")
    @patch("app.search.search.settings")
    def test_returns_sorted_results(self, mock_settings, mock_embed):
        from app.search.search import search_floats

        for k, v in _TEST_SETTINGS.items():
            setattr(mock_settings, k, v)

        mock_embed.return_value = [0.1] * 1536

        rows = [
            _make_float_row(float_id=1, cosine_distance=0.4),
            _make_float_row(float_id=2, cosine_distance=0.2),
            _make_float_row(float_id=3, cosine_distance=0.3),
        ]

        mock_db = MagicMock()
        mock_db.execute.return_value.all.return_value = rows

        results = search_floats("BGC floats", mock_db, MagicMock())

        scores = [r["score"] for r in results]
        assert scores == sorted(scores, reverse=True)

    @patch("app.search.search.embed_single")
    @patch("app.search.search.settings")
    def test_below_threshold_excluded(self, mock_settings, mock_embed):
        from app.search.search import search_floats

        for k, v in _TEST_SETTINGS.items():
            setattr(mock_settings, k, v)
        mock_settings.SEARCH_SIMILARITY_THRESHOLD = 0.6

        mock_embed.return_value = [0.1] * 1536

        rows = [
            _make_float_row(float_id=1, cosine_distance=0.3),   # score=0.7 → above
            _make_float_row(float_id=2, cosine_distance=0.8),   # score=0.2 → below
        ]

        mock_db = MagicMock()
        mock_db.execute.return_value.all.return_value = rows

        results = search_floats("test", mock_db, MagicMock())

        assert len(results) == 1
        assert results[0]["float_id"] == 1

    def test_limit_exceeds_max_raises(self):
        from app.search.search import search_floats

        with patch("app.search.search.settings") as mock_settings:
            for k, v in _TEST_SETTINGS.items():
                setattr(mock_settings, k, v)

            with pytest.raises(ValueError, match="exceeds maximum"):
                search_floats("test", MagicMock(), MagicMock(), limit=100)
