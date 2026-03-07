"""Task orchestration tests for Feature 15 anomaly scanning."""

from __future__ import annotations

from datetime import UTC, datetime
from types import SimpleNamespace

from app.anomaly import tasks
from app.db.models import Anomaly


class _ScalarListResult:
    def __init__(self, values):
        self._values = values

    def scalars(self):
        return self

    def all(self):
        return self._values


class _DummyDB:
    def __init__(self, profiles):
        self._profiles = profiles
        self.added = []
        self.commits = 0
        self.rollbacks = 0
        self.closed = False

    def execute(self, stmt):
        return _ScalarListResult(self._profiles)

    def add_all(self, rows):
        self.added.extend(rows)

    def commit(self):
        self.commits += 1

    def rollback(self):
        self.rollbacks += 1

    def close(self):
        self.closed = True


class _Detector:
    def __init__(self, rows):
        self._rows = rows

    def run(self, *args, **kwargs):
        return list(self._rows)


class _ExplodingDetector:
    def run(self, *args, **kwargs):
        raise RuntimeError("detector failure")


def _seed_anomaly(float_id: int, profile_id: int, anomaly_type: str) -> Anomaly:
    return Anomaly(
        float_id=float_id,
        profile_id=profile_id,
        anomaly_type=anomaly_type,
        severity="high",
        variable="temperature",
        baseline_value=20.0,
        observed_value=24.0,
        deviation_percent=20.0,
        description=f"{anomaly_type} anomaly",
        detected_at=datetime.now(UTC),
        region="Arabian Sea",
    )


def test_run_anomaly_scan_skips_when_disabled(monkeypatch):
    monkeypatch.setattr(tasks.settings, "ANOMALY_SCAN_ENABLED", False)

    db = _DummyDB([])
    monkeypatch.setattr(tasks, "SessionLocal", lambda: db)

    result = tasks.run_anomaly_scan.run()

    assert result["success"] is True
    assert result["scan_enabled"] is False
    assert result["created"] == 0
    assert db.commits == 0
    assert db.closed is True


def test_run_anomaly_scan_handles_cold_start_without_profiles(monkeypatch):
    monkeypatch.setattr(tasks.settings, "ANOMALY_SCAN_ENABLED", True)

    db = _DummyDB([])
    monkeypatch.setattr(tasks, "SessionLocal", lambda: db)

    result = tasks.run_anomaly_scan.run()

    assert result["success"] is True
    assert result["profiles_scanned"] == 0
    assert result["created"] == 0
    assert result["detectors"]["spatial_baseline"] == 0
    assert db.commits == 0


def test_run_anomaly_scan_commits_once_with_dedup(monkeypatch):
    monkeypatch.setattr(tasks.settings, "ANOMALY_SCAN_ENABLED", True)

    profile = SimpleNamespace(profile_id=101, float_id=11, created_at=datetime.now(UTC))
    db = _DummyDB([profile])
    monkeypatch.setattr(tasks, "SessionLocal", lambda: db)

    spatial = _seed_anomaly(11, 101, "spatial_baseline")
    duplicate_spatial = _seed_anomaly(11, 101, "spatial_baseline")
    seasonal = _seed_anomaly(11, 101, "seasonal_baseline")
    cluster = _seed_anomaly(11, 101, "cluster_pattern")

    monkeypatch.setattr(tasks, "SpatialBaselineDetector", lambda: _Detector([spatial, duplicate_spatial]))
    monkeypatch.setattr(tasks, "FloatSelfComparisonDetector", lambda: _Detector([]))
    monkeypatch.setattr(tasks, "SeasonalBaselineDetector", lambda: _Detector([seasonal]))
    monkeypatch.setattr(tasks, "ClusterPatternDetector", lambda: _Detector([cluster]))

    result = tasks.run_anomaly_scan.run()

    assert result["success"] is True
    assert result["created"] == 3
    assert db.commits == 1
    assert len(db.added) == 3
    assert db.closed is True


def test_run_anomaly_scan_isolates_detector_failures(monkeypatch):
    monkeypatch.setattr(tasks.settings, "ANOMALY_SCAN_ENABLED", True)

    profile = SimpleNamespace(profile_id=102, float_id=12, created_at=datetime.now(UTC))
    db = _DummyDB([profile])
    monkeypatch.setattr(tasks, "SessionLocal", lambda: db)

    seasonal = _seed_anomaly(12, 102, "seasonal_baseline")
    cluster = _seed_anomaly(12, 102, "cluster_pattern")

    monkeypatch.setattr(tasks, "SpatialBaselineDetector", lambda: _ExplodingDetector())
    monkeypatch.setattr(tasks, "FloatSelfComparisonDetector", lambda: _Detector([]))
    monkeypatch.setattr(tasks, "SeasonalBaselineDetector", lambda: _Detector([seasonal]))
    monkeypatch.setattr(tasks, "ClusterPatternDetector", lambda: _Detector([cluster]))

    result = tasks.run_anomaly_scan.run()

    assert result["success"] is True
    assert result["detectors"]["spatial_baseline"] == 0
    assert result["detectors"]["seasonal_baseline"] == 1
    assert result["detectors"]["cluster_pattern"] == 1
    assert result["created"] == 2
    assert db.commits == 1
