"""API tests for Feature 15 anomaly endpoints."""

from __future__ import annotations

import uuid
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient

from app.auth.jwt import create_token
from app.db.models import Anomaly, Float, Measurement, Profile, User, mv_float_latest_position


def _auth_header(token: str) -> dict[str, str]:
    return {"Authorization": f"Bearer {token}"}


@pytest.fixture()
def anomaly_client(db_session):
    from app.db.session import get_db, get_readonly_db
    from app.main import app

    def _override_get_db():
        yield db_session

    def _override_get_readonly_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_readonly_db] = _override_get_readonly_db

    # GeoAlchemy can emit AsBinary(...) when selecting Geography columns.
    db_session.connection().connection.create_function("AsBinary", 1, lambda x: x)

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture()
def researcher_user(db_session) -> User:
    user = User(
        user_id=uuid.uuid4(),
        email="researcher@example.com",
        hashed_password="hash",
        name="Researcher",
        role="researcher",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def researcher_headers(researcher_user: User) -> dict[str, str]:
    token = create_token(
        {
            "sub": str(researcher_user.user_id),
            "email": researcher_user.email,
            "role": researcher_user.role,
        },
        token_type="access",
    )
    return _auth_header(token)


@pytest.fixture()
def admin_headers(db_session) -> dict[str, str]:
    admin = User(
        user_id=uuid.uuid4(),
        email="admin@example.com",
        hashed_password="hash",
        name="Admin",
        role="admin",
        is_active=True,
    )
    db_session.add(admin)
    db_session.commit()

    token = create_token(
        {
            "sub": str(admin.user_id),
            "email": admin.email,
            "role": admin.role,
        },
        token_type="access",
    )
    return _auth_header(token)


def _seed_float_profile_anomaly(db_session, *, reviewed: bool = False):
    seed_id = uuid.uuid4().int % 1_000_000_000

    float_row = Float(platform_number="2900001", float_type="core", country="India")
    db_session.add(float_row)
    db_session.flush()

    profile = Profile(
        profile_id=seed_id,
        float_id=float_row.float_id,
        platform_number=float_row.platform_number,
        cycle_number=10,
        timestamp=datetime.now(UTC),
        latitude=10.0,
        longitude=72.0,
        geom="POINT(72 10)",
    )
    db_session.add(profile)
    db_session.flush()

    anomaly = Anomaly(
        float_id=float_row.float_id,
        profile_id=profile.profile_id,
        anomaly_type="spatial_baseline",
        severity="high",
        variable="temperature",
        baseline_value=20.0,
        observed_value=24.0,
        deviation_percent=20.0,
        description="temperature anomaly",
        detected_at=datetime.now(UTC),
        region="Arabian Sea",
        is_reviewed=reviewed,
    )
    db_session.add(anomaly)

    db_session.execute(
        mv_float_latest_position.insert().values(
            platform_number=float_row.platform_number,
            float_id=float_row.float_id,
            cycle_number=profile.cycle_number,
            timestamp=profile.timestamp,
            latitude=profile.latitude,
            longitude=profile.longitude,
            geom="POINT(72 10)",
        )
    )

    db_session.add(
        Measurement(
            measurement_id=seed_id * 10 + 1,
            profile_id=profile.profile_id,
            pressure=5.0,
            temperature=24.0,
            salinity=35.0,
            is_outlier=False,
        )
    )
    db_session.add(
        Measurement(
            measurement_id=seed_id * 10 + 2,
            profile_id=profile.profile_id,
            pressure=15.0,
            temperature=23.8,
            salinity=35.1,
            is_outlier=True,
        )
    )

    db_session.commit()
    db_session.refresh(anomaly)
    return float_row, profile, anomaly


def test_list_anomalies_requires_auth(anomaly_client):
    response = anomaly_client.get("/api/v1/anomalies")
    assert response.status_code == 401


def test_list_anomalies_returns_items(anomaly_client, db_session, researcher_headers):
    _, _, anomaly = _seed_float_profile_anomaly(db_session)

    response = anomaly_client.get("/api/v1/anomalies?days=30", headers=researcher_headers)

    assert response.status_code == 200
    payload = response.json()
    assert payload["total"] == 1
    assert payload["items"][0]["anomaly_id"] == str(anomaly.anomaly_id)
    assert payload["items"][0]["platform_number"] == "2900001"


def test_get_anomaly_detail_returns_measurements(anomaly_client, db_session, researcher_headers):
    _, profile, anomaly = _seed_float_profile_anomaly(db_session)

    response = anomaly_client.get(
        f"/api/v1/anomalies/{anomaly.anomaly_id}",
        headers=researcher_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["profile_id"] == profile.profile_id
    assert len(payload["measurements"]) == 1
    assert payload["baseline_comparison"]["baseline_value"] == 20.0


def test_mark_anomaly_reviewed_updates_fields(anomaly_client, db_session, researcher_user, researcher_headers):
    _, _, anomaly = _seed_float_profile_anomaly(db_session, reviewed=False)

    response = anomaly_client.patch(
        f"/api/v1/anomalies/{anomaly.anomaly_id}/review",
        headers=researcher_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["is_reviewed"] is True
    assert payload["reviewed_by"] == str(researcher_user.user_id)


def test_mark_anomaly_reviewed_rejects_already_reviewed(anomaly_client, db_session, researcher_headers):
    _, _, anomaly = _seed_float_profile_anomaly(db_session, reviewed=True)

    response = anomaly_client.patch(
        f"/api/v1/anomalies/{anomaly.anomaly_id}/review",
        headers=researcher_headers,
    )

    assert response.status_code == 409


def test_compute_baselines_requires_admin(anomaly_client, researcher_headers):
    response = anomaly_client.post(
        "/api/v1/anomalies/baselines/compute",
        headers=researcher_headers,
    )
    assert response.status_code == 403


def test_compute_baselines_admin_success(anomaly_client, admin_headers, monkeypatch):
    from app.api.v1 import anomalies as anomalies_api

    monkeypatch.setattr(
        anomalies_api,
        "compute_all_baselines",
        lambda db: {"upserts": 5, "errors": 0},
    )

    response = anomaly_client.post(
        "/api/v1/anomalies/baselines/compute",
        headers=admin_headers,
    )

    assert response.status_code == 200
    payload = response.json()
    assert payload["message"] == "Baseline computation complete"
    assert payload["summary"]["upserts"] == 5
