"""
Tests for app.chat.suggestions and app.chat.follow_ups modules.

Covers:
  - generate_load_time_suggestions: caching, dataset-based, fallbacks
  - _build_suggestions_from_datasets: variety (spatial, temporal, variable)
  - generate_follow_up_suggestions: LLM call, parsing, error handling
  - _parse_suggestions: JSON array, code blocks, plain text, failures
"""

import json
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from app.chat.suggestions import (
    generate_load_time_suggestions,
    _build_suggestions_from_datasets,
    _FALLBACK_SUGGESTIONS,
    _CACHE_KEY,
)
from app.chat.follow_ups import (
    generate_follow_up_suggestions,
    _parse_suggestions,
)


# ═════════════════════════════════════════════════════════════════════════════
# Mock settings
# ═════════════════════════════════════════════════════════════════════════════

class MockSettings:
    CHAT_SUGGESTIONS_CACHE_TTL_SECONDS = 3600
    CHAT_SUGGESTIONS_COUNT = 6
    QUERY_LLM_PROVIDER = "deepseek"
    QUERY_LLM_MODEL = "deepseek-reasoner"
    FOLLOW_UP_LLM_TEMPERATURE = 0.7
    FOLLOW_UP_LLM_MAX_TOKENS = 150
    DEEPSEEK_API_KEY = "sk-test"
    DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"


@pytest.fixture
def settings():
    return MockSettings()


@pytest.fixture
def mock_redis():
    """Mock Redis client with in-memory store."""
    client = MagicMock()
    client._store = {}

    def mock_get(key):
        return client._store.get(key)

    def mock_setex(key, ttl, value):
        client._store[key] = value

    client.get = MagicMock(side_effect=mock_get)
    client.setex = MagicMock(side_effect=mock_setex)

    return client


@pytest.fixture
def mock_db():
    """Mock SQLAlchemy session."""
    return MagicMock()


# Sample dataset summaries
SAMPLE_SUMMARIES = [
    {
        "name": "Argo Core",
        "variable_list": ["temperature", "salinity", "pressure"],
        "date_range_start": "2020-01-01",
        "date_range_end": "2025-06-01",
        "float_count": 4000,
    },
    {
        "name": "BGC Argo",
        "variable_list": ["chlorophyll", "oxygen"],
        "date_range_start": "2021-03-15",
        "date_range_end": "2025-05-20",
        "float_count": 500,
    },
]


# ═════════════════════════════════════════════════════════════════════════════
# generate_load_time_suggestions
# ═════════════════════════════════════════════════════════════════════════════

class TestGenerateLoadTimeSuggestions:

    @patch("app.chat.suggestions.get_all_summaries")
    def test_returns_suggestions_from_dataset_metadata(
        self, mock_summaries, mock_db, mock_redis, settings
    ):
        mock_summaries.return_value = SAMPLE_SUMMARIES

        result = generate_load_time_suggestions(mock_db, mock_redis, settings)

        assert isinstance(result, list)
        assert 4 <= len(result) <= 6
        for item in result:
            assert "query" in item
            assert "description" in item

    @patch("app.chat.suggestions.get_all_summaries")
    def test_caches_in_redis(self, mock_summaries, mock_db, mock_redis, settings):
        mock_summaries.return_value = SAMPLE_SUMMARIES

        generate_load_time_suggestions(mock_db, mock_redis, settings)

        # Should have called setex (cache write)
        mock_redis.setex.assert_called_once()
        call_args = mock_redis.setex.call_args
        assert call_args[0][0] == _CACHE_KEY
        assert call_args[0][1] == 3600  # TTL

    @patch("app.chat.suggestions.get_all_summaries")
    def test_returns_cached_if_available(
        self, mock_summaries, mock_db, mock_redis, settings
    ):
        cached = [{"query": "cached q", "description": "cached d"}]
        mock_redis._store[_CACHE_KEY] = json.dumps(cached)

        result = generate_load_time_suggestions(mock_db, mock_redis, settings)

        assert result == cached
        # get_all_summaries should NOT be called when cache is hit
        mock_summaries.assert_not_called()

    @patch("app.chat.suggestions.get_all_summaries")
    def test_returns_fallbacks_when_no_datasets(
        self, mock_summaries, mock_db, mock_redis, settings
    ):
        mock_summaries.return_value = []

        result = generate_load_time_suggestions(mock_db, mock_redis, settings)

        assert result == _FALLBACK_SUGGESTIONS

    @patch("app.chat.suggestions.get_all_summaries")
    def test_returns_fallbacks_when_summaries_raise(
        self, mock_summaries, mock_db, mock_redis, settings
    ):
        mock_summaries.side_effect = Exception("DB error")

        result = generate_load_time_suggestions(mock_db, mock_redis, settings)

        assert result == _FALLBACK_SUGGESTIONS

    @patch("app.chat.suggestions.get_all_summaries")
    def test_works_without_redis(self, mock_summaries, mock_db, settings):
        mock_summaries.return_value = SAMPLE_SUMMARIES

        result = generate_load_time_suggestions(mock_db, None, settings)

        assert isinstance(result, list)
        assert len(result) >= 4

    @patch("app.chat.suggestions.get_all_summaries")
    def test_redis_get_error_falls_through(
        self, mock_summaries, mock_db, mock_redis, settings
    ):
        """If Redis get raises, we fall through to building from datasets."""
        mock_redis.get.side_effect = Exception("Redis down")
        mock_summaries.return_value = SAMPLE_SUMMARIES

        result = generate_load_time_suggestions(mock_db, mock_redis, settings)

        assert len(result) >= 4
        mock_summaries.assert_called_once()


# ═════════════════════════════════════════════════════════════════════════════
# _build_suggestions_from_datasets
# ═════════════════════════════════════════════════════════════════════════════

class TestBuildSuggestionsFromDatasets:
    def test_returns_4_to_6_suggestions(self, settings):
        result = _build_suggestions_from_datasets(SAMPLE_SUMMARIES, settings)
        assert 4 <= len(result) <= 6

    def test_includes_spatial_query(self, settings):
        result = _build_suggestions_from_datasets(SAMPLE_SUMMARIES, settings)
        # First suggestion should be spatial (mentions region)
        queries_lower = " ".join(s["query"].lower() for s in result)
        assert "atlantic" in queries_lower or "pacific" in queries_lower or "ocean" in queries_lower

    def test_includes_temporal_query(self, settings):
        result = _build_suggestions_from_datasets(SAMPLE_SUMMARIES, settings)
        queries_lower = " ".join(s["query"].lower() for s in result)
        assert "2020" in queries_lower or "2025" in queries_lower

    def test_includes_variable_specific_query(self, settings):
        result = _build_suggestions_from_datasets(SAMPLE_SUMMARIES, settings)
        queries_lower = " ".join(s["query"].lower() for s in result)
        assert "temperature" in queries_lower or "salinity" in queries_lower

    def test_handles_single_dataset(self, settings):
        single = [SAMPLE_SUMMARIES[0]]
        result = _build_suggestions_from_datasets(single, settings)
        assert len(result) >= 4

    def test_handles_dataset_without_variables(self, settings):
        no_vars = [{"name": "Empty DS", "variable_list": [], "float_count": 10}]
        result = _build_suggestions_from_datasets(no_vars, settings)
        assert len(result) >= 4

    def test_respects_count_setting(self):
        class SmallSettings:
            CHAT_SUGGESTIONS_COUNT = 3
        result = _build_suggestions_from_datasets(SAMPLE_SUMMARIES, SmallSettings())
        assert len(result) <= 3

    def test_uses_two_datasets_for_comparison(self, settings):
        result = _build_suggestions_from_datasets(SAMPLE_SUMMARIES, settings)
        queries_lower = " ".join(s["query"].lower() for s in result)
        # With 2 datasets, should generate a comparison suggestion
        assert "compare" in queries_lower or "bgc" in queries_lower.lower()


# ═════════════════════════════════════════════════════════════════════════════
# generate_follow_up_suggestions
# ═════════════════════════════════════════════════════════════════════════════

class TestGenerateFollowUpSuggestions:

    @patch("app.chat.follow_ups._get_model", return_value="deepseek-reasoner")
    @patch("app.chat.follow_ups.get_llm_client")
    @pytest.mark.asyncio
    async def test_returns_2_to_3_suggestions(self, mock_client_fn, mock_model, settings):
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client

        # Mock LLM response
        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = json.dumps([
            "What about salinity at this depth?",
            "How does this vary seasonally?",
        ])
        mock_client.chat.completions.create.return_value = mock_response

        result = await generate_follow_up_suggestions(
            nl_query="Show temperature at 500m",
            sql="SELECT temp FROM profiles WHERE depth = 500",
            column_names=["temp"],
            row_count=42,
            settings=settings,
        )

        assert isinstance(result, list)
        assert 2 <= len(result) <= 3
        assert all(isinstance(s, str) for s in result)

    @patch("app.chat.follow_ups._get_model", return_value="deepseek-reasoner")
    @patch("app.chat.follow_ups.get_llm_client")
    @pytest.mark.asyncio
    async def test_returns_empty_on_llm_failure(self, mock_client_fn, mock_model, settings):
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client
        mock_client.chat.completions.create.side_effect = Exception("API error")

        result = await generate_follow_up_suggestions(
            nl_query="test", sql="SELECT 1",
            column_names=["x"], row_count=1, settings=settings,
        )

        assert result == []

    @patch("app.chat.follow_ups.get_llm_client")
    @pytest.mark.asyncio
    async def test_returns_empty_on_invalid_provider(self, mock_client_fn, settings):
        mock_client_fn.side_effect = ValueError("Unknown provider")

        result = await generate_follow_up_suggestions(
            nl_query="test", sql="SELECT 1",
            column_names=["x"], row_count=1, settings=settings,
        )

        assert result == []

    @patch("app.chat.follow_ups._get_model", return_value="deepseek-reasoner")
    @patch("app.chat.follow_ups.get_llm_client")
    @pytest.mark.asyncio
    async def test_handles_empty_llm_response(self, mock_client_fn, mock_model, settings):
        mock_client = MagicMock()
        mock_client_fn.return_value = mock_client

        mock_response = MagicMock()
        mock_response.choices = [MagicMock()]
        mock_response.choices[0].message.content = ""
        mock_client.chat.completions.create.return_value = mock_response

        result = await generate_follow_up_suggestions(
            nl_query="test", sql="SELECT 1",
            column_names=["x"], row_count=1, settings=settings,
        )

        assert result == []


# ═════════════════════════════════════════════════════════════════════════════
# _parse_suggestions
# ═════════════════════════════════════════════════════════════════════════════

class TestParseSuggestions:
    def test_parses_json_array(self):
        content = '["Question one?", "Question two?"]'
        result = _parse_suggestions(content)
        assert len(result) == 2
        assert result[0] == "Question one?"
        assert result[1] == "Question two?"

    def test_parses_json_in_code_block(self):
        content = '```json\n["What about salinity?", "How deep?"]\n```'
        result = _parse_suggestions(content)
        assert len(result) == 2

    def test_parses_plain_text_questions(self):
        content = "1. What is the average salinity here?\n2. How does temperature vary by depth?\n3. Are there seasonal patterns?"
        result = _parse_suggestions(content)
        assert len(result) >= 2
        assert all(s.endswith("?") for s in result)

    def test_limits_to_3_suggestions(self):
        content = json.dumps([
            "Q1?", "Q2?", "Q3?", "Q4?", "Q5?",
        ])
        result = _parse_suggestions(content)
        assert len(result) <= 3

    def test_returns_empty_on_garbage(self):
        content = "this is not a question at all and has no structure"
        result = _parse_suggestions(content)
        assert result == []

    def test_filters_non_string_elements(self):
        content = json.dumps(["Valid question?", 42, None, "Another question?"])
        result = _parse_suggestions(content)
        # Only string elements should survive
        assert all(isinstance(s, str) for s in result)
        assert len(result) == 2

    def test_empty_string_returns_empty(self):
        result = _parse_suggestions("")
        assert result == []

    def test_strips_whitespace(self):
        content = json.dumps(["  How deep is the ocean?  ", "  What about salinity? "])
        result = _parse_suggestions(content)
        assert result[0] == "How deep is the ocean?"
        assert result[1] == "What about salinity?"

    def test_code_block_without_json_label(self):
        content = '```\n["Question A?", "Question B?"]\n```'
        result = _parse_suggestions(content)
        assert len(result) == 2
