"""GDAC downloader tests."""

from __future__ import annotations

from datetime import UTC, date, datetime
import os

from app.gdac import downloader
from app.gdac.index import GDACProfileEntry


class _FakeStreamResponse:
    def __init__(self, chunks: list[bytes]):
        self._chunks = chunks

    def __enter__(self):
        return self

    def __exit__(self, exc_type, exc, tb):
        return False

    def raise_for_status(self) -> None:
        return None

    def iter_bytes(self, chunk_size: int = 0):
        _ = chunk_size
        for chunk in self._chunks:
            yield chunk


def _entry(file_path: str = "dac/aoml/1234567/profiles/R1234567_001.nc") -> GDACProfileEntry:
    return GDACProfileEntry(
        file_path=file_path,
        date=date(2024, 1, 1),
        latitude=10.0,
        longitude=20.0,
        ocean="I",
        profiler_type="846",
        institution="AOML",
        date_update=datetime(2024, 1, 1, 12, 0, 0, tzinfo=UTC),
    )


def test_file_url_inserts_dac_prefix_when_missing():
    url = downloader._file_url(
        "https://data-argo.ifremer.fr",
        "aoml/4903069/profiles/R4903069_151D.nc",
    )

    assert url == "https://data-argo.ifremer.fr/dac/aoml/4903069/profiles/R4903069_151D.nc"


def test_file_url_preserves_single_dac_prefix():
    url = downloader._file_url(
        "https://data-argo.ifremer.fr/",
        "/dac/aoml/4903069/profiles/R4903069_151D.nc",
    )

    assert url == "https://data-argo.ifremer.fr/dac/aoml/4903069/profiles/R4903069_151D.nc"


def test_download_single_file_retries_then_succeeds(monkeypatch):
    call_counter = {"count": 0}

    def flaky_stream(*args, **kwargs):
        _ = args, kwargs
        call_counter["count"] += 1
        if call_counter["count"] < 3:
            raise RuntimeError("temporary network failure")
        return _FakeStreamResponse([b"abc", b"123"])

    monkeypatch.setattr(downloader.httpx, "stream", flaky_stream)
    monkeypatch.setattr(downloader.time, "sleep", lambda _seconds: None)

    result = downloader._download_single_file(_entry(), "https://mirror.example")

    assert result.success is True
    assert result.attempts == 3
    assert result.temp_file_path is not None
    assert os.path.exists(result.temp_file_path)
    with open(result.temp_file_path, "rb") as handle:
        assert handle.read() == b"abc123"

    os.remove(result.temp_file_path)


def test_download_profile_files_returns_failure_after_retries(monkeypatch):
    def always_fail(*args, **kwargs):
        _ = args, kwargs
        raise RuntimeError("mirror timeout")

    monkeypatch.setattr(downloader.httpx, "stream", always_fail)
    monkeypatch.setattr(downloader.time, "sleep", lambda _seconds: None)

    results = downloader.download_profile_files(
        [_entry()],
        "https://mirror.example",
        max_workers=8,
    )

    assert len(results) == 1
    assert results[0].success is False
    assert results[0].attempts == 3
    assert results[0].temp_file_path is None
    assert "mirror timeout" in (results[0].error or "")
