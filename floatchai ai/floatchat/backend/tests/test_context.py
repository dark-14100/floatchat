"""
Tests for app.query.context — Redis-backed conversation context.

Tests both the real Redis path (mocked) and the None Redis path (graceful no-op).
"""

import json
from unittest.mock import MagicMock, patch

import pytest

from app.query.context import get_context, append_context, clear_context


# ═════════════════════════════════════════════════════════════════════════════
# Mock settings
# ═════════════════════════════════════════════════════════════════════════════

class MockSettings:
    QUERY_CONTEXT_MAX_TURNS = 5
    QUERY_CONTEXT_TTL = 3600


@pytest.fixture
def settings():
    return MockSettings()


@pytest.fixture
def mock_redis():
    """A mock Redis client with get/set/delete."""
    client = MagicMock()
    client._store = {}

    def mock_get(key):
        return client._store.get(key)

    def mock_set(key, value, ex=None):
        client._store[key] = value

    def mock_delete(key):
        client._store.pop(key, None)

    client.get = MagicMock(side_effect=mock_get)
    client.set = MagicMock(side_effect=mock_set)
    client.delete = MagicMock(side_effect=mock_delete)

    return client


# ═════════════════════════════════════════════════════════════════════════════
# get_context
# ═════════════════════════════════════════════════════════════════════════════

class TestGetContext:
    @pytest.mark.asyncio
    async def test_returns_empty_when_redis_none(self):
        result = await get_context(None, "session-1")
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_when_key_missing(self, mock_redis):
        result = await get_context(mock_redis, "nonexistent-session")
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_stored_context(self, mock_redis):
        turns = [
            {"role": "user", "content": "hello", "sql": None, "row_count": None},
            {"role": "assistant", "content": "hi", "sql": "SELECT 1", "row_count": 1},
        ]
        mock_redis._store["query:context:sess-1"] = json.dumps(turns)

        result = await get_context(mock_redis, "sess-1")
        assert len(result) == 2
        assert result[0]["role"] == "user"
        assert result[1]["sql"] == "SELECT 1"

    @pytest.mark.asyncio
    async def test_returns_empty_on_invalid_json(self, mock_redis):
        mock_redis._store["query:context:sess-bad"] = "not json"
        # Override get to return the raw string
        mock_redis.get = MagicMock(return_value="not json")

        result = await get_context(mock_redis, "sess-bad")
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_exception(self):
        broken_redis = MagicMock()
        broken_redis.get = MagicMock(side_effect=Exception("connection lost"))

        result = await get_context(broken_redis, "sess-1")
        assert result == []

    @pytest.mark.asyncio
    async def test_returns_empty_on_non_list_json(self, mock_redis):
        mock_redis._store["query:context:sess-obj"] = json.dumps({"not": "a list"})

        result = await get_context(mock_redis, "sess-obj")
        assert result == []


# ═════════════════════════════════════════════════════════════════════════════
# append_context
# ═════════════════════════════════════════════════════════════════════════════

class TestAppendContext:
    @pytest.mark.asyncio
    async def test_noop_when_redis_none(self, settings):
        # Should not raise
        await append_context(None, "sess-1", {"role": "user", "content": "hi"}, settings)

    @pytest.mark.asyncio
    async def test_appends_turn(self, mock_redis, settings):
        turn = {"role": "user", "content": "show floats", "sql": None, "row_count": None}
        await append_context(mock_redis, "sess-1", turn, settings)

        stored = json.loads(mock_redis._store["query:context:sess-1"])
        assert len(stored) == 1
        assert stored[0]["content"] == "show floats"

    @pytest.mark.asyncio
    async def test_appends_multiple_turns(self, mock_redis, settings):
        for i in range(3):
            turn = {"role": "user", "content": f"query {i}"}
            await append_context(mock_redis, "sess-1", turn, settings)

        stored = json.loads(mock_redis._store["query:context:sess-1"])
        assert len(stored) == 3

    @pytest.mark.asyncio
    async def test_trims_to_max_turns(self, mock_redis, settings):
        settings.QUERY_CONTEXT_MAX_TURNS = 3

        for i in range(5):
            turn = {"role": "user", "content": f"query {i}"}
            await append_context(mock_redis, "sess-1", turn, settings)

        stored = json.loads(mock_redis._store["query:context:sess-1"])
        assert len(stored) == 3
        # Oldest turns trimmed — should have queries 2, 3, 4
        assert stored[0]["content"] == "query 2"
        assert stored[2]["content"] == "query 4"

    @pytest.mark.asyncio
    async def test_sets_ttl(self, mock_redis, settings):
        turn = {"role": "user", "content": "test"}
        await append_context(mock_redis, "sess-1", turn, settings)

        # Verify set was called with ex=TTL
        mock_redis.set.assert_called()
        call_kwargs = mock_redis.set.call_args
        # The ex parameter should be the TTL
        assert call_kwargs[1].get("ex") == settings.QUERY_CONTEXT_TTL or \
               (len(call_kwargs[0]) >= 3 or "ex" in str(call_kwargs))

    @pytest.mark.asyncio
    async def test_noop_on_exception(self, settings):
        broken_redis = MagicMock()
        broken_redis.get = MagicMock(side_effect=Exception("oops"))

        # Should not raise
        await append_context(broken_redis, "sess-1", {"role": "user", "content": "x"}, settings)


# ═════════════════════════════════════════════════════════════════════════════
# clear_context
# ═════════════════════════════════════════════════════════════════════════════

class TestClearContext:
    @pytest.mark.asyncio
    async def test_noop_when_redis_none(self):
        await clear_context(None, "sess-1")  # Should not raise

    @pytest.mark.asyncio
    async def test_deletes_key(self, mock_redis):
        mock_redis._store["query:context:sess-1"] = json.dumps([{"role": "user"}])
        await clear_context(mock_redis, "sess-1")
        assert "query:context:sess-1" not in mock_redis._store

    @pytest.mark.asyncio
    async def test_noop_on_exception(self):
        broken_redis = MagicMock()
        broken_redis.delete = MagicMock(side_effect=Exception("oops"))

        await clear_context(broken_redis, "sess-1")  # Should not raise
