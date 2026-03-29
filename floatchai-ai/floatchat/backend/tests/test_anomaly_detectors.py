"""Unit tests for Feature 15 anomaly detectors."""

from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from unittest.mock import MagicMock

from app.anomaly import detectors
from app.db.models import Anomaly, AnomalyBaseline


def _scalar_result(value):
    result = MagicMock()
    result.scalar_one_or_none.return_value = value
    return result


def _scalars_result(values):
    result = MagicMock()
    scalars = MagicMock()
    scalars.all.return_value = values
    result.scalars.return_value = scalars
    return result


def _one_result(row):
    result = MagicMock()
    result.one.return_value = row
    return result


def _all_result(rows):
    result = MagicMock()
    result.all.return_value = rows
    return result


def _profile(profile_id: int, float_id: int, timestamp: datetime) -> SimpleNamespace:
    return SimpleNamespace(
        profile_id=profile_id,
        float_id=float_id,
        timestamp=timestamp,
        geom="POINT(72 10)",
        latitude=10.0,
        longitude=72.0,
    )


def _seed_anomaly(float_id: int, profile_id: int, variable: str, detected_at: datetime) -> Anomaly:
    return Anomaly(
        float_id=float_id,
        profile_id=profile_id,
        anomaly_type="spatial_baseline",
        severity="high",
        variable=variable,
        baseline_value=20.0,
        observed_value=25.0,
        deviation_percent=25.0,
        description="seed",
        detected_at=detected_at,
        region="Arabian Sea",
    )


def test_spatial_baseline_detector_flags_anomaly(monkeypatch):
    detector = detectors.SpatialBaselineDetector()
    profile = _profile(101, 11, datetime(2026, 3, 1, tzinfo=UTC))

    monkeypatch.setattr(detectors, "_get_profile_observed_values", lambda db, pid: {"temperature": 25.0})
    monkeypatch.setattr(detectors, "_resolve_nearest_region_name", lambda db, p: "Arabian Sea")
    monkeypatch.setattr(detectors, "_anomaly_exists", lambda *args: False)

    db = MagicMock()
    db.execute.return_value = _one_result(
        SimpleNamespace(baseline=20.0, std_dev=1.0, comparison_profiles=12)
    )

    anomalies = detector.run([profile], db)

    assert len(anomalies) == 1
    anomaly = anomalies[0]
    assert anomaly.anomaly_type == "spatial_baseline"
    assert anomaly.variable == "temperature"
    assert anomaly.severity == "high"


def test_float_self_comparison_detector_respects_min_profiles(monkeypatch):
    detector = detectors.FloatSelfComparisonDetector()
    profile = _profile(102, 12, datetime(2026, 3, 2, tzinfo=UTC))

    monkeypatch.setattr(detectors, "_get_profile_observed_values", lambda db, pid: {"temperature": 22.0})
    monkeypatch.setattr(detectors, "_resolve_nearest_region_name", lambda db, p: "Arabian Sea")
    monkeypatch.setattr(detectors, "_anomaly_exists", lambda *args: False)

    db = MagicMock()
    db.execute.side_effect = [
        _scalars_result([1, 2, 3, 4]),
        _one_result(SimpleNamespace(baseline=20.0, std_dev=1.0, comparison_profiles=4)),
    ]

    anomalies = detector.run([profile], db)

    assert anomalies == []


def test_float_self_comparison_detector_flags_anomaly(monkeypatch):
    detector = detectors.FloatSelfComparisonDetector()
    profile = _profile(103, 13, datetime(2026, 3, 3, tzinfo=UTC))

    monkeypatch.setattr(detectors, "_get_profile_observed_values", lambda db, pid: {"temperature": 25.0})
    monkeypatch.setattr(detectors, "_resolve_nearest_region_name", lambda db, p: "Arabian Sea")
    monkeypatch.setattr(detectors, "_anomaly_exists", lambda *args: False)

    db = MagicMock()
    db.execute.side_effect = [
        _scalars_result([10, 11, 12, 13, 14]),
        _one_result(SimpleNamespace(baseline=20.0, std_dev=1.0, comparison_profiles=5)),
    ]

    anomalies = detector.run([profile], db)

    assert len(anomalies) == 1
    assert anomalies[0].anomaly_type == "float_self_comparison"


def test_seasonal_detector_skips_when_baseline_missing(monkeypatch):
    detector = detectors.SeasonalBaselineDetector()
    profile = _profile(104, 14, datetime(2026, 3, 4, tzinfo=UTC))

    monkeypatch.setattr(detectors, "_resolve_nearest_region_name", lambda db, p: "Arabian Sea")
    monkeypatch.setattr(detectors, "_get_profile_observed_values", lambda db, pid: {"temperature": 25.0})

    db = MagicMock()
    db.execute.return_value = _scalar_result(None)

    anomalies = detector.run([profile], db)

    assert anomalies == []


def test_seasonal_detector_flags_anomaly(monkeypatch):
    detector = detectors.SeasonalBaselineDetector()
    profile = _profile(105, 15, datetime(2026, 3, 5, tzinfo=UTC))

    baseline = AnomalyBaseline(
        region="Arabian Sea",
        variable="temperature",
        month=3,
        mean_value=20.0,
        std_dev=1.0,
        sample_count=35,
    )

    monkeypatch.setattr(detectors, "_resolve_nearest_region_name", lambda db, p: "Arabian Sea")
    monkeypatch.setattr(detectors, "_get_profile_observed_values", lambda db, pid: {"temperature": 24.0})
    monkeypatch.setattr(detectors, "_anomaly_exists", lambda *args: False)

    db = MagicMock()
    db.execute.return_value = _scalar_result(baseline)

    anomalies = detector.run([profile], db)

    assert len(anomalies) == 1
    assert anomalies[0].anomaly_type == "seasonal_baseline"


def test_cluster_pattern_detector_creates_anomaly_per_float(monkeypatch):
    detector = detectors.ClusterPatternDetector()
    now = datetime.now(UTC)

    a1 = _seed_anomaly(21, 201, "temperature", now)
    a2 = _seed_anomaly(22, 202, "temperature", now - timedelta(hours=2))
    a3 = _seed_anomaly(23, 203, "temperature", now - timedelta(hours=4))

    monkeypatch.setattr(detectors, "_anomaly_exists", lambda *args: False)

    db = MagicMock()
    db.execute.return_value = _all_result(
        [
            SimpleNamespace(profile_id=201, latitude=10.0, longitude=72.0),
            SimpleNamespace(profile_id=202, latitude=10.2, longitude=72.2),
            SimpleNamespace(profile_id=203, latitude=10.3, longitude=72.1),
        ]
    )

    anomalies = detector.run([], db, [a1, a2, a3])

    assert len(anomalies) == 3
    assert {a.anomaly_type for a in anomalies} == {"cluster_pattern"}


def test_cluster_pattern_detector_skips_when_cluster_too_small(monkeypatch):
    detector = detectors.ClusterPatternDetector()
    now = datetime.now(UTC)

    a1 = _seed_anomaly(31, 301, "temperature", now)
    a2 = _seed_anomaly(32, 302, "temperature", now)

    monkeypatch.setattr(detectors, "_anomaly_exists", lambda *args: False)

    db = MagicMock()
    db.execute.return_value = _all_result(
        [
            SimpleNamespace(profile_id=301, latitude=10.0, longitude=72.0),
            SimpleNamespace(profile_id=302, latitude=10.1, longitude=72.0),
        ]
    )

    anomalies = detector.run([], db, [a1, a2])

    assert anomalies == []


def test_detector_returns_empty_on_internal_error(monkeypatch):
    detector = detectors.SpatialBaselineDetector()
    profile = _profile(401, 41, datetime(2026, 3, 6, tzinfo=UTC))

    def _boom(*args, **kwargs):
        raise RuntimeError("boom")

    monkeypatch.setattr(detectors, "_get_profile_observed_values", _boom)

    db = MagicMock()

    anomalies = detector.run([profile], db)

    assert anomalies == []
