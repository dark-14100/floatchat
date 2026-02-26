"""
FloatChat Redis Query Cache

Caches NL query results in Redis with a configurable TTL.
Cache keys follow the pattern: query_cache:{md5_hash_of_sql_string}

Rules:
    - Results larger than REDIS_CACHE_MAX_ROWS are never cached.
    - Cache is invalidated by deleting all query_cache:* keys after ingestion.
    - All operations are logged via structlog.
"""

import hashlib
import json
from typing import Any, Optional

import structlog
from redis import Redis

from app.config import get_settings

logger = structlog.get_logger(__name__)

CACHE_KEY_PREFIX = "query_cache"


def _make_cache_key(sql_string: str) -> str:
    """Build a deterministic cache key from a SQL string."""
    md5_hash = hashlib.md5(sql_string.encode("utf-8")).hexdigest()
    return f"{CACHE_KEY_PREFIX}:{md5_hash}"


def get_cached_result(sql_string: str, redis_client: Redis) -> Optional[list[dict]]:
    """
    Look up a cached query result.

    Args:
        sql_string: The exact SQL query string used as cache key source.
        redis_client: An active Redis client instance.

    Returns:
        The deserialized list of dicts on cache hit, or ``None`` on miss.
    """
    key = _make_cache_key(sql_string)
    try:
        raw = redis_client.get(key)
    except Exception:
        logger.warning("redis_get_error", key=key, exc_info=True)
        return None

    if raw is None:
        logger.debug("cache_miss", key=key)
        return None

    logger.debug("cache_hit", key=key)
    return json.loads(raw)


def set_cached_result(
    sql_string: str,
    result: list[dict],
    redis_client: Redis,
) -> bool:
    """
    Store a query result in the cache.

    The result is only cached when ``len(result) <= REDIS_CACHE_MAX_ROWS``.
    TTL is set to ``REDIS_CACHE_TTL_SECONDS`` from application settings.

    Args:
        sql_string: The exact SQL query string used as cache key source.
        result: The query result rows (list of plain dicts).
        redis_client: An active Redis client instance.

    Returns:
        ``True`` if the result was cached, ``False`` if skipped or on error.
    """
    settings = get_settings()

    if len(result) > settings.REDIS_CACHE_MAX_ROWS:
        logger.debug(
            "cache_skip_too_large",
            rows=len(result),
            max_rows=settings.REDIS_CACHE_MAX_ROWS,
        )
        return False

    key = _make_cache_key(sql_string)
    try:
        redis_client.set(
            key,
            json.dumps(result),
            ex=settings.REDIS_CACHE_TTL_SECONDS,
        )
        logger.debug("cache_set", key=key, rows=len(result), ttl=settings.REDIS_CACHE_TTL_SECONDS)
        return True
    except Exception:
        logger.warning("redis_set_error", key=key, exc_info=True)
        return False


def invalidate_all_query_cache(redis_client: Redis) -> int:
    """
    Delete every ``query_cache:*`` key in Redis.

    Args:
        redis_client: An active Redis client instance.

    Returns:
        The number of keys deleted.
    """
    pattern = f"{CACHE_KEY_PREFIX}:*"
    try:
        keys = redis_client.keys(pattern)
        if not keys:
            logger.info("cache_invalidate", deleted=0)
            return 0
        count = redis_client.delete(*keys)
        logger.info("cache_invalidate", deleted=count)
        return count
    except Exception:
        logger.warning("redis_invalidate_error", exc_info=True)
        return 0
