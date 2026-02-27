"""
FloatChat NL Query Engine — Conversation Context

Redis-backed session context for multi-turn NL query conversations.
All functions accept an Optional[Redis] client — if None, they gracefully
no-op or return empty lists.  This ensures the query engine never blocks
on Redis unavailability (Gap 6 resolution).

Context is stored ONLY by the API layer after execution completes, not by
the pipeline (Gap 3 resolution).

Key format:  query:context:{session_id}
Storage:     JSON-encoded list of turn dicts in a single Redis string key.
"""

import json
from typing import Optional

import structlog
from redis import Redis

log = structlog.get_logger(__name__)


# ── Turn schema ─────────────────────────────────────────────────────────────
# Each turn dict:
# {
#     "role": "user" | "assistant",
#     "content": str,
#     "sql": Optional[str],
#     "row_count": Optional[int],
# }


def _key(session_id: str) -> str:
    """Build the Redis key for a session's context."""
    return f"query:context:{session_id}"


async def get_context(
    redis_client: Optional[Redis],
    session_id: str,
) -> list[dict]:
    """
    Retrieve the conversation context for a session.

    Parameters
    ----------
    redis_client : Optional[Redis]
        A Redis client instance, or None if Redis is unavailable.
    session_id : str
        The unique session identifier.

    Returns
    -------
    list[dict]
        List of turn dicts, or ``[]`` if Redis is unavailable or key
        doesn't exist.
    """
    if redis_client is None:
        return []

    try:
        raw = redis_client.get(_key(session_id))
        if raw is None:
            return []
        turns = json.loads(raw)
        if not isinstance(turns, list):
            log.warning("context_invalid_format", session_id=session_id)
            return []
        return turns
    except Exception as exc:
        log.warning("context_get_failed", session_id=session_id, error=str(exc))
        return []


async def append_context(
    redis_client: Optional[Redis],
    session_id: str,
    turn: dict,
    settings,
) -> None:
    """
    Append a turn to the session context, trim to max turns, and set TTL.

    Parameters
    ----------
    redis_client : Optional[Redis]
        A Redis client instance, or None (no-op).
    session_id : str
        The unique session identifier.
    turn : dict
        A turn dict with keys: role, content, sql, row_count.
    settings : Settings
        Application settings (uses QUERY_CONTEXT_MAX_TURNS and
        QUERY_CONTEXT_TTL).
    """
    if redis_client is None:
        return

    try:
        key = _key(session_id)
        max_turns: int = settings.QUERY_CONTEXT_MAX_TURNS
        ttl: int = settings.QUERY_CONTEXT_TTL

        # Get existing turns
        raw = redis_client.get(key)
        turns: list[dict] = []
        if raw is not None:
            loaded = json.loads(raw)
            if isinstance(loaded, list):
                turns = loaded

        # Append new turn
        turns.append(turn)

        # Trim oldest turns if exceeding max
        if len(turns) > max_turns:
            turns = turns[-max_turns:]

        # Write back and set TTL
        redis_client.set(key, json.dumps(turns), ex=ttl)

        log.debug(
            "context_appended",
            session_id=session_id,
            turn_count=len(turns),
            role=turn.get("role"),
        )
    except Exception as exc:
        log.warning("context_append_failed", session_id=session_id, error=str(exc))


async def clear_context(
    redis_client: Optional[Redis],
    session_id: str,
) -> None:
    """
    Delete the session context from Redis.

    Parameters
    ----------
    redis_client : Optional[Redis]
        A Redis client instance, or None (no-op).
    session_id : str
        The unique session identifier.
    """
    if redis_client is None:
        return

    try:
        redis_client.delete(_key(session_id))
        log.debug("context_cleared", session_id=session_id)
    except Exception as exc:
        log.warning("context_clear_failed", session_id=session_id, error=str(exc))
