"""GDAC synchronization orchestration logic."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
import re
import time
from typing import Optional
import uuid

import structlog
from sqlalchemy import select, tuple_

from app.config import settings
from app.db.models import Dataset, GDACSyncRun, GDACSyncState, IngestionJob, Profile
from app.db.session import SessionLocal
from app.gdac.downloader import download_profile_files
from app.gdac.index import GDACProfileEntry, download_and_parse_index_with_mirror
from app.ingestion.tasks import ingest_file_task
from app.notifications.sender import notify


logger = structlog.get_logger(__name__)

_PROFILE_FILE_RE = re.compile(r"^(?P<mode>[RrDdAa])?(?P<platform>\d+)_(?P<cycle>\d+)")


@dataclass
class GDACSyncResult:
    """Summary result for one sync execution."""

    run_id: uuid.UUID
    status: str
    profiles_found: int
    profiles_downloaded: int
    profiles_ingested: int
    profiles_skipped: int
    duration_seconds: float
    error: Optional[str]


def _now_utc() -> datetime:
    return datetime.now(timezone.utc)


def _entry_identity(entry: GDACProfileEntry) -> tuple[Optional[str], Optional[int], Optional[str]]:
    name = Path(entry.file_path).name
    match = _PROFILE_FILE_RE.match(name)
    if not match:
        return None, None, None

    mode = match.group("mode").upper() if match.group("mode") else None
    platform = match.group("platform")
    cycle_str = match.group("cycle")

    try:
        cycle = int(cycle_str)
    except ValueError:
        return None, None, mode

    return platform, cycle, mode


def _entry_is_delayed_mode(entry: GDACProfileEntry) -> bool:
    _, _, mode = _entry_identity(entry)
    return mode == "D"


def _state_value(db, key: str) -> str:
    row = db.get(GDACSyncState, key)
    if row is None:
        return ""
    return row.value or ""


def _set_state_value(db, key: str, value: str) -> None:
    row = db.get(GDACSyncState, key)
    if row is None:
        row = GDACSyncState(key=key, value=value)
        db.add(row)
    else:
        row.value = value
        row.updated_at = _now_utc()


def _parse_checkpoint_date(raw: str) -> Optional[date]:
    raw = (raw or "").strip()
    if not raw:
        return None

    for fmt in ("%Y-%m-%d", "%Y%m%d"):
        try:
            return datetime.strptime(raw, fmt).date()
        except ValueError:
            continue

    try:
        return datetime.fromisoformat(raw.replace("Z", "+00:00")).date()
    except ValueError:
        return None


def _filter_by_window(
    entries: list[GDACProfileEntry],
    *,
    checkpoint_date: Optional[date],
    lookback_days: int,
) -> list[GDACProfileEntry]:
    if checkpoint_date is None:
        cutoff = (_now_utc() - timedelta(days=lookback_days)).date()
        return [entry for entry in entries if entry.date >= cutoff]

    return [entry for entry in entries if entry.date_update.date() > checkpoint_date]


def _deduplicate_entries(db, entries: list[GDACProfileEntry]) -> tuple[list[GDACProfileEntry], int]:
    """Return entries eligible for ingestion and count of deduplicated skips."""
    if not entries:
        return [], 0

    accepted: list[GDACProfileEntry] = []
    skipped = 0

    for i in range(0, len(entries), settings.GDAC_INDEX_BATCH_SIZE):
        batch = entries[i : i + settings.GDAC_INDEX_BATCH_SIZE]

        keys: list[tuple[str, int]] = []
        entry_by_key: dict[tuple[str, int], list[GDACProfileEntry]] = {}
        unresolved: list[GDACProfileEntry] = []

        for entry in batch:
            platform, cycle, _ = _entry_identity(entry)
            if platform is None or cycle is None:
                unresolved.append(entry)
                continue

            key = (platform, cycle)
            keys.append(key)
            entry_by_key.setdefault(key, []).append(entry)

        existing_by_key: dict[tuple[str, int], Profile] = {}
        if keys:
            rows = db.execute(
                select(Profile).where(tuple_(Profile.platform_number, Profile.cycle_number).in_(keys))
            ).scalars().all()
            for row in rows:
                existing_by_key[(row.platform_number, row.cycle_number)] = row

        # Entries that do not expose platform/cycle metadata cannot be deduplicated
        # by the agreed strategy and are therefore skipped safely.
        skipped += len(unresolved)

        for key, group in entry_by_key.items():
            delayed_group = [entry for entry in group if _entry_is_delayed_mode(entry)]
            preferred_general = max(group, key=lambda entry: entry.date_update)
            preferred_delayed = (
                max(delayed_group, key=lambda entry: entry.date_update)
                if delayed_group
                else None
            )

            existing = existing_by_key.get(key)
            if existing is None:
                accepted.append(preferred_delayed or preferred_general)
                skipped += max(0, len(group) - 1)
                continue

            if existing.data_mode == "R" and preferred_delayed is not None:
                accepted.append(preferred_delayed)
                skipped += max(0, len(group) - 1)
            else:
                skipped += len(group)

    return accepted, skipped


def _notify_event(event: str, context: dict) -> None:
    try:
        notify(event, context)
    except Exception as exc:
        logger.warning("gdac_sync_notification_failed", event=event, error=str(exc))


def run_gdac_sync(triggered_by: str = "scheduled", lookback_days: int | None = None) -> GDACSyncResult:
    """Run one GDAC sync cycle and persist run/checkpoint state."""
    started_perf = time.perf_counter()

    if not settings.GDAC_SYNC_ENABLED:
        duration = time.perf_counter() - started_perf
        logger.info("gdac_sync_disabled")
        return GDACSyncResult(
            run_id=uuid.uuid4(),
            status="completed",
            profiles_found=0,
            profiles_downloaded=0,
            profiles_ingested=0,
            profiles_skipped=0,
            duration_seconds=duration,
            error="GDAC sync disabled",
        )

    effective_lookback = lookback_days if lookback_days is not None else settings.GDAC_LOOKBACK_DAYS
    db = SessionLocal()

    run = GDACSyncRun(
        status="running",
        gdac_mirror=settings.GDAC_PRIMARY_MIRROR,
        lookback_days=effective_lookback,
        triggered_by=triggered_by,
    )

    profiles_found = 0
    profiles_downloaded = 0
    profiles_skipped = 0
    error_message: Optional[str] = None
    status = "failed"

    try:
        db.add(run)
        db.flush()

        dataset = Dataset(
            name=f"GDAC Sync {_now_utc().date().isoformat()}",
            source_filename="gdac_sync",
            raw_file_path=None,
            is_active=True,
            is_public=False,
        )
        db.add(dataset)
        db.flush()

        checkpoint_date = _parse_checkpoint_date(_state_value(db, "last_sync_index_date"))

        entries_iter, used_mirror = download_and_parse_index_with_mirror(settings.GDAC_PRIMARY_MIRROR)
        run.gdac_mirror = used_mirror

        dispatch_failures = 0
        download_failures = 0

        batch_size = max(1, int(settings.GDAC_INDEX_BATCH_SIZE))
        rolling_batch: list[GDACProfileEntry] = []

        if checkpoint_date is None:
            cutoff_date = (_now_utc() - timedelta(days=effective_lookback)).date()
        else:
            cutoff_date = None

        def _process_sync_batch(entries_batch: list[GDACProfileEntry]) -> None:
            nonlocal profiles_found
            nonlocal profiles_skipped
            nonlocal profiles_downloaded
            nonlocal dispatch_failures
            nonlocal download_failures

            deduped_entries, skipped_count = _deduplicate_entries(db, entries_batch)
            profiles_found += len(deduped_entries)
            profiles_skipped += skipped_count

            if not deduped_entries:
                return

            results = download_profile_files(
                deduped_entries,
                used_mirror,
                settings.GDAC_MAX_CONCURRENT_DOWNLOADS,
            )

            for result in results:
                if not result.success or not result.temp_file_path:
                    download_failures += 1
                    continue

                profiles_downloaded += 1

                filename = Path(result.entry.file_path).name
                job = IngestionJob(
                    dataset_id=dataset.dataset_id,
                    original_filename=filename,
                    raw_file_path=result.temp_file_path,
                    status="pending",
                    progress_pct=0,
                    profiles_ingested=0,
                    errors=[],
                    source="gdac_sync",
                )
                db.add(job)
                db.flush()
                db.commit()

                try:
                    ingest_file_task.delay(
                        job_id=str(job.job_id),
                        file_path=result.temp_file_path,
                        dataset_id=dataset.dataset_id,
                        original_filename=filename,
                    )
                except Exception as exc:
                    dispatch_failures += 1
                    job.status = "failed"
                    job.error_log = f"Dispatch failed: {str(exc)}"

        for entry in entries_iter:
            if checkpoint_date is None:
                if entry.date < cutoff_date:
                    continue
            elif entry.date_update.date() <= checkpoint_date:
                continue

            rolling_batch.append(entry)
            if len(rolling_batch) >= batch_size:
                _process_sync_batch(rolling_batch)
                rolling_batch = []

        if rolling_batch:
            _process_sync_batch(rolling_batch)

        # By confirmed product decision, ingestion is asynchronous and this value
        # is a proxy equal to successfully downloaded files at sync-completion time.
        profiles_ingested_proxy = profiles_downloaded

        if download_failures > 0 or dispatch_failures > 0:
            status = "partial"
        else:
            status = "completed"

        run.completed_at = _now_utc()
        run.status = status
        run.index_profiles_found = profiles_found
        run.profiles_downloaded = profiles_downloaded
        run.profiles_ingested = profiles_ingested_proxy
        run.profiles_skipped = profiles_skipped
        run.error_message = None

        if status in {"completed", "partial"}:
            _set_state_value(db, "last_sync_index_date", _now_utc().date().isoformat())
            _set_state_value(db, "last_sync_completed_at", _now_utc().isoformat())

        db.commit()

        _notify_event(
            "gdac_sync_completed",
            {
                "run_id": str(run.run_id),
                "status": status,
                "profiles_found": profiles_found,
                "profiles_downloaded": profiles_downloaded,
                "profiles_ingested": profiles_ingested_proxy,
                "profiles_skipped": profiles_skipped,
                "mirror": run.gdac_mirror,
            },
        )

        duration = time.perf_counter() - started_perf
        return GDACSyncResult(
            run_id=run.run_id,
            status=status,
            profiles_found=profiles_found,
            profiles_downloaded=profiles_downloaded,
            profiles_ingested=profiles_ingested_proxy,
            profiles_skipped=profiles_skipped,
            duration_seconds=duration,
            error=None,
        )

    except Exception as exc:
        error_message = str(exc)
        logger.error("gdac_sync_failed", error=error_message)

        run.completed_at = _now_utc()
        run.status = "failed"
        run.index_profiles_found = profiles_found
        run.profiles_downloaded = profiles_downloaded
        run.profiles_ingested = profiles_downloaded
        run.profiles_skipped = profiles_skipped
        run.error_message = error_message

        try:
            db.commit()
        except Exception:
            db.rollback()

        _notify_event(
            "gdac_sync_failed",
            {
                "run_id": str(run.run_id),
                "error_message": error_message,
            },
        )

        duration = time.perf_counter() - started_perf
        return GDACSyncResult(
            run_id=run.run_id,
            status="failed",
            profiles_found=profiles_found,
            profiles_downloaded=profiles_downloaded,
            profiles_ingested=profiles_downloaded,
            profiles_skipped=profiles_skipped,
            duration_seconds=duration,
            error=error_message,
        )
    finally:
        db.close()
