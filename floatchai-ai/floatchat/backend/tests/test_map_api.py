"""
Tests for app.api.v1.map — Feature 7 geospatial map endpoints.

These tests use FastAPI dependency overrides + mocked DB/Redis interactions
for deterministic coverage of endpoint behavior and payload shapes.
"""

import json
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient

from app.api.v1 import map as map_api


@pytest.fixture()
def map_client(db_session, auth_user):
    """TestClient overriding readonly DB with mock and auth DB with sqlite session."""
    from app.db.session import get_db, get_readonly_db
    from app.main import app

    del auth_user

    db = MagicMock()

    def _override_get_db():
        yield db_session

    def _override_get_readonly_db():
        yield db

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_readonly_db] = _override_get_readonly_db

    with TestClient(app) as client:
        yield client, db

    app.dependency_overrides.clear()


class TestActiveFloats:
    def test_active_floats_returns_cached_payload(self, map_client, auth_headers, monkeypatch: pytest.MonkeyPatch):
        client, db = map_client

        cached_payload = [
            {
                "platform_number": "FCTEST001",
                "float_type": "core",
                "latitude": 10.0,
                "longitude": 72.0,
                "last_seen": "2024-06-15T00:00:00+00:00",
            }
        ]

        redis_client = MagicMock()
        redis_client.get.return_value = json.dumps(cached_payload)
        monkeypatch.setattr(map_api, "_get_redis_client", lambda: redis_client)

        resp = client.get("/api/v1/map/active-floats", headers=auth_headers)

        assert resp.status_code == 200
        assert resp.json() == cached_payload
        db.execute.assert_not_called()


class TestNearestFloats:
    def test_nearest_floats_rejects_invalid_latitude(self, map_client, auth_headers):
        client, _ = map_client

        resp = client.get("/api/v1/map/nearest-floats?lat=95&lon=72", headers=auth_headers)

        assert resp.status_code == 400
        assert "Latitude" in resp.json()["detail"]


class TestRadiusQuery:
    def test_radius_query_rejects_excessive_radius(self, map_client, auth_headers):
        client, _ = map_client

        resp = client.post(
            "/api/v1/map/radius-query",
            json={"lat": 10.0, "lon": 72.0, "radius_km": 999999},
            headers=auth_headers,
        )

        assert resp.status_code == 400
        assert "exceeds maximum" in resp.json()["detail"]

    def test_radius_query_returns_counts_and_bbox(self, map_client, auth_headers, monkeypatch: pytest.MonkeyPatch):
        client, _ = map_client

        profiles = [
            {
                "platform_number": "FCTEST001",
                "latitude": 10.0,
                "longitude": 72.0,
            },
            {
                "platform_number": "FCTEST002",
                "latitude": 11.0,
                "longitude": 73.0,
            },
        ]
        monkeypatch.setattr(map_api, "get_profiles_by_radius", lambda *args, **kwargs: profiles)

        resp = client.post(
            "/api/v1/map/radius-query",
            json={"lat": 10.5, "lon": 72.5, "radius_km": 150},
            headers=auth_headers,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["profile_count"] == 2
        assert body["float_count"] == 2
        assert body["bbox"]["type"] == "Polygon"
        assert len(body["profiles"]) == 2


class TestFloatDetail:
    def test_float_detail_not_found(self, map_client, auth_headers):
        client, db = map_client

        first_query = MagicMock()
        first_query.one_or_none.return_value = None
        db.execute.return_value = first_query

        resp = client.get("/api/v1/map/floats/UNKNOWN123", headers=auth_headers)

        assert resp.status_code == 404
        assert "not found" in resp.json()["detail"]


class TestBasinFloats:
    def test_basin_floats_invalid_region_returns_400(self, map_client, auth_headers, monkeypatch: pytest.MonkeyPatch):
        client, _ = map_client

        def _raise(*args, **kwargs):
            raise ValueError("No matching region")

        monkeypatch.setattr(map_api, "resolve_region_name", _raise)

        resp = client.get("/api/v1/map/basin-floats?basin_name=unknown", headers=auth_headers)

        assert resp.status_code == 400
        assert "No matching region" in resp.json()["detail"]

    def test_basin_floats_returns_rows(self, map_client, auth_headers, monkeypatch: pytest.MonkeyPatch):
        client, db = map_client

        region = SimpleNamespace(region_name="Arabian Sea", geom="fake-geom")
        monkeypatch.setattr(map_api, "resolve_region_name", lambda *args, **kwargs: region)

        query_result = MagicMock()
        query_result.all.return_value = [
            SimpleNamespace(
                float_id=1,
                platform_number="FCTEST001",
                float_type="core",
                latitude=10.0,
                longitude=72.0,
                timestamp=datetime(2024, 6, 15, tzinfo=timezone.utc),
            )
        ]
        db.execute.return_value = query_result

        resp = client.get("/api/v1/map/basin-floats?basin_name=arabian", headers=auth_headers)

        assert resp.status_code == 200
        body = resp.json()
        assert len(body) == 1
        assert body[0]["platform_number"] == "FCTEST001"
        assert body[0]["float_type"] == "core"


class TestBasinPolygons:
    def test_basin_polygons_returns_feature_collection_and_caches(
        self,
        map_client,
        auth_headers,
        monkeypatch: pytest.MonkeyPatch,
    ):
        client, db = map_client

        redis_client = MagicMock()
        redis_client.get.return_value = None
        monkeypatch.setattr(map_api, "_get_redis_client", lambda: redis_client)

        query_result = MagicMock()
        query_result.all.return_value = [
            SimpleNamespace(
                region_id=10,
                region_name="Arabian Sea",
                geojson=json.dumps(
                    {
                        "type": "Polygon",
                        "coordinates": [[[50.0, 0.0], [80.0, 0.0], [80.0, 30.0], [50.0, 30.0], [50.0, 0.0]]],
                    }
                ),
            ),
            SimpleNamespace(region_id=11, region_name="Null Geometry", geojson=None),
        ]
        db.execute.return_value = query_result

        resp = client.get("/api/v1/map/basin-polygons", headers=auth_headers)

        assert resp.status_code == 200
        body = resp.json()
        assert body["type"] == "FeatureCollection"
        assert len(body["features"]) == 1
        assert body["features"][0]["properties"]["region_name"] == "Arabian Sea"
        redis_client.set.assert_called_once()
