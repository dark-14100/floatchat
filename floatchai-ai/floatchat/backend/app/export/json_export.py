"""Feature 8 JSON export generator."""

from __future__ import annotations

import json
import math
from datetime import datetime, timezone
from typing import Any


def _iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _sanitize_value(value: Any) -> Any:
    """Recursively sanitize values to produce strict valid JSON."""
    if isinstance(value, float):
        if math.isnan(value) or math.isinf(value):
            return None
        return value

    if isinstance(value, datetime):
        return _iso_utc(value)

    if isinstance(value, dict):
        return {str(k): _sanitize_value(v) for k, v in value.items()}

    if isinstance(value, (list, tuple)):
        return [_sanitize_value(v) for v in value]

    return value


def generate_json(
    rows: list[dict[str, Any]],
    columns: list[str],
    nl_query: str,
    generated_at: str | None = None,
    exported_at: datetime | None = None,
) -> bytes:
    """Generate JSON export bytes per Feature 8 FR-09."""
    export_time = exported_at or datetime.now(timezone.utc)
    export_iso = _iso_utc(export_time)

    payload = {
        "metadata": {
            "query": nl_query,
            "generated_at": generated_at or export_iso,
            "exported_at": export_iso,
            "row_count": len(rows),
            "columns": list(columns),
        },
        "profiles": [_sanitize_value(row) for row in rows],
    }

    return json.dumps(payload, ensure_ascii=False, allow_nan=False).encode("utf-8")
