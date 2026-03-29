"""
Tests for Feature 3: Embeddings Module + Indexer (embedding failure path).

Tests:
    1. build_dataset_embedding_text produces non-empty string with dataset name and variables
    2. build_float_embedding_text produces string with float type and platform number
    3. embed_texts with 150 strings calls API exactly twice (batch 100)
    4. embed_texts returns correct length list with 1536-dim vectors
    5. index_dataset sets embedding_failed on API error without raising
"""

from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock, patch

import pytest


# ── Helpers ──────────────────────────────────────────────────────────────────


def _make_dataset(**overrides):
    """Build a fake Dataset-like object with sensible defaults."""
    defaults = {
        "dataset_id": 1,
        "name": "Argo Indian Ocean 2025",
        "source_filename": "argo_indian_ocean.nc",
        "variable_list": {"temperature": True, "salinity": True, "dissolved_oxygen": True},
        "date_range_start": datetime(2025, 1, 1, tzinfo=timezone.utc),
        "date_range_end": datetime(2025, 6, 30, tzinfo=timezone.utc),
        "float_count": 42,
        "profile_count": 500,
        "summary_text": "Argo profiles from the Indian Ocean covering temperature and salinity.",
        "is_active": True,
        "ingestion_date": datetime(2025, 7, 1, tzinfo=timezone.utc),
        "bbox": None,
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _make_float(**overrides):
    """Build a fake Float-like object with sensible defaults."""
    defaults = {
        "float_id": 10,
        "platform_number": "2902150",
        "float_type": "BGC",
        "deployment_date": datetime(2024, 3, 15, tzinfo=timezone.utc),
        "deployment_lat": 15.0,
        "deployment_lon": 72.5,
        "country": "India",
        "program": "IndOOS",
    }
    defaults.update(overrides)
    return SimpleNamespace(**defaults)


def _mock_embedding_response(vectors):
    """Build a mock OpenAI embeddings.create() response from a list of vectors."""
    data = []
    for i, vec in enumerate(vectors):
        data.append(SimpleNamespace(embedding=vec, index=i))
    usage = SimpleNamespace(total_tokens=len(vectors) * 10)
    return SimpleNamespace(data=data, usage=usage)


# ── Test 1: build_dataset_embedding_text ─────────────────────────────────────


class TestBuildDatasetEmbeddingText:
    def test_produces_non_empty_string(self):
        from app.search.embeddings import build_dataset_embedding_text

        dataset = _make_dataset()
        text = build_dataset_embedding_text(dataset)

        assert isinstance(text, str)
        assert len(text) > 0

    def test_contains_dataset_name(self):
        from app.search.embeddings import build_dataset_embedding_text

        dataset = _make_dataset(name="North Atlantic Deployment")
        text = build_dataset_embedding_text(dataset)

        assert "North Atlantic Deployment" in text

    def test_contains_variables(self):
        from app.search.embeddings import build_dataset_embedding_text

        dataset = _make_dataset(
            variable_list={"temperature": True, "salinity": True}
        )
        text = build_dataset_embedding_text(dataset)

        assert "temperature" in text
        assert "salinity" in text

    def test_contains_summary_text(self):
        from app.search.embeddings import build_dataset_embedding_text

        dataset = _make_dataset(summary_text="Argo profiles from the Indian Ocean.")
        text = build_dataset_embedding_text(dataset)

        assert "Indian Ocean" in text

    def test_handles_list_variable_list(self):
        from app.search.embeddings import build_dataset_embedding_text

        dataset = _make_dataset(variable_list=["temperature", "salinity", "ph"])
        text = build_dataset_embedding_text(dataset)

        assert "temperature" in text
        assert "salinity" in text
        assert "ph" in text

    def test_handles_missing_optional_fields(self):
        from app.search.embeddings import build_dataset_embedding_text

        dataset = _make_dataset(
            date_range_start=None,
            date_range_end=None,
            float_count=None,
            profile_count=None,
            summary_text=None,
            variable_list=None,
        )
        text = build_dataset_embedding_text(dataset)

        # Should still contain at least the dataset name
        assert "Argo Indian Ocean 2025" in text
        assert len(text) > 0


# ── Test 2: build_float_embedding_text ───────────────────────────────────────


class TestBuildFloatEmbeddingText:
    def test_produces_non_empty_string(self):
        from app.search.embeddings import build_float_embedding_text

        float_obj = _make_float()
        text = build_float_embedding_text(float_obj, ["temperature", "salinity"])

        assert isinstance(text, str)
        assert len(text) > 0

    def test_contains_platform_number(self):
        from app.search.embeddings import build_float_embedding_text

        float_obj = _make_float(platform_number="5904567")
        text = build_float_embedding_text(float_obj, ["temperature"])

        assert "5904567" in text

    def test_contains_float_type(self):
        from app.search.embeddings import build_float_embedding_text

        float_obj = _make_float(float_type="BGC")
        text = build_float_embedding_text(float_obj, ["temperature"])

        assert "BGC" in text

    def test_contains_region_name_when_provided(self):
        from app.search.embeddings import build_float_embedding_text

        float_obj = _make_float()
        text = build_float_embedding_text(
            float_obj, ["temperature"], region_name="Arabian Sea"
        )

        assert "Arabian Sea" in text

    def test_contains_variables(self):
        from app.search.embeddings import build_float_embedding_text

        float_obj = _make_float()
        text = build_float_embedding_text(
            float_obj, ["temperature", "dissolved_oxygen", "ph"]
        )

        assert "temperature" in text
        assert "dissolved_oxygen" in text
        assert "ph" in text


# ── Test 3: embed_texts batching ─────────────────────────────────────────────


class TestEmbedTextsBatching:
    @patch("app.search.embeddings.settings")
    def test_150_texts_calls_api_exactly_twice(self, mock_settings):
        from app.search.embeddings import embed_texts

        mock_settings.EMBEDDING_BATCH_SIZE = 100
        mock_settings.EMBEDDING_MODEL = "text-embedding-3-small"

        # 150 texts → batch 1 (100) + batch 2 (50) = 2 API calls
        texts = [f"text {i}" for i in range(150)]

        # Build a mock client
        mock_client = MagicMock()

        # First call returns 100 vectors, second returns 50
        dim = 1536
        batch1_vectors = [[0.1] * dim for _ in range(100)]
        batch2_vectors = [[0.2] * dim for _ in range(50)]

        mock_client.embeddings.create.side_effect = [
            _mock_embedding_response(batch1_vectors),
            _mock_embedding_response(batch2_vectors),
        ]

        result = embed_texts(texts, mock_client)

        # API called exactly twice
        assert mock_client.embeddings.create.call_count == 2

        # Total results = 150
        assert len(result) == 150

    @patch("app.search.embeddings.settings")
    def test_exact_batch_size_calls_once(self, mock_settings):
        from app.search.embeddings import embed_texts

        mock_settings.EMBEDDING_BATCH_SIZE = 100
        mock_settings.EMBEDDING_MODEL = "text-embedding-3-small"

        texts = [f"text {i}" for i in range(100)]
        mock_client = MagicMock()
        vectors = [[0.1] * 1536 for _ in range(100)]
        mock_client.embeddings.create.return_value = _mock_embedding_response(vectors)

        embed_texts(texts, mock_client)
        assert mock_client.embeddings.create.call_count == 1


# ── Test 4: embed_texts returns correct shape ────────────────────────────────


class TestEmbedTextsReturnShape:
    @patch("app.search.embeddings.settings")
    def test_returns_correct_length_list(self, mock_settings):
        from app.search.embeddings import embed_texts

        mock_settings.EMBEDDING_BATCH_SIZE = 100
        mock_settings.EMBEDDING_MODEL = "text-embedding-3-small"

        texts = ["hello", "world", "test"]
        dim = 1536
        vectors = [[float(j) / dim for j in range(dim)] for _ in range(3)]

        mock_client = MagicMock()
        mock_client.embeddings.create.return_value = _mock_embedding_response(vectors)

        result = embed_texts(texts, mock_client)

        assert len(result) == 3
        for vec in result:
            assert len(vec) == 1536

    @patch("app.search.embeddings.settings")
    def test_empty_input_returns_empty_list(self, mock_settings):
        from app.search.embeddings import embed_texts

        mock_settings.EMBEDDING_BATCH_SIZE = 100
        mock_settings.EMBEDDING_MODEL = "text-embedding-3-small"

        mock_client = MagicMock()
        result = embed_texts([], mock_client)

        assert result == []
        mock_client.embeddings.create.assert_not_called()


# ── Test 5: index_dataset sets embedding_failed on API error ─────────────────


class TestIndexDatasetEmbeddingFailure:
    @patch("app.search.indexer._upsert_dataset_embedding")
    @patch("app.search.indexer.embed_single")
    @patch("app.search.indexer.build_dataset_embedding_text")
    def test_sets_embedding_failed_on_api_error(
        self, mock_build_text, mock_embed, mock_upsert
    ):
        from app.search.indexer import index_dataset

        # Setup
        dataset = _make_dataset()
        mock_build_text.return_value = "some embedding text"
        mock_embed.side_effect = Exception("OpenAI API rate limit exceeded")

        # Mock DB session
        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = dataset

        mock_client = MagicMock()

        # Should return False (failure) without raising
        result = index_dataset(dataset_id=1, db=mock_db, openai_client=mock_client)

        assert result is False

        # Should have called _upsert_dataset_embedding with status='embedding_failed'
        mock_upsert.assert_called_once()
        call_kwargs = mock_upsert.call_args
        assert call_kwargs[1]["status"] == "embedding_failed"
        assert call_kwargs[1]["embedding"] is None

    @patch("app.search.indexer._upsert_dataset_embedding")
    @patch("app.search.indexer.embed_single")
    @patch("app.search.indexer.build_dataset_embedding_text")
    def test_returns_true_on_success(
        self, mock_build_text, mock_embed, mock_upsert
    ):
        from app.search.indexer import index_dataset

        dataset = _make_dataset()
        mock_build_text.return_value = "some embedding text"
        mock_embed.return_value = [0.1] * 1536

        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = dataset

        mock_client = MagicMock()

        result = index_dataset(dataset_id=1, db=mock_db, openai_client=mock_client)
        assert result is True

        # Should have called upsert with status='indexed' and the vector
        mock_upsert.assert_called_once()
        call_kwargs = mock_upsert.call_args
        assert call_kwargs[1]["status"] == "indexed"
        assert call_kwargs[1]["embedding"] == [0.1] * 1536

    @patch("app.search.indexer.embed_single")
    @patch("app.search.indexer.build_dataset_embedding_text")
    def test_returns_false_when_dataset_not_found(
        self, mock_build_text, mock_embed
    ):
        from app.search.indexer import index_dataset

        mock_db = MagicMock()
        mock_db.execute.return_value.scalar_one_or_none.return_value = None

        result = index_dataset(dataset_id=999, db=mock_db, openai_client=MagicMock())
        assert result is False

        # Should not have attempted to build text or embed
        mock_build_text.assert_not_called()
        mock_embed.assert_not_called()
