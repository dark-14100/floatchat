"""Feature 8 CSV export generator."""

from __future__ import annotations

from datetime import datetime, timezone
from io import StringIO
from typing import Any

import pandas as pd

_BASE_COLUMN_ORDER = [
    "profile_id",
    "float_id",
    "platform_number",
    "juld_timestamp",
    "latitude",
    "longitude",
    "pressure",
]

_VARIABLE_COLUMN_ORDER = [
    "temperature",
    "salinity",
    "dissolved_oxygen",
    "chlorophyll",
    "nitrate",
    "ph",
]

_QC_COLUMN_ORDER = [
    "temp_qc",
    "psal_qc",
    "doxy_qc",
    "chla_qc",
    "nitrate_qc",
    "ph_qc",
]


def _iso_utc(dt: datetime) -> str:
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(timezone.utc).isoformat()


def _present_columns(rows: list[dict[str, Any]], columns: list[str]) -> list[str]:
    seen: dict[str, None] = {}
    for column in columns:
        seen[column] = None
    for row in rows:
        for key in row.keys():
            seen[key] = None
    return list(seen.keys())


def _ordered_columns(rows: list[dict[str, Any]], columns: list[str]) -> list[str]:
    present = _present_columns(rows, columns)
    present_set = set(present)

    ordered: list[str] = []

    for column in _BASE_COLUMN_ORDER:
        if column in present_set:
            ordered.append(column)

    for column in _VARIABLE_COLUMN_ORDER:
        if column in present_set:
            ordered.append(column)

    for column in _QC_COLUMN_ORDER:
        if column in present_set:
            ordered.append(column)

    for column in present:
        if column not in ordered:
            ordered.append(column)

    return ordered


def generate_csv(
    rows: list[dict[str, Any]],
    columns: list[str],
    nl_query: str,
    exported_at: datetime | None = None,
) -> bytes:
    """Generate CSV export bytes per Feature 8 FR-07."""
    export_time = exported_at or datetime.now(timezone.utc)
    export_iso = _iso_utc(export_time)

    ordered = _ordered_columns(rows, columns)

    frame = pd.DataFrame(rows)
    for column in ordered:
        if column not in frame.columns:
            frame[column] = None

    frame = frame[ordered] if ordered else frame

    csv_buffer = StringIO()
    frame.to_csv(
        csv_buffer,
        index=False,
        lineterminator="\n",
        na_rep="",
    )

    header_lines = [
        "# FloatChat Export",
        f"# Query: {nl_query}",
        f"# Exported: {export_iso}",
        f"# Rows: {len(rows)}",
    ]

    payload = "\n".join(header_lines) + "\n" + csv_buffer.getvalue()
    return payload.encode("utf-8")
