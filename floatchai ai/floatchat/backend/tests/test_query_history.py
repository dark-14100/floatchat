"""Tests for Feature 9 query history endpoint."""

from datetime import datetime, timedelta, timezone
import uuid

from fastapi.testclient import TestClient

from app.db.models import QueryHistory, User


def _vector() -> list[float]:
    return [0.0] * 1536


class TestQueryHistoryEndpoint:
    def test_requires_auth(self, client: TestClient):
        response = client.get("/api/v1/chat/query-history")
        assert response.status_code == 401

    def test_returns_current_user_history_only(self, client: TestClient, db_session, auth_user: User, auth_headers: dict[str, str]):
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

        now = datetime.now(timezone.utc)
        db_session.add_all(
            [
                QueryHistory(
                    nl_query="show temperature in indian ocean",
                    generated_sql="SELECT 1",
                    embedding=_vector(),
                    row_count=10,
                    user_id=auth_user.user_id,
                    provider="deepseek",
                    model="deepseek-reasoner",
                    created_at=now,
                ),
                QueryHistory(
                    nl_query="show salinity in arabian sea",
                    generated_sql="SELECT 2",
                    embedding=_vector(),
                    row_count=12,
                    user_id=auth_user.user_id,
                    provider="deepseek",
                    model="deepseek-reasoner",
                    created_at=now - timedelta(minutes=1),
                ),
                QueryHistory(
                    nl_query="show oxygen in pacific",
                    generated_sql="SELECT 3",
                    embedding=_vector(),
                    row_count=8,
                    user_id=other_user.user_id,
                    provider="deepseek",
                    model="deepseek-reasoner",
                    created_at=now - timedelta(minutes=2),
                ),
            ]
        )
        db_session.commit()

        response = client.get("/api/v1/chat/query-history", headers=auth_headers)
        assert response.status_code == 200

        body = response.json()
        assert len(body) == 2
        assert body[0]["nl_query"] == "show temperature in indian ocean"
        assert body[1]["nl_query"] == "show salinity in arabian sea"
        for item in body:
            assert "created_at" in item

    def test_respects_limit_parameter(self, client: TestClient, db_session, auth_user: User, auth_headers: dict[str, str]):
        now = datetime.now(timezone.utc)
        for i in range(3):
            db_session.add(
                QueryHistory(
                    nl_query=f"query {i}",
                    generated_sql="SELECT 1",
                    embedding=_vector(),
                    row_count=1,
                    user_id=auth_user.user_id,
                    provider="deepseek",
                    model="deepseek-reasoner",
                    created_at=now - timedelta(seconds=i),
                )
            )
        db_session.commit()

        response = client.get("/api/v1/chat/query-history?limit=2", headers=auth_headers)
        assert response.status_code == 200
        assert len(response.json()) == 2

    def test_limit_over_200_rejected(self, client: TestClient, auth_headers: dict[str, str]):
        response = client.get("/api/v1/chat/query-history?limit=201", headers=auth_headers)
        assert response.status_code == 422
