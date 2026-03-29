"""Feature 8 export size estimation utilities."""

from __future__ import annotations

from typing import Literal

ExportFormat = Literal["csv", "netcdf", "json"]


def estimate_export_size_bytes(
    row_count: int,
    column_count: int,
    export_format: ExportFormat,
) -> int:
    """Estimate export size in bytes using Feature 8 FR-06 formulas."""
    safe_rows = max(0, row_count)
    safe_columns = max(1, column_count)

    if export_format == "csv":
        return int(safe_rows * 150)
    if export_format == "netcdf":
        return int(safe_rows * safe_columns * 8 * 1.1)
    if export_format == "json":
        return int(safe_rows * 150 * 1.8)

    raise ValueError(f"Unsupported export format: {export_format}")


def should_use_async_export(
    row_count: int,
    column_count: int,
    export_format: ExportFormat,
    sync_limit_mb: int,
) -> bool:
    """
    Determine whether export should use async path.

    Uses async path if estimate is at/above limit, or within 10% of limit.
    """
    estimate_bytes = estimate_export_size_bytes(row_count, column_count, export_format)
    sync_limit_bytes = max(1, sync_limit_mb) * 1024 * 1024

    borderline_threshold = int(sync_limit_bytes * 0.9)
    return estimate_bytes >= borderline_threshold
