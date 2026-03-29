"""GDAC index download and streaming parse utilities."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timezone
import codecs
from typing import Iterable, Optional
import zlib

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


def _probe_index_availability(mirror_url: str, index_filename: str) -> None:
    """Verify index is reachable for mirror failover decisions."""
    url = _index_url(mirror_url, index_filename)
    headers = {"User-Agent": _user_agent()}
    timeout = float(settings.GDAC_MIRROR_TIMEOUT_SECONDS)

    with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()


def _iter_streamed_gzip_lines(mirror_url: str, index_filename: str) -> Iterable[str]:
    """Stream a remote gz index and yield decoded lines without buffering the full file."""
    url = _index_url(mirror_url, index_filename)
    headers = {"User-Agent": _user_agent()}
    timeout = float(settings.GDAC_MIRROR_TIMEOUT_SECONDS)

    with httpx.Client(timeout=timeout, headers=headers, follow_redirects=True) as client:
        with client.stream("GET", url) as response:
            response.raise_for_status()

            decompressor = zlib.decompressobj(16 + zlib.MAX_WBITS)
            decoder = codecs.getincrementaldecoder("utf-8")(errors="replace")
            pending = ""

            for chunk in response.iter_bytes():
                if not chunk:
                    continue
                try:
                    decompressed = decompressor.decompress(chunk)
                except zlib.error as exc:
                    raise RuntimeError(f"Invalid gzip stream for {index_filename}: {str(exc)}") from exc

                if not decompressed:
                    continue

                pending += decoder.decode(decompressed)
                lines = pending.split("\n")
                pending = lines.pop()
                for line in lines:
                    yield line.rstrip("\r")

            try:
                flushed = decompressor.flush()
            except zlib.error as exc:
                raise RuntimeError(f"Invalid gzip stream for {index_filename}: {str(exc)}") from exc

            pending += decoder.decode(flushed, final=True)
            if pending:
                yield pending.rstrip("\r")


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


def _iter_parsed_index_entries(
    lines: Iterable[str],
    *,
    source_name: str,
) -> Iterable[GDACProfileEntry]:
    for raw_line in lines:
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

        yield GDACProfileEntry(
            file_path=file_path,
            date=obs_date,
            latitude=latitude,
            longitude=longitude,
            ocean=parts[4],
            profiler_type=parts[5],
            institution=parts[6],
            date_update=updated_at,
        )


def _iter_index_entries(mirror_url: str, index_filename: str) -> Iterable[GDACProfileEntry]:
    return _iter_parsed_index_entries(
        _iter_streamed_gzip_lines(mirror_url, index_filename),
        source_name=index_filename,
    )


def _iter_entries_for_mirror(mirror_url: str) -> Iterable[GDACProfileEntry]:
    global_entries = 0
    merge_entries = 0

    for entry in _iter_index_entries(mirror_url, GLOBAL_PROFILE_INDEX):
        global_entries += 1
        yield entry

    # Merge/BGC index is optional. Any failure should not fail sync or
    # trigger mirror failover when the core global index succeeded.
    try:
        for entry in _iter_index_entries(mirror_url, MERGE_PROFILE_INDEX):
            merge_entries += 1
            yield entry
    except Exception as exc:
        logger.warning(
            "gdac_merge_index_skipped",
            mirror=mirror_url,
            index=MERGE_PROFILE_INDEX,
            error=str(exc),
        )

    logger.info(
        "gdac_index_parse_completed",
        mirror=mirror_url,
        global_entries=global_entries,
        merge_entries=merge_entries,
        total_entries=global_entries + merge_entries,
    )


def download_and_parse_index_with_mirror(mirror_url: str) -> tuple[Iterable[GDACProfileEntry], str]:
    """Download and parse GDAC profile indexes with mirror failover.

    Returns both parsed entries and the mirror URL that succeeded.
    """
    last_error: Optional[Exception] = None

    for candidate in _candidate_mirrors(mirror_url):
        try:
            _probe_index_availability(candidate, GLOBAL_PROFILE_INDEX)
            logger.info("gdac_index_download_started", mirror=candidate)
            return _iter_entries_for_mirror(candidate), candidate
        except Exception as exc:
            last_error = exc
            logger.warning(
                "gdac_index_mirror_failed",
                mirror=candidate,
                error=str(exc),
            )

    raise RuntimeError("Failed to download/parse GDAC indexes from all mirrors") from last_error


def download_and_parse_index(mirror_url: str) -> Iterable[GDACProfileEntry]:
    """Compatibility wrapper returning parsed index entries iterator."""
    entries, _ = download_and_parse_index_with_mirror(mirror_url)
    return entries
