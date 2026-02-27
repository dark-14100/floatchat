"""
FloatChat NL Query Engine — Geography Resolver

Scans a natural-language query for known geographic region names and returns
bounding-box coordinates that the pipeline injects into the LLM prompt.

The JSON lookup file is loaded once at module import time — never per request.
"""

import json
import os
from typing import Optional

import structlog

log = structlog.get_logger(__name__)

# ── Load geography lookup once at import time ───────────────────────────────
_GEOGRAPHY_DATA: dict[str, dict] = {}

_DEFAULT_PATH = os.path.join(
    os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))),
    "data",
    "geography_lookup.json",
)


def _load_geography(path: Optional[str] = None) -> dict[str, dict]:
    """Load and return the geography lookup dict. Keys are lowercase."""
    file_path = path or _DEFAULT_PATH
    try:
        with open(file_path, "r", encoding="utf-8") as f:
            data = json.load(f)
        log.info("geography_lookup_loaded", entry_count=len(data), path=file_path)
        return {k.lower().strip(): v for k, v in data.items()}
    except FileNotFoundError:
        log.warning("geography_lookup_not_found", path=file_path)
        return {}
    except json.JSONDecodeError as exc:
        log.error("geography_lookup_invalid_json", path=file_path, error=str(exc))
        return {}


# Load at import time
_GEOGRAPHY_DATA = _load_geography()


def resolve_geography(query: str) -> Optional[dict]:
    """
    Scan a natural-language query for known geography names.

    Matching is case-insensitive substring search against all keys in the
    lookup table.  Returns the *first* match found (longest key first to
    prefer specific regions like "south china sea" over "china sea").

    Parameters
    ----------
    query : str
        The user's natural-language question.

    Returns
    -------
    dict or None
        ``{"name": str, "lat_min": float, "lat_max": float,
          "lon_min": float, "lon_max": float}``
        or ``None`` if no geography is detected.
    """
    if not _GEOGRAPHY_DATA or not query:
        return None

    query_lower = query.lower()

    # Sort by key length descending so "south china sea" matches before
    # "china sea" or "sea"
    for name in sorted(_GEOGRAPHY_DATA, key=len, reverse=True):
        if name in query_lower:
            bbox = _GEOGRAPHY_DATA[name]
            return {
                "name": name,
                "lat_min": bbox["lat_min"],
                "lat_max": bbox["lat_max"],
                "lon_min": bbox["lon_min"],
                "lon_max": bbox["lon_max"],
            }

    return None


def reload_geography(path: Optional[str] = None) -> int:
    """
    Reload the geography lookup from disk.  Useful for testing or after
    updating the JSON file at runtime.

    Returns the number of entries loaded.
    """
    global _GEOGRAPHY_DATA
    _GEOGRAPHY_DATA = _load_geography(path)
    return len(_GEOGRAPHY_DATA)
