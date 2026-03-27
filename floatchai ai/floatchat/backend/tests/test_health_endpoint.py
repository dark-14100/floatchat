from __future__ import annotations

import time

from app.api.v1 import health as health_module


def test_health_endpoint_returns_within_budget(client, monkeypatch):
    async def _ok_db():
        return health_module._ComponentResult(status="ok")

    async def _ok_redis():
        return health_module._ComponentResult(status="ok")

    async def _ok_celery():
        return health_module._ComponentResult(status="ok")

    monkeypatch.setattr(health_module, "_check_db", _ok_db)
    monkeypatch.setattr(health_module, "_check_redis", _ok_redis)
    monkeypatch.setattr(health_module, "_check_celery", _ok_celery)

    started = time.perf_counter()
    response = client.get("/api/v1/health")
    elapsed = time.perf_counter() - started

    assert response.status_code == 200
    payload = response.json()
    assert payload["status"] == "ok"
    assert payload["db"] == "ok"
    assert payload["redis"] == "ok"
    assert payload["celery"] == "ok"
    assert elapsed < 3.0


def test_health_endpoint_returns_503_when_db_unreachable(client, monkeypatch):
    async def _error_db():
        return health_module._ComponentResult(status="error", message="db_unreachable")

    async def _ok_redis():
        return health_module._ComponentResult(status="ok")

    async def _ok_celery():
        return health_module._ComponentResult(status="ok")

    monkeypatch.setattr(health_module, "_check_db", _error_db)
    monkeypatch.setattr(health_module, "_check_redis", _ok_redis)
    monkeypatch.setattr(health_module, "_check_celery", _ok_celery)

    response = client.get("/api/v1/health")

    assert response.status_code == 503
    payload = response.json()
    assert payload["status"] == "error"
    assert payload["db"] == "error"
    assert payload.get("db_message") == "db_unreachable"
