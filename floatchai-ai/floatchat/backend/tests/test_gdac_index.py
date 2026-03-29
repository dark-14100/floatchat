"""GDAC index parsing tests."""

from __future__ import annotations

from datetime import UTC, datetime
import gzip
import io

from app.gdac import index


def _gzip_payload(text: str) -> bytes:
    buffer = io.BytesIO()
    with gzip.GzipFile(fileobj=buffer, mode="wb") as gz:
        gz.write(text.encode("utf-8"))
    return buffer.getvalue()


def test_download_and_parse_index_deduplicates_and_parses_stream(monkeypatch):
    global_rows = "\n".join(
        [
            "# profile index",
            "file\tdate\tlatitude\tlongitude\tocean\tprofiler_type\tinstitution\tdate_update",
            "dac/aoml/1234567/profiles/R1234567_001.nc\t20240101\t10.0\t20.0\tI\t846\tAOML\t20240101120000",
            "dac/aoml/7654321/profiles/R7654321_005.nc\t20240102\tinvalid\t20.0\tI\t846\tAOML\t20240102120000",
        ]
    )
    merge_rows = "\n".join(
        [
            "# merge index",
            # Same path as global row but newer date_update should win.
            "dac/aoml/1234567/profiles/R1234567_001.nc,20240101,10.0,20.0,I,846,AOML,20240103120000",
            "dac/coriolis/7654321/profiles/D7654321_005.nc,20240104,11.5,21.5,A,999,CORIOLIS,20240104121212",
        ]
    )

    def fake_download(mirror_url: str, index_filename: str) -> bytes:
        assert mirror_url == "https://primary.example"
        if index_filename == index.GLOBAL_PROFILE_INDEX:
            return _gzip_payload(global_rows)
        if index_filename == index.MERGE_PROFILE_INDEX:
            return _gzip_payload(merge_rows)
        raise AssertionError(f"Unexpected index filename: {index_filename}")

    monkeypatch.setattr(index, "_download_index_bytes", fake_download)

    entries, used_mirror = index.download_and_parse_index_with_mirror("https://primary.example")

    assert used_mirror == "https://primary.example"
    assert len(entries) == 2

    by_path = {entry.file_path: entry for entry in entries}
    merged = by_path["dac/aoml/1234567/profiles/R1234567_001.nc"]
    unique = by_path["dac/coriolis/7654321/profiles/D7654321_005.nc"]

    assert merged.date_update == datetime(2024, 1, 3, 12, 0, 0, tzinfo=UTC)
    assert unique.ocean == "A"
    assert unique.latitude == 11.5
    assert unique.longitude == 21.5


def test_download_and_parse_index_fails_over_to_secondary(monkeypatch):
    calls: list[tuple[str, str]] = []
    payload = _gzip_payload(
        "# idx\n"
        "dac/aoml/1234567/profiles/R1234567_001.nc\t20240101\t10.0\t20.0\tI\t846\tAOML\t20240101120000\n"
    )

    monkeypatch.setattr(index.settings, "GDAC_SECONDARY_MIRROR", "https://secondary.example")

    def fake_download(mirror_url: str, index_filename: str) -> bytes:
        calls.append((mirror_url, index_filename))
        if mirror_url == "https://primary.example":
            raise RuntimeError("primary unavailable")
        return payload

    monkeypatch.setattr(index, "_download_index_bytes", fake_download)

    entries, used_mirror = index.download_and_parse_index_with_mirror("https://primary.example")

    assert used_mirror == "https://secondary.example"
    assert len(entries) == 1
    assert any(mirror == "https://primary.example" for mirror, _ in calls)
    assert any(mirror == "https://secondary.example" for mirror, _ in calls)


def test_download_and_parse_index_skips_merge_without_mirror_failover(monkeypatch):
    calls: list[tuple[str, str]] = []
    global_payload = _gzip_payload(
        "# idx\n"
        "dac/aoml/1234567/profiles/R1234567_001.nc\t20240101\t10.0\t20.0\tI\t846\tAOML\t20240101120000\n"
    )

    monkeypatch.setattr(index.settings, "GDAC_SECONDARY_MIRROR", "https://secondary.example")

    def fake_download(mirror_url: str, index_filename: str) -> bytes:
        calls.append((mirror_url, index_filename))
        if mirror_url == "https://secondary.example":
            raise AssertionError("secondary mirror should not be used")

        if index_filename == index.GLOBAL_PROFILE_INDEX:
            return global_payload

        if index_filename == index.MERGE_PROFILE_INDEX:
            raise RuntimeError("404 Not Found")

        raise AssertionError(f"Unexpected index filename: {index_filename}")

    monkeypatch.setattr(index, "_download_index_bytes", fake_download)

    entries, used_mirror = index.download_and_parse_index_with_mirror("https://primary.example")

    assert used_mirror == "https://primary.example"
    assert len(entries) == 1
    assert all(mirror == "https://primary.example" for mirror, _ in calls)
    assert (
        "https://primary.example",
        index.GLOBAL_PROFILE_INDEX,
    ) in calls
    assert (
        "https://primary.example",
        index.MERGE_PROFILE_INDEX,
    ) in calls
