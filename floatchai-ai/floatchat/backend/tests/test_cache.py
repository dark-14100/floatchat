"""
Feature 2 — Redis cache layer tests.

Verifies cache hit/miss behaviour, size-limit enforcement, invalidation,
and the ``query_cache:{md5}`` key-pattern contract.

Requires:
    - Docker Redis running on port 6379
"""

import hashlib
from unittest.mock import MagicMock

import pytest

from app.cache.redis_cache import (
    CACHE_KEY_PREFIX,
    _make_cache_key,
    get_cached_result,
    invalidate_all_query_cache,
    set_cached_result,
)


# ============================================================================
# Cache key pattern
# ============================================================================
class TestCacheKeyPattern:
    """Cache keys must follow ``query_cache:{md5_of_sql}``."""

    def test_key_matches_md5(self):
        sql = "SELECT * FROM profiles WHERE latitude > 10"
        key = _make_cache_key(sql)
        expected = hashlib.md5(sql.encode("utf-8")).hexdigest()
        assert key == f"query_cache:{expected}"

    def test_prefix_constant(self):
        assert CACHE_KEY_PREFIX == "query_cache"

    def test_different_sql_produces_different_keys(self):
        k1 = _make_cache_key("SELECT 1")
        k2 = _make_cache_key("SELECT 2")
        assert k1 != k2


# ============================================================================
# Cache miss
# ============================================================================
def test_cache_miss_returns_none(redis_client):
    """A never-cached SQL string must return None."""
    result = get_cached_result("SELECT never_cached_query_xyz", redis_client)
    assert result is None


# ============================================================================
# Cache set → get round-trip
# ============================================================================
def test_set_then_get_returns_data(redis_client):
    """Storing a result and immediately reading it must round-trip correctly."""
    sql = "SELECT * FROM test_roundtrip_table"
    data = [{"id": 1, "value": "hello"}, {"id": 2, "value": "world"}]

    cached = set_cached_result(sql, data, redis_client)
    assert cached is True

    result = get_cached_result(sql, redis_client)
    assert result == data


def test_cached_result_preserves_types(redis_client):
    """Numeric and boolean values must survive JSON serialization."""
    sql = "SELECT * FROM type_check"
    data = [{"int_val": 42, "float_val": 3.14, "bool_val": True, "null_val": None}]

    set_cached_result(sql, data, redis_client)
    result = get_cached_result(sql, redis_client)

    assert result[0]["int_val"] == 42
    assert result[0]["float_val"] == pytest.approx(3.14)
    assert result[0]["bool_val"] is True
    assert result[0]["null_val"] is None


# ============================================================================
# Large result NOT cached
# ============================================================================
def test_large_result_not_cached(redis_client, monkeypatch):
    """Results exceeding REDIS_CACHE_MAX_ROWS must NOT be cached."""
    mock_settings = MagicMock()
    mock_settings.REDIS_CACHE_MAX_ROWS = 5
    mock_settings.REDIS_CACHE_TTL_SECONDS = 300
    monkeypatch.setattr("app.cache.redis_cache.get_settings", lambda: mock_settings)

    sql = "SELECT * FROM large_table"
    large_data = [{"row": i} for i in range(6)]  # 6 > max of 5

    cached = set_cached_result(sql, large_data, redis_client)
    assert cached is False

    # Nothing should have been stored
    result = get_cached_result(sql, redis_client)
    assert result is None


def test_exact_max_rows_is_cached(redis_client, monkeypatch):
    """A result with exactly REDIS_CACHE_MAX_ROWS rows should still be cached."""
    mock_settings = MagicMock()
    mock_settings.REDIS_CACHE_MAX_ROWS = 5
    mock_settings.REDIS_CACHE_TTL_SECONDS = 300
    monkeypatch.setattr("app.cache.redis_cache.get_settings", lambda: mock_settings)

    sql = "SELECT * FROM exact_max"
    data = [{"row": i} for i in range(5)]  # exactly 5

    cached = set_cached_result(sql, data, redis_client)
    assert cached is True


# ============================================================================
# Cache invalidation
# ============================================================================
def test_invalidate_all_deletes_keys(redis_client):
    """invalidate_all_query_cache must delete every ``query_cache:*`` key."""
    redis_client.set("query_cache:aaa", b"1", ex=60)
    redis_client.set("query_cache:bbb", b"2", ex=60)
    redis_client.set("query_cache:ccc", b"3", ex=60)

    deleted = invalidate_all_query_cache(redis_client)
    assert deleted >= 3

    remaining = redis_client.keys("query_cache:*")
    assert len(remaining) == 0


def test_invalidate_returns_zero_when_empty(redis_client):
    """Invalidating an empty cache should return 0 without error."""
    # Ensure no keys exist
    for key in redis_client.keys("query_cache:*"):
        redis_client.delete(key)

    deleted = invalidate_all_query_cache(redis_client)
    assert deleted == 0


def test_invalidate_does_not_touch_non_cache_keys(redis_client):
    """Non-query_cache keys must survive invalidation."""
    redis_client.set("other_key:important", b"keep_me", ex=120)
    redis_client.set("query_cache:delete_me", b"bye", ex=60)

    invalidate_all_query_cache(redis_client)

    assert redis_client.get("other_key:important") == b"keep_me"
    # Clean up
    redis_client.delete("other_key:important")
