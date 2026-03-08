"""GDAC NetCDF downloader with bounded concurrency and retry support."""

from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass
import os
from pathlib import Path
import tempfile
import time
from typing import Optional

import httpx
import structlog

from app.config import settings
from app.gdac.index import GDACProfileEntry


logger = structlog.get_logger(__name__)


@dataclass
class DownloadResult:
    """Outcome of attempting to download a single GDAC profile file."""

    entry: GDACProfileEntry
    temp_file_path: Optional[str]
    success: bool
    error: Optional[str]
    attempts: int


def _contact_email() -> str:
    return (
        settings.GDAC_CONTACT_EMAIL
        or settings.NOTIFICATION_EMAIL_FROM
        or "support@floatchat.local"
    )


def _user_agent() -> str:
    return f"FloatChat/1.0 (oceanographic research platform; contact: {_contact_email()})"


def _file_url(mirror_url: str, file_path: str) -> str:
    return f"{mirror_url.rstrip('/')}/{file_path.lstrip('/')}"


def _temp_nc_path(file_path: str) -> str:
    stem = Path(file_path).name
    suffix = Path(stem).suffix or ".nc"
    handle = tempfile.NamedTemporaryFile(prefix="gdac_", suffix=suffix, delete=False)
    handle.close()
    return handle.name


def _download_single_file(entry: GDACProfileEntry, mirror_url: str) -> DownloadResult:
    headers = {"User-Agent": _user_agent()}
    timeout = float(settings.GDAC_DOWNLOAD_TIMEOUT_SECONDS)
    url = _file_url(mirror_url, entry.file_path)
    backoff_seconds = (1.0, 2.0, 4.0)
    last_error: Optional[str] = None

    for attempt in range(1, 4):
        temp_path: Optional[str] = None
        try:
            temp_path = _temp_nc_path(entry.file_path)

            with httpx.stream(
                "GET",
                url,
                headers=headers,
                timeout=timeout,
                follow_redirects=True,
            ) as response:
                response.raise_for_status()

                with open(temp_path, "wb") as output:
                    for chunk in response.iter_bytes(chunk_size=1024 * 128):
                        if chunk:
                            output.write(chunk)

            return DownloadResult(
                entry=entry,
                temp_file_path=temp_path,
                success=True,
                error=None,
                attempts=attempt,
            )
        except Exception as exc:
            last_error = str(exc)

            if temp_path and os.path.exists(temp_path):
                try:
                    os.remove(temp_path)
                except OSError:
                    logger.warning(
                        "gdac_download_temp_cleanup_failed",
                        file_path=entry.file_path,
                        temp_file_path=temp_path,
                    )

            if attempt < 3:
                time.sleep(backoff_seconds[attempt - 1])

    logger.warning(
        "gdac_download_failed",
        file_path=entry.file_path,
        url=url,
        attempts=3,
        error=last_error,
    )
    return DownloadResult(
        entry=entry,
        temp_file_path=None,
        success=False,
        error=last_error,
        attempts=3,
    )


def download_profile_files(
    entries: list[GDACProfileEntry],
    mirror_url: str,
    max_workers: int,
) -> list[DownloadResult]:
    """Download GDAC profile files concurrently with retry and backoff."""
    if not entries:
        return []

    bounded_workers = max(1, min(max_workers, settings.GDAC_MAX_CONCURRENT_DOWNLOADS))
    results: list[DownloadResult] = []

    with ThreadPoolExecutor(max_workers=bounded_workers) as executor:
        futures = {
            executor.submit(_download_single_file, entry, mirror_url): entry.file_path
            for entry in entries
        }
        for future in as_completed(futures):
            results.append(future.result())

    return results
