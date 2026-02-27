"""
Tests for app.query.pipeline — LLM orchestration pipeline.

All LLM calls are mocked — no real API keys required.
"""

import json
from dataclasses import dataclass
from unittest.mock import MagicMock, patch, AsyncMock

import pytest

from app.query.pipeline import (
    PipelineResult,
    get_llm_client,
    nl_to_sql,
    interpret_results,
    _extract_sql,
    _build_messages,
    _get_model,
    _PROVIDER_CONFIG,
)


# ═════════════════════════════════════════════════════════════════════════════
# Mock settings
# ═════════════════════════════════════════════════════════════════════════════

class MockSettings:
    QUERY_LLM_PROVIDER = "deepseek"
    QUERY_LLM_MODEL = "deepseek-reasoner"
    QUERY_LLM_TEMPERATURE = 0.0
    QUERY_LLM_MAX_TOKENS = 2048
    QUERY_MAX_RETRIES = 3
    DEEPSEEK_API_KEY = "sk-test-deepseek"
    DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
    QWEN_API_KEY = "sk-test-qwen"
    QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    GEMMA_API_KEY = "sk-test-gemma"
    GEMMA_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
    OPENAI_API_KEY = "sk-test-openai"


class MockSettingsNoKeys:
    QUERY_LLM_PROVIDER = "deepseek"
    QUERY_LLM_MODEL = "deepseek-reasoner"
    QUERY_LLM_TEMPERATURE = 0.0
    QUERY_LLM_MAX_TOKENS = 2048
    QUERY_MAX_RETRIES = 3
    DEEPSEEK_API_KEY = None
    DEEPSEEK_BASE_URL = "https://api.deepseek.com/v1"
    QWEN_API_KEY = None
    QWEN_BASE_URL = "https://dashscope.aliyuncs.com/compatible-mode/v1"
    GEMMA_API_KEY = None
    GEMMA_BASE_URL = "https://generativelanguage.googleapis.com/v1beta/openai"
    OPENAI_API_KEY = None


@pytest.fixture
def settings():
    return MockSettings()


@pytest.fixture
def settings_no_keys():
    return MockSettingsNoKeys()


# ═════════════════════════════════════════════════════════════════════════════
# _extract_sql
# ═════════════════════════════════════════════════════════════════════════════

class TestExtractSql:
    def test_extract_from_code_block(self):
        response = "Here's the query:\n```sql\nSELECT * FROM floats LIMIT 10;\n```"
        assert _extract_sql(response) == "SELECT * FROM floats LIMIT 10;"

    def test_extract_from_code_block_multiline(self):
        response = """```sql
SELECT f.platform_number, COUNT(p.profile_id) AS cnt
FROM floats f
JOIN profiles p ON p.float_id = f.float_id
GROUP BY f.platform_number
LIMIT 1000;
```"""
        sql = _extract_sql(response)
        assert sql is not None
        assert "SELECT" in sql
        assert "GROUP BY" in sql

    def test_extract_raw_select(self):
        response = "SELECT * FROM floats LIMIT 10"
        sql = _extract_sql(response)
        assert sql is not None
        assert "SELECT" in sql

    def test_extract_raw_with_cte(self):
        response = "WITH top AS (SELECT 1) SELECT * FROM top"
        sql = _extract_sql(response)
        assert sql is not None
        assert "WITH" in sql

    def test_returns_none_for_no_sql(self):
        response = "I don't understand your question."
        sql = _extract_sql(response)
        assert sql is None

    def test_empty_response(self):
        assert _extract_sql("") is None

    def test_code_block_preferred_over_raw(self):
        response = "SELECT 1\n\n```sql\nSELECT * FROM floats\n```"
        sql = _extract_sql(response)
        assert sql == "SELECT * FROM floats"


# ═════════════════════════════════════════════════════════════════════════════
# get_llm_client
# ═════════════════════════════════════════════════════════════════════════════

class TestGetLlmClient:
    @patch("app.query.pipeline.OpenAI")
    def test_deepseek_client(self, mock_openai_cls, settings):
        get_llm_client("deepseek", settings)
        mock_openai_cls.assert_called_once_with(
            api_key="sk-test-deepseek",
            base_url="https://api.deepseek.com/v1",
        )

    @patch("app.query.pipeline.OpenAI")
    def test_qwen_client(self, mock_openai_cls, settings):
        get_llm_client("qwen", settings)
        mock_openai_cls.assert_called_once_with(
            api_key="sk-test-qwen",
            base_url="https://dashscope.aliyuncs.com/compatible-mode/v1",
        )

    @patch("app.query.pipeline.OpenAI")
    def test_gemma_client(self, mock_openai_cls, settings):
        get_llm_client("gemma", settings)
        mock_openai_cls.assert_called_once_with(
            api_key="sk-test-gemma",
            base_url="https://generativelanguage.googleapis.com/v1beta/openai",
        )

    @patch("app.query.pipeline.OpenAI")
    def test_openai_client(self, mock_openai_cls, settings):
        get_llm_client("openai", settings)
        mock_openai_cls.assert_called_once_with(api_key="sk-test-openai")

    def test_unknown_provider_raises(self, settings):
        with pytest.raises(ValueError, match="Unknown LLM provider"):
            get_llm_client("claude", settings)

    def test_missing_api_key_raises(self, settings_no_keys):
        with pytest.raises(ValueError, match="API key not configured"):
            get_llm_client("deepseek", settings_no_keys)

    @patch("app.query.pipeline.OpenAI")
    def test_case_insensitive(self, mock_openai_cls, settings):
        get_llm_client("DeepSeek", settings)
        mock_openai_cls.assert_called_once()


# ═════════════════════════════════════════════════════════════════════════════
# _get_model
# ═════════════════════════════════════════════════════════════════════════════

class TestGetModel:
    def test_override_takes_precedence(self, settings):
        assert _get_model("deepseek", "my-custom-model", settings) == "my-custom-model"

    def test_default_provider_uses_settings_model(self, settings):
        assert _get_model("deepseek", None, settings) == "deepseek-reasoner"

    def test_different_provider_uses_provider_default(self, settings):
        assert _get_model("qwen", None, settings) == "qwq-32b"

    def test_gemma_default(self, settings):
        assert _get_model("gemma", None, settings) == "gemma3"

    def test_openai_default(self, settings):
        assert _get_model("openai", None, settings) == "gpt-4o"


# ═════════════════════════════════════════════════════════════════════════════
# _build_messages
# ═════════════════════════════════════════════════════════════════════════════

class TestBuildMessages:
    def test_basic_query(self):
        msgs = _build_messages("Show all floats", [], None)
        assert msgs[0]["role"] == "system"
        assert msgs[-1]["role"] == "user"
        assert msgs[-1]["content"] == "Show all floats"

    def test_with_geography(self):
        geo = {"name": "arabian sea", "lat_min": 0, "lat_max": 25, "lon_min": 45, "lon_max": 78}
        msgs = _build_messages("floats in arabian sea", [], geo)
        # Should have system, geography system, user
        assert len(msgs) == 3
        assert "arabian sea" in msgs[1]["content"].lower()

    def test_with_context(self):
        context = [
            {"role": "user", "content": "show floats"},
            {"role": "assistant", "content": "Here are floats", "sql": "SELECT * FROM floats"},
        ]
        msgs = _build_messages("now filter by BGC", context, None)
        # system + 2 context turns + user
        assert len(msgs) == 4
        assert "SELECT * FROM floats" in msgs[2]["content"]

    def test_with_validation_error(self):
        msgs = _build_messages("show floats", [], None, validation_error="Table not found")
        user_msg = msgs[-1]["content"]
        assert "[RETRY]" in user_msg
        assert "Table not found" in user_msg


# ═════════════════════════════════════════════════════════════════════════════
# nl_to_sql (mocked LLM)
# ═════════════════════════════════════════════════════════════════════════════

class TestNlToSql:
    def _mock_llm_response(self, content):
        """Create a mock OpenAI chat completion response."""
        mock_message = MagicMock()
        mock_message.content = content
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        return mock_response

    @pytest.mark.asyncio
    @patch("app.query.pipeline.get_llm_client")
    async def test_successful_pipeline(self, mock_get_client, settings):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = self._mock_llm_response(
            "```sql\nSELECT * FROM floats LIMIT 10\n```"
        )
        mock_get_client.return_value = mock_client

        result = await nl_to_sql("Show all floats", [], None, settings)

        assert result.sql == "SELECT * FROM floats LIMIT 10"
        assert result.error is None
        assert result.retries_used == 0
        assert result.provider == "deepseek"

    @pytest.mark.asyncio
    @patch("app.query.pipeline.get_llm_client")
    async def test_retry_on_extraction_failure(self, mock_get_client, settings):
        mock_client = MagicMock()
        # First call: no SQL, second call: valid SQL
        mock_client.chat.completions.create.side_effect = [
            self._mock_llm_response("I don't know how to help"),
            self._mock_llm_response("```sql\nSELECT * FROM floats\n```"),
        ]
        mock_get_client.return_value = mock_client

        result = await nl_to_sql("Show floats", [], None, settings)

        assert result.sql == "SELECT * FROM floats"
        assert result.retries_used == 1
        assert len(result.validation_errors) == 1

    @pytest.mark.asyncio
    @patch("app.query.pipeline.get_llm_client")
    async def test_retry_on_validation_failure(self, mock_get_client, settings):
        mock_client = MagicMock()
        # First: invalid SQL (references bad table), second: valid SQL
        mock_client.chat.completions.create.side_effect = [
            self._mock_llm_response("```sql\nSELECT * FROM evil_table\n```"),
            self._mock_llm_response("```sql\nSELECT * FROM floats\n```"),
        ]
        mock_get_client.return_value = mock_client

        result = await nl_to_sql("Show data", [], None, settings)

        assert result.sql == "SELECT * FROM floats"
        assert result.retries_used == 1

    @pytest.mark.asyncio
    @patch("app.query.pipeline.get_llm_client")
    async def test_exhausted_retries(self, mock_get_client, settings):
        settings.QUERY_MAX_RETRIES = 2
        mock_client = MagicMock()
        # All attempts return invalid SQL
        mock_client.chat.completions.create.return_value = self._mock_llm_response(
            "```sql\nDELETE FROM floats\n```"
        )
        mock_get_client.return_value = mock_client

        result = await nl_to_sql("Delete everything", [], None, settings)

        assert result.sql is None
        assert result.error is not None
        assert "failed after" in result.error.lower()
        assert result.retries_used == 2

    @pytest.mark.asyncio
    async def test_missing_api_key_returns_error(self, settings_no_keys):
        result = await nl_to_sql("Show floats", [], None, settings_no_keys)
        assert result.sql is None
        assert result.error is not None
        assert "API key" in result.error

    @pytest.mark.asyncio
    @patch("app.query.pipeline.get_llm_client")
    async def test_llm_exception_returns_error(self, mock_get_client, settings):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("rate limited")
        mock_get_client.return_value = mock_client

        result = await nl_to_sql("Show floats", [], None, settings)

        assert result.sql is None
        assert "rate limited" in result.error

    @pytest.mark.asyncio
    @patch("app.query.pipeline.get_llm_client")
    async def test_provider_override(self, mock_get_client, settings):
        mock_client = MagicMock()
        mock_client.chat.completions.create.return_value = self._mock_llm_response(
            "```sql\nSELECT 1\n```"
        )
        mock_get_client.return_value = mock_client

        result = await nl_to_sql(
            "Show floats", [], None, settings, provider="qwen", model="qwq-32b"
        )

        assert result.provider == "qwen"
        assert result.model == "qwq-32b"


# ═════════════════════════════════════════════════════════════════════════════
# interpret_results (mocked LLM)
# ═════════════════════════════════════════════════════════════════════════════

class TestInterpretResults:
    @pytest.mark.asyncio
    @patch("app.query.pipeline.get_llm_client")
    async def test_successful_interpretation(self, mock_get_client, settings):
        mock_client = MagicMock()
        mock_message = MagicMock()
        mock_message.content = "The query found 5 BGC floats deployed by India."
        mock_choice = MagicMock()
        mock_choice.message = mock_message
        mock_response = MagicMock()
        mock_response.choices = [mock_choice]
        mock_client.chat.completions.create.return_value = mock_response
        mock_get_client.return_value = mock_client

        result = await interpret_results(
            query="Show BGC floats",
            sql="SELECT * FROM floats WHERE float_type = 'BGC'",
            columns=["platform_number", "float_type"],
            rows=[{"platform_number": "F001", "float_type": "BGC"}],
            row_count=5,
            settings=settings,
        )

        assert "BGC" in result or "found" in result.lower()

    @pytest.mark.asyncio
    @patch("app.query.pipeline.get_llm_client")
    async def test_fallback_on_llm_failure(self, mock_get_client, settings):
        mock_client = MagicMock()
        mock_client.chat.completions.create.side_effect = Exception("timeout")
        mock_get_client.return_value = mock_client

        result = await interpret_results(
            query="Show floats",
            sql="SELECT * FROM floats",
            columns=["platform_number"],
            rows=[],
            row_count=0,
            settings=settings,
        )

        assert "no results" in result.lower() or "0" in result

    @pytest.mark.asyncio
    async def test_fallback_on_missing_key(self, settings_no_keys):
        result = await interpret_results(
            query="Show floats",
            sql="SELECT * FROM floats",
            columns=["platform_number", "float_type"],
            rows=[{"platform_number": "F001", "float_type": "core"}],
            row_count=1,
            settings=settings_no_keys,
        )

        assert "1 row" in result


# ═════════════════════════════════════════════════════════════════════════════
# PipelineResult dataclass
# ═════════════════════════════════════════════════════════════════════════════

class TestPipelineResult:
    def test_defaults(self):
        r = PipelineResult()
        assert r.sql is None
        assert r.error is None
        assert r.retries_used == 0
        assert r.validation_errors == []
        assert r.provider == ""
        assert r.model == ""
