"""
FloatChat Chat Interface — Load-Time Suggestions

Generates example queries for the SuggestionsPanel shown when a new
chat session starts. Sources dataset metadata from Feature 3's
get_all_summaries() and constructs varied query patterns.

Caching: suggestions are stored in Redis with a configurable TTL
(default 1 hour). If Redis is unavailable or no datasets exist,
hardcoded Argo fallback suggestions are returned.

Never raises — all exceptions are caught, logged, and fallbacks returned.
"""

import json
from typing import Any, Optional

import structlog
from redis import Redis
from sqlalchemy.orm import Session

from app.search.discovery import get_all_summaries

log = structlog.get_logger(__name__)

# Redis key for cached suggestions
_CACHE_KEY = "chat_suggestions"

# Hardcoded fallback suggestions when no datasets exist or on any failure
_FALLBACK_SUGGESTIONS: list[dict[str, str]] = [
    {
        "query": "Show me all Argo float profiles in the North Atlantic from the last year",
        "description": "Browse recent profiles in a well-sampled ocean basin",
    },
    {
        "query": "What is the average temperature at 500m depth in the Southern Ocean?",
        "description": "Explore deep-water temperature patterns in the Antarctic",
    },
    {
        "query": "How many floats are currently active in the Pacific Ocean?",
        "description": "Get a count of operational floats in the largest ocean basin",
    },
    {
        "query": "Show me salinity profiles near the Gulf Stream for 2025",
        "description": "Examine salinity structure in a major western boundary current",
    },
]


def generate_load_time_suggestions(
    db: Session,
    redis_client: Optional[Redis],
    settings: Any,
) -> list[dict[str, str]]:
    """
    Generate 4–6 example queries for the chat suggestions panel.

    Checks Redis cache first. On cache miss, builds suggestions from
    dataset metadata via Feature 3's get_all_summaries(). Caches the
    result in Redis.

    Parameters
    ----------
    db : Session
        SQLAlchemy database session (read-write) for querying datasets.
    redis_client : Optional[Redis]
        Redis client for caching. None if unavailable.
    settings : Settings
        Application settings (for TTL and count).

    Returns
    -------
    list[dict[str, str]]
        Each dict has 'query' and 'description' keys.
    """
    # 1. Check Redis cache
    if redis_client is not None:
        try:
            cached = redis_client.get(_CACHE_KEY)
            if cached:
                suggestions = json.loads(cached)
                log.debug("suggestions_cache_hit", count=len(suggestions))
                return suggestions
        except Exception as exc:
            log.warning("suggestions_cache_read_failed", error=str(exc))

    # 2. Fetch dataset summaries from Feature 3
    try:
        summaries = get_all_summaries(db)
    except Exception as exc:
        log.warning("suggestions_summaries_failed", error=str(exc))
        return _FALLBACK_SUGGESTIONS

    if not summaries:
        log.info("suggestions_no_datasets_fallback")
        return _FALLBACK_SUGGESTIONS

    # 3. Build suggestions from dataset metadata
    try:
        suggestions = _build_suggestions_from_datasets(summaries, settings)
    except Exception as exc:
        log.warning("suggestions_build_failed", error=str(exc))
        return _FALLBACK_SUGGESTIONS

    # 4. Cache in Redis
    if redis_client is not None:
        try:
            ttl = getattr(settings, "CHAT_SUGGESTIONS_CACHE_TTL_SECONDS", 3600)
            redis_client.setex(
                _CACHE_KEY,
                ttl,
                json.dumps(suggestions),
            )
            log.debug("suggestions_cached", count=len(suggestions), ttl=ttl)
        except Exception as exc:
            log.warning("suggestions_cache_write_failed", error=str(exc))

    return suggestions


def _build_suggestions_from_datasets(
    summaries: list[dict[str, Any]],
    settings: Any,
) -> list[dict[str, str]]:
    """
    Construct varied query suggestions from dataset metadata.

    Generates at least one spatial, one temporal, and one variable-specific
    suggestion. Returns 4–6 suggestions.
    """
    target_count = getattr(settings, "CHAT_SUGGESTIONS_COUNT", 6)
    suggestions: list[dict[str, str]] = []

    # Use the first dataset for primary suggestions
    primary = summaries[0]
    ds_name = primary.get("name", "the dataset")
    variables = primary.get("variable_list") or []
    date_start = primary.get("date_range_start", "")
    date_end = primary.get("date_range_end", "")
    float_count = primary.get("float_count", 0)

    # Extract year range if available
    start_year = date_start[:4] if date_start and len(date_start) >= 4 else "2020"
    end_year = date_end[:4] if date_end and len(date_end) >= 4 else "2025"

    # Suggestion 1: Spatial query
    suggestions.append({
        "query": f"Show me all float profiles in the North Atlantic from {ds_name}",
        "description": f"Browse profiles from {ds_name} in a well-sampled region",
    })

    # Suggestion 2: Temporal query
    suggestions.append({
        "query": f"How many profiles were collected between {start_year} and {end_year}?",
        "description": f"Explore the temporal coverage of available data ({start_year}–{end_year})",
    })

    # Suggestion 3: Variable-specific query
    if variables and len(variables) > 0:
        var = variables[0] if isinstance(variables[0], str) else str(variables[0])
        suggestions.append({
            "query": f"What is the average {var} at 500m depth in the Southern Ocean?",
            "description": f"Analyze deep-water {var} patterns across the Southern Ocean",
        })
    else:
        suggestions.append({
            "query": "What is the average temperature at 500m depth in the Southern Ocean?",
            "description": "Analyze deep-water temperature patterns across the Southern Ocean",
        })

    # Suggestion 4: Count/overview query
    suggestions.append({
        "query": f"How many active floats are in {ds_name}?",
        "description": f"Get an overview of the {float_count} floats in this dataset",
    })

    # Suggestion 5: Second variable or depth query
    if variables and len(variables) > 1:
        var2 = variables[1] if isinstance(variables[1], str) else str(variables[1])
        suggestions.append({
            "query": f"Show me {var2} profiles from the Pacific Ocean in {end_year}",
            "description": f"Explore {var2} data in the Pacific for the most recent period",
        })
    else:
        suggestions.append({
            "query": f"Show me depth profiles near the Gulf Stream from {end_year}",
            "description": "Examine profile structure in a major boundary current",
        })

    # Suggestion 6: Use a second dataset if available
    if len(summaries) > 1:
        secondary = summaries[1]
        sec_name = secondary.get("name", "another dataset")
        suggestions.append({
            "query": f"Compare float counts between {ds_name} and {sec_name}",
            "description": "Compare coverage across different datasets",
        })

    # Trim to target count
    suggestions = suggestions[:target_count]

    log.info(
        "suggestions_built_from_datasets",
        dataset_count=len(summaries),
        suggestion_count=len(suggestions),
    )

    return suggestions
