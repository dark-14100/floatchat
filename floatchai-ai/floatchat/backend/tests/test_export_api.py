"""Tests for app.api.v1.export — Feature 8 export API endpoints."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from types import SimpleNamespace
from unittest.mock import MagicMock

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.api.v1 import export as export_api
from app.auth.jwt import create_token
from app.db.models import ChatMessage, ChatSession, User


def _create_chat_message(
    db_session: Session,
    owner_user_id: str,
    *,
    row_count: int = 2,
    columns: list[str] | None = None,
) -> ChatMessage:
    session = ChatSession(
        session_id=uuid.uuid4(),
        user_identifier=owner_user_id,
        name="Export Session",
    )
    message = ChatMessage(
        message_id=uuid.uuid4(),
        session_id=session.session_id,
        role="assistant",
        content="Result payload",
        nl_query="show salinity in 2024",
        result_metadata={
            "row_count": row_count,
            "columns": columns or ["profile_id", "pressure", "temperature"],
        },
    )
    db_session.add_all([session, message])
    db_session.commit()
    db_session.refresh(message)
    return message


def _export_request_body(message_id: str, export_format: str = "csv") -> dict:
    return {
        "message_id": message_id,
        "format": export_format,
        "rows": [
            {"profile_id": 101, "pressure": 5.0, "temperature": 26.7},
            {"profile_id": 102, "pressure": 25.0, "temperature": 24.1},
        ],
    }


@pytest.fixture()
def other_auth_headers(db_session: Session) -> dict[str, str]:
    other_user = User(
        user_id=uuid.uuid4(),
        email="other-user@example.com",
        hashed_password="test-hash",
        name="Other User",
        role="researcher",
        is_active=True,
    )
    db_session.add(other_user)
    db_session.commit()
    db_session.refresh(other_user)

    token = create_token(
        {
            "sub": str(other_user.user_id),
            "email": other_user.email,
            "role": other_user.role,
        },
        token_type="access",
    )
    return {"Authorization": f"Bearer {token}"}


class TestCreateExport:
    def test_requires_auth(self, client: TestClient):
        body = _export_request_body(str(uuid.uuid4()))
        resp = client.post("/api/v1/export", json=body)
        assert resp.status_code == 401

    def test_rejects_non_owner(self, client: TestClient, db_session: Session, auth_user: User, other_auth_headers: dict[str, str]):
        message = _create_chat_message(db_session, str(auth_user.user_id))

        resp = client.post(
            "/api/v1/export",
            json=_export_request_body(str(message.message_id)),
            headers=other_auth_headers,
        )

        assert resp.status_code == 403
        assert "do not have access" in resp.json()["detail"]

    def test_sync_csv_returns_gzip_attachment(
        self,
        client: TestClient,
        db_session: Session,
        auth_user: User,
        auth_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ):
        message = _create_chat_message(db_session, str(auth_user.user_id))

        expected_payload = b"profile_id,pressure,temperature\n101,5.0,26.7\n"
        monkeypatch.setattr(export_api, "estimate_export_size_bytes", lambda **kwargs: 1024)
        monkeypatch.setattr(export_api, "should_use_async_export", lambda **kwargs: False)
        monkeypatch.setattr(export_api, "_generate_export_bytes", lambda **kwargs: expected_payload)

        resp = client.post(
            "/api/v1/export",
            json=_export_request_body(str(message.message_id), "csv"),
            headers=auth_headers,
        )

        assert resp.status_code == 200
        assert resp.headers.get("content-encoding") == "gzip"
        assert "attachment; filename=\"floatchat_csv_" in resp.headers.get("content-disposition", "")
        assert resp.content == expected_payload

    def test_async_export_queues_task_and_returns_poll_url(
        self,
        client: TestClient,
        db_session: Session,
        auth_user: User,
        auth_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ):
        message = _create_chat_message(db_session, str(auth_user.user_id))

        redis_client = MagicMock()
        delay_mock = MagicMock()

        monkeypatch.setattr(export_api, "estimate_export_size_bytes", lambda **kwargs: 1024)
        monkeypatch.setattr(export_api, "should_use_async_export", lambda **kwargs: True)
        monkeypatch.setattr(export_api, "_get_redis_client", lambda: redis_client)
        monkeypatch.setattr(export_api, "generate_export_task", SimpleNamespace(delay=delay_mock))

        resp = client.post(
            "/api/v1/export",
            json=_export_request_body(str(message.message_id), "json"),
            headers=auth_headers,
        )

        assert resp.status_code == 200
        body = resp.json()
        assert body["status"] == "queued"
        assert body["task_id"]
        assert body["poll_url"].endswith(body["task_id"])

        uuid.UUID(body["task_id"])
        assert redis_client.setex.call_count == 2
        delay_mock.assert_called_once()
        assert delay_mock.call_args.kwargs["task_id"] == body["task_id"]
        assert delay_mock.call_args.kwargs["user_id"] == str(auth_user.user_id)

    def test_returns_413_when_estimated_size_exceeds_limit(
        self,
        client: TestClient,
        db_session: Session,
        auth_user: User,
        auth_headers: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ):
        message = _create_chat_message(db_session, str(auth_user.user_id))

        monkeypatch.setattr(export_api, "estimate_export_size_bytes", lambda **kwargs: 600 * 1024 * 1024)

        resp = client.post(
            "/api/v1/export",
            json=_export_request_body(str(message.message_id), "netcdf"),
            headers=auth_headers,
        )

        assert resp.status_code == 413
        body = resp.json()
        assert body["error"] == "Export too large"
        assert "500MB limit" in body["detail"]


class TestExportStatus:
    def test_returns_status_payload(self, client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch):
        redis_client = MagicMock()
        redis_client.get.return_value = json.dumps(
            {
                "task_id": "abc-task",
                "status": "complete",
                "download_url": "https://example.com/export.csv",
                "expires_at": datetime.now(timezone.utc).isoformat(),
                "error": None,
            }
        )
        monkeypatch.setattr(export_api, "_get_redis_client", lambda: redis_client)

        resp = client.get("/api/v1/export/status/abc-task", headers=auth_headers)

        assert resp.status_code == 200
        body = resp.json()
        assert body["task_id"] == "abc-task"
        assert body["status"] == "complete"
        assert body["download_url"] == "https://example.com/export.csv"

    def test_returns_404_for_unknown_task(self, client: TestClient, auth_headers: dict[str, str], monkeypatch: pytest.MonkeyPatch):
        redis_client = MagicMock()
        redis_client.get.return_value = None
        monkeypatch.setattr(export_api, "_get_redis_client", lambda: redis_client)

        resp = client.get("/api/v1/export/status/missing-task", headers=auth_headers)

        assert resp.status_code == 404
        assert resp.json()["detail"] == "Task not found"
