"""GDAC index parsing tests."""

from __future__ import annotations

from datetime import UTC, datetime

from app.gdac import index


def test_download_and_parse_index_parses_stream(monkeypatch):
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

    def fake_probe(mirror_url: str, index_filename: str) -> None:
        assert mirror_url == "https://primary.example"

    def fake_stream(mirror_url: str, index_filename: str):
        assert mirror_url == "https://primary.example"
        if index_filename == index.GLOBAL_PROFILE_INDEX:
            return iter(global_rows.splitlines())
        if index_filename == index.MERGE_PROFILE_INDEX:
            return iter(merge_rows.splitlines())
        raise AssertionError(f"Unexpected index filename: {index_filename}")

    monkeypatch.setattr(index, "_probe_index_availability", fake_probe)
    monkeypatch.setattr(index, "_iter_streamed_gzip_lines", fake_stream)

    entries_iter, used_mirror = index.download_and_parse_index_with_mirror("https://primary.example")
    entries = list(entries_iter)

    assert used_mirror == "https://primary.example"
    assert len(entries) == 3

    duplicates = [
        entry for entry in entries if entry.file_path == "dac/aoml/1234567/profiles/R1234567_001.nc"
    ]
    unique = [entry for entry in entries if entry.file_path == "dac/coriolis/7654321/profiles/D7654321_005.nc"]

    assert len(duplicates) == 2
    assert max(duplicates, key=lambda entry: entry.date_update).date_update == datetime(
        2024, 1, 3, 12, 0, 0, tzinfo=UTC
    )
    assert len(unique) == 1
    assert unique[0].ocean == "A"
    assert unique[0].latitude == 11.5
    assert unique[0].longitude == 21.5


def test_download_and_parse_index_fails_over_to_secondary(monkeypatch):
    probe_calls: list[tuple[str, str]] = []
    stream_calls: list[tuple[str, str]] = []
    rows = [
        "# idx",
        "dac/aoml/1234567/profiles/R1234567_001.nc\t20240101\t10.0\t20.0\tI\t846\tAOML\t20240101120000",
    ]

    monkeypatch.setattr(index.settings, "GDAC_SECONDARY_MIRROR", "https://secondary.example")

    def fake_probe(mirror_url: str, index_filename: str) -> None:
        probe_calls.append((mirror_url, index_filename))
        if mirror_url == "https://primary.example":
            raise RuntimeError("primary unavailable")

    def fake_stream(mirror_url: str, index_filename: str):
        stream_calls.append((mirror_url, index_filename))
        if mirror_url == "https://primary.example":
            raise AssertionError("primary stream should not be used after probe failure")
        if index_filename == index.GLOBAL_PROFILE_INDEX:
            return iter(rows)
        if index_filename == index.MERGE_PROFILE_INDEX:
            return iter([])
        raise AssertionError(f"Unexpected index filename: {index_filename}")

    monkeypatch.setattr(index, "_probe_index_availability", fake_probe)
    monkeypatch.setattr(index, "_iter_streamed_gzip_lines", fake_stream)

    entries_iter, used_mirror = index.download_and_parse_index_with_mirror("https://primary.example")
    entries = list(entries_iter)

    assert used_mirror == "https://secondary.example"
    assert len(entries) == 1
    assert any(mirror == "https://primary.example" for mirror, _ in probe_calls)
    assert any(mirror == "https://secondary.example" for mirror, _ in probe_calls)
    assert all(mirror == "https://secondary.example" for mirror, _ in stream_calls)


def test_download_and_parse_index_skips_merge_without_mirror_failover(monkeypatch):
    probe_calls: list[tuple[str, str]] = []
    stream_calls: list[tuple[str, str]] = []
    global_rows = [
        "# idx",
        "dac/aoml/1234567/profiles/R1234567_001.nc\t20240101\t10.0\t20.0\tI\t846\tAOML\t20240101120000",
    ]

    monkeypatch.setattr(index.settings, "GDAC_SECONDARY_MIRROR", "https://secondary.example")

    def fake_probe(mirror_url: str, index_filename: str) -> None:
        probe_calls.append((mirror_url, index_filename))
        if mirror_url == "https://secondary.example":
            raise AssertionError("secondary mirror should not be used")

    def fake_stream(mirror_url: str, index_filename: str):
        stream_calls.append((mirror_url, index_filename))
        if mirror_url == "https://secondary.example":
            raise AssertionError("secondary mirror should not be used")

        if index_filename == index.GLOBAL_PROFILE_INDEX:
            return iter(global_rows)

        if index_filename == index.MERGE_PROFILE_INDEX:
            raise RuntimeError("404 Not Found")

        raise AssertionError(f"Unexpected index filename: {index_filename}")

    monkeypatch.setattr(index, "_probe_index_availability", fake_probe)
    monkeypatch.setattr(index, "_iter_streamed_gzip_lines", fake_stream)

    entries_iter, used_mirror = index.download_and_parse_index_with_mirror("https://primary.example")
    entries = list(entries_iter)

    assert used_mirror == "https://primary.example"
    assert len(entries) == 1
    assert all(mirror == "https://primary.example" for mirror, _ in probe_calls)
    assert all(mirror == "https://primary.example" for mirror, _ in stream_calls)
    assert (
        "https://primary.example",
        index.GLOBAL_PROFILE_INDEX,
    ) in stream_calls
    assert (
        "https://primary.example",
        index.MERGE_PROFILE_INDEX,
    ) in stream_calls
