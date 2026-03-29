"""GDAC sync orchestration tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
import os
import tempfile
from unittest.mock import MagicMock

import pytest
from sqlalchemy import select

from app.db.models import GDACSyncRun, GDACSyncState, IngestionJob
from app.gdac import sync
from app.gdac.downloader import DownloadResult
from app.gdac.index import GDACProfileEntry


@pytest.fixture(autouse=True)
def _sqlite_geo_functions(db_session):
    raw = db_session.connection().connection
    raw.create_function("AsBinary", 1, lambda x: x)


def _entry(file_path: str) -> GDACProfileEntry:
    now = datetime.now(UTC)
    return GDACProfileEntry(
        file_path=file_path,
        date=now.date(),
        latitude=10.0,
        longitude=20.0,
        ocean="I",
        profiler_type="846",
        institution="AOML",
        date_update=now,
    )


def _temp_nc_file() -> str:
    handle = tempfile.NamedTemporaryFile(prefix="gdac_test_", suffix=".nc", delete=False)
    handle.write(b"netcdf-bytes")
    handle.flush()
    handle.close()
    return handle.name


def test_run_gdac_sync_completed_creates_jobs_and_checkpoint(db_session, monkeypatch):
    monkeypatch.setattr(sync, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(sync.settings, "GDAC_SYNC_ENABLED", True)
    monkeypatch.setattr(sync.settings, "GDAC_LOOKBACK_DAYS", 30)
    monkeypatch.setattr(sync.settings, "GDAC_INDEX_BATCH_SIZE", 1000)

    entries = [
        _entry("dac/aoml/1234567/profiles/R1234567_001.nc"),
        _entry("dac/aoml/1234567/profiles/R1234567_002.nc"),
    ]
    temp_paths = [_temp_nc_file(), _temp_nc_file()]

    monkeypatch.setattr(
        sync,
        "download_and_parse_index_with_mirror",
        lambda _mirror: (iter(entries), "https://used-mirror.example"),
    )
    monkeypatch.setattr(
        sync,
        "download_profile_files",
        lambda _entries, _mirror, _workers: [
            DownloadResult(entry=entries[0], temp_file_path=temp_paths[0], success=True, error=None, attempts=1),
            DownloadResult(entry=entries[1], temp_file_path=temp_paths[1], success=True, error=None, attempts=1),
        ],
    )

    delay_mock = MagicMock()
    monkeypatch.setattr(sync.ingest_file_task, "delay", delay_mock)
    notify_mock = MagicMock()
    monkeypatch.setattr(sync, "notify", notify_mock)

    result = sync.run_gdac_sync(triggered_by="manual")

    assert result.status == "completed"
    assert result.profiles_found == 2
    assert result.profiles_downloaded == 2
    assert result.profiles_ingested == 2

    run_row = db_session.execute(select(GDACSyncRun)).scalar_one()
    assert run_row.status == "completed"
    assert run_row.triggered_by == "manual"
    assert run_row.gdac_mirror == "https://used-mirror.example"
    assert run_row.index_profiles_found == 2
    assert run_row.profiles_downloaded == 2
    assert run_row.profiles_ingested == 2

    state_rows = {
        row.key: row.value for row in db_session.execute(select(GDACSyncState)).scalars().all()
    }
    assert state_rows["last_sync_index_date"]
    assert state_rows["last_sync_completed_at"]

    jobs = db_session.execute(select(IngestionJob)).scalars().all()
    assert len(jobs) == 2
    assert all(job.source == "gdac_sync" for job in jobs)
    assert delay_mock.call_count == 2
    notify_mock.assert_called_once()

    assert not os.path.exists(temp_paths[0])
    assert not os.path.exists(temp_paths[1])


def test_run_gdac_sync_partial_updates_checkpoint(db_session, monkeypatch):
    monkeypatch.setattr(sync, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(sync.settings, "GDAC_SYNC_ENABLED", True)
    monkeypatch.setattr(sync.settings, "GDAC_INDEX_BATCH_SIZE", 1000)

    entries = [
        _entry("dac/aoml/1234567/profiles/R1234567_003.nc"),
        _entry("dac/aoml/1234567/profiles/R1234567_004.nc"),
    ]
    temp_path = _temp_nc_file()

    monkeypatch.setattr(
        sync,
        "download_and_parse_index_with_mirror",
        lambda _mirror: (iter(entries), "https://used-mirror.example"),
    )
    monkeypatch.setattr(
        sync,
        "download_profile_files",
        lambda _entries, _mirror, _workers: [
            DownloadResult(entry=entries[0], temp_file_path=temp_path, success=True, error=None, attempts=1),
            DownloadResult(entry=entries[1], temp_file_path=None, success=False, error="timeout", attempts=3),
        ],
    )

    monkeypatch.setattr(sync.ingest_file_task, "delay", MagicMock())
    monkeypatch.setattr(sync, "notify", MagicMock())

    result = sync.run_gdac_sync(triggered_by="scheduled")

    assert result.status == "partial"
    assert result.profiles_found == 2
    assert result.profiles_downloaded == 1

    run_row = db_session.execute(select(GDACSyncRun)).scalar_one()
    assert run_row.status == "partial"
    assert run_row.profiles_downloaded == 1

    state_rows = {
        row.key: row.value for row in db_session.execute(select(GDACSyncState)).scalars().all()
    }
    assert state_rows["last_sync_index_date"]
    assert state_rows["last_sync_completed_at"]

    assert not os.path.exists(temp_path)


def test_run_gdac_sync_processes_iterator_in_batches(db_session, monkeypatch):
    monkeypatch.setattr(sync, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(sync.settings, "GDAC_SYNC_ENABLED", True)
    monkeypatch.setattr(sync.settings, "GDAC_INDEX_BATCH_SIZE", 2)

    entries = [
        _entry("dac/aoml/1234567/profiles/R1234567_001.nc"),
        _entry("dac/aoml/1234567/profiles/R1234567_002.nc"),
        _entry("dac/aoml/1234567/profiles/R1234567_003.nc"),
        _entry("dac/aoml/1234567/profiles/R1234567_004.nc"),
        _entry("dac/aoml/1234567/profiles/R1234567_005.nc"),
    ]

    monkeypatch.setattr(
        sync,
        "download_and_parse_index_with_mirror",
        lambda _mirror: (iter(entries), "https://used-mirror.example"),
    )

    observed_batch_sizes: list[int] = []

    def _download_in_batches(batch_entries, _mirror, _workers):
        observed_batch_sizes.append(len(batch_entries))
        return [
            DownloadResult(
                entry=entry,
                temp_file_path=_temp_nc_file(),
                success=True,
                error=None,
                attempts=1,
            )
            for entry in batch_entries
        ]

    monkeypatch.setattr(sync, "download_profile_files", _download_in_batches)
    monkeypatch.setattr(sync.ingest_file_task, "delay", MagicMock())
    monkeypatch.setattr(sync, "notify", MagicMock())

    result = sync.run_gdac_sync(triggered_by="manual")

    assert result.status == "completed"
    assert result.profiles_found == 5
    assert result.profiles_downloaded == 5
    assert observed_batch_sizes == [2, 2, 1]
    assert max(observed_batch_sizes) == 2


def test_run_gdac_sync_failure_preserves_existing_checkpoint(db_session, monkeypatch):
    db_session.add(GDACSyncState(key="last_sync_index_date", value="2024-01-01"))
    db_session.add(GDACSyncState(key="last_sync_completed_at", value="2024-01-01T00:00:00+00:00"))
    db_session.commit()

    monkeypatch.setattr(sync, "SessionLocal", lambda: db_session)
    monkeypatch.setattr(sync.settings, "GDAC_SYNC_ENABLED", True)
    monkeypatch.setattr(
        sync,
        "download_and_parse_index_with_mirror",
        lambda _mirror: (_ for _ in ()).throw(RuntimeError("index unavailable")),
    )

    notify_mock = MagicMock()
    monkeypatch.setattr(sync, "notify", notify_mock)

    result = sync.run_gdac_sync(triggered_by="scheduled")

    assert result.status == "failed"
    assert result.error is not None

    run_row = db_session.execute(select(GDACSyncRun)).scalar_one()
    assert run_row.status == "failed"
    assert "index unavailable" in (run_row.error_message or "")

    checkpoint = db_session.get(GDACSyncState, "last_sync_index_date")
    assert checkpoint is not None
    assert checkpoint.value == "2024-01-01"

    failure_events = [call.args[0] for call in notify_mock.call_args_list]
    assert "gdac_sync_failed" in failure_events
