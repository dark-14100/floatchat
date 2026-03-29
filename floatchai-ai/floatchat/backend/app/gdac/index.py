"""GDAC index download and streaming parse utilities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import gzip
import io
from typing import Iterable, Optional

import httpx
import structlog

from app.config import settings


logger = structlog.get_logger(__name__)

GLOBAL_PROFILE_INDEX = "ar_index_global_prof.txt.gz"
MERGE_PROFILE_INDEX = "argo_merge-profile_index.txt.gz"


@dataclass
class GDACProfileEntry:
    """Single profile row extracted from the GDAC profile index."""

    file_path: str
    date: date
    latitude: float
    longitude: float
    ocean: str
    profiler_type: str
    institution: str
    date_update: datetime


def _contact_email() -> str:
    """Resolve contact email for GDAC User-Agent with a stable fallback chain."""
    return (
        settings.GDAC_CONTACT_EMAIL
        or settings.NOTIFICATION_EMAIL_FROM
        or "support@floatchat.local"
    )


def _user_agent() -> str:
    return f"FloatChat/1.0 (oceanographic research platform; contact: {_contact_email()})"


def _candidate_mirrors(primary_mirror: str) -> list[str]:
    mirrors = [primary_mirror.rstrip("/")]
    secondary = settings.GDAC_SECONDARY_MIRROR.rstrip("/")
    if secondary not in mirrors:
        mirrors.append(secondary)
    return mirrors


def _index_url(mirror_url: str, index_filename: str) -> str:
    return f"{mirror_url.rstrip('/')}/{index_filename}"


def _download_index_bytes(mirror_url: str, index_filename: str) -> bytes:
    url = _index_url(mirror_url, index_filename)
    headers = {"User-Agent": _user_agent()}
    timeout = float(settings.GDAC_MIRROR_TIMEOUT_SECONDS)

    with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
        response = client.get(url)
        response.raise_for_status()
        return response.content


def _parse_datetime_utc(raw: str) -> Optional[datetime]:
    raw = raw.strip()
    if not raw:
        return None

    if raw.endswith("Z"):
        raw = raw[:-1] + "+00:00"

    patterns = (
        "%Y%m%d%H%M%S",
        "%Y%m%d",
        "%Y-%m-%dT%H:%M:%S%z",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%d",
    )
    for pattern in patterns:
        try:
            parsed = datetime.strptime(raw, pattern)
            if parsed.tzinfo is None:
                return parsed.replace(tzinfo=timezone.utc)
            return parsed.astimezone(timezone.utc)
        except ValueError:
            continue
    return None


def _parse_date_only(raw: str) -> Optional[date]:
    parsed = _parse_datetime_utc(raw)
    if parsed is None:
        return None
    return parsed.date()


def _split_index_row(line: str) -> list[str]:
    # GDAC profile indexes are historically comma-delimited; specs may describe
    # tab-separated. Support both so parsing is resilient across mirrors.
    if "\t" in line:
        return [part.strip() for part in line.split("\t")]
    return [part.strip() for part in line.split(",")]


def _iter_gzip_lines(compressed_bytes: bytes) -> Iterable[str]:
    buffer = io.BytesIO(compressed_bytes)
    with gzip.GzipFile(fileobj=buffer, mode="rb") as gz_file:
        with io.TextIOWrapper(gz_file, encoding="utf-8", errors="replace") as reader:
            for line in reader:
                yield line.rstrip("\n")


def _parse_index_rows(compressed_bytes: bytes, *, source_name: str) -> list[GDACProfileEntry]:
    entries: list[GDACProfileEntry] = []

    for raw_line in _iter_gzip_lines(compressed_bytes):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue

        parts = _split_index_row(line)
        if len(parts) < 8:
            logger.debug(
                "gdac_index_row_skipped",
                reason="too_few_columns",
                source=source_name,
                raw_line=line,
            )
            continue

        file_path = parts[0]
        if file_path.lower() in {"file", "file_path"}:
            continue

        obs_date = _parse_date_only(parts[1])
        updated_at = _parse_datetime_utc(parts[7])
        if obs_date is None or updated_at is None:
            logger.debug(
                "gdac_index_row_skipped",
                reason="invalid_dates",
                source=source_name,
                file_path=file_path,
            )
            continue

        try:
            latitude = float(parts[2])
            longitude = float(parts[3])
        except ValueError:
            logger.debug(
                "gdac_index_row_skipped",
                reason="invalid_coordinates",
                source=source_name,
                file_path=file_path,
            )
            continue

        entries.append(
            GDACProfileEntry(
                file_path=file_path,
                date=obs_date,
                latitude=latitude,
                longitude=longitude,
                ocean=parts[4],
                profiler_type=parts[5],
                institution=parts[6],
                date_update=updated_at,
            )
        )

    return entries


def _deduplicate_by_path(entries: list[GDACProfileEntry]) -> list[GDACProfileEntry]:
    deduped: dict[str, GDACProfileEntry] = {}

    for entry in entries:
        existing = deduped.get(entry.file_path)
        if existing is None or entry.date_update > existing.date_update:
            deduped[entry.file_path] = entry

    return list(deduped.values())


def download_and_parse_index_with_mirror(mirror_url: str) -> tuple[list[GDACProfileEntry], str]:
    """Download and parse GDAC profile indexes with mirror failover.

    Returns both parsed entries and the mirror URL that succeeded.
    """
    last_error: Optional[Exception] = None

    for candidate in _candidate_mirrors(mirror_url):
        try:
            logger.info("gdac_index_download_started", mirror=candidate)

            global_index = _download_index_bytes(candidate, GLOBAL_PROFILE_INDEX)
            global_entries = _parse_index_rows(global_index, source_name=GLOBAL_PROFILE_INDEX)

            # Merge/BGC index is optional. Any failure should not fail sync or
            # trigger mirror failover when the core global index succeeded.
            merge_entries: list[GDACProfileEntry] = []
            try:
                merge_index = _download_index_bytes(candidate, MERGE_PROFILE_INDEX)
                merge_entries = _parse_index_rows(
                    merge_index,
                    source_name=MERGE_PROFILE_INDEX,
                )
            except Exception as exc:
                logger.warning(
                    "gdac_merge_index_skipped",
                    mirror=candidate,
                    index=MERGE_PROFILE_INDEX,
                    error=str(exc),
                )

            all_entries = _deduplicate_by_path(global_entries + merge_entries)

            logger.info(
                "gdac_index_parse_completed",
                mirror=candidate,
                global_entries=len(global_entries),
                merge_entries=len(merge_entries),
                deduplicated_entries=len(all_entries),
            )
            return all_entries, candidate
        except Exception as exc:
            last_error = exc
            logger.warning(
                "gdac_index_mirror_failed",
                mirror=candidate,
                error=str(exc),
            )

    raise RuntimeError("Failed to download/parse GDAC indexes from all mirrors") from last_error


def download_and_parse_index(mirror_url: str) -> list[GDACProfileEntry]:
    """Compatibility wrapper returning only parsed index entries."""
    entries, _ = download_and_parse_index_with_mirror(mirror_url)
    return entries
