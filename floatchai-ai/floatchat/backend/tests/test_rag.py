"""Feature 14 RAG tests.

Covers:
- rag.py unit behavior (dedup, tenant-filtered retrieval, fallback)
- benchmark static-only behavior (no user/db passed to nl_to_sql)
- chat SSE non-blocking store scheduling behavior
"""

from dataclasses import dataclass, field
from types import SimpleNamespace
from unittest.mock import AsyncMock, MagicMock, patch
import uuid
from typing import Generator

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.auth.jwt import create_token
from app.db.models import ChatSession, User
from app.query.rag import build_rag_context, retrieve_similar_queries, store_successful_query


# =============================================================================
# Shared helpers
# =============================================================================


@dataclass
class MockPipelineResult:
    sql: str | None = "SELECT 1"
    error: str | None = None
    retries_used: int = 0
    validation_errors: list[str] = field(default_factory=list)
    provider: str = "deepseek"
    model: str = "deepseek-reasoner"


@dataclass
class MockExecutionResult:
    columns: list[str] = field(default_factory=lambda: ["id"])
    rows: list[dict] = field(default_factory=lambda: [{"id": 1}])
    row_count: int = 1
    truncated: bool = False
    error: str | None = None


def _parse_sse_events(response) -> list[dict]:
    events = []
    current_event = None
    for line in response.text.split("\n"):
        line = line.strip()
        if line.startswith("event:"):
            current_event = line[len("event:") :].strip()
        elif line.startswith("data:"):
            data_raw = line[len("data:") :].strip()
            try:
                import json

                payload = json.loads(data_raw)
            except Exception:
                payload = data_raw
            events.append({"event": current_event, "data": payload})
            current_event = None
    return events


# =============================================================================
# Unit tests: rag.py
# =============================================================================


class TestRagStore:
    @patch("app.query.rag._embed_nl_query", return_value=[0.1, 0.2, 0.3])
    def test_store_successful_query_inserts_and_commits(self, mock_embed):
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None

        store_successful_query(
            nl_query="Show SST trend",
            generated_sql="SELECT 1",
            row_count=5,
            user_id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            provider="deepseek",
            model="deepseek-reasoner",
            db=db,
        )

        assert db.add.called
        db.commit.assert_called_once()
        db.rollback.assert_not_called()
        mock_embed.assert_called_once()

    def test_store_successful_query_dedup_skips_insert(self):
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = uuid.uuid4()

        store_successful_query(
            nl_query="Show SST trend",
            generated_sql="SELECT 1",
            row_count=5,
            user_id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            provider="deepseek",
            model="deepseek-reasoner",
            db=db,
        )

        db.add.assert_not_called()
        db.commit.assert_not_called()

    def test_store_successful_query_ignores_zero_rows(self):
        db = MagicMock()

        store_successful_query(
            nl_query="Show SST trend",
            generated_sql="SELECT 1",
            row_count=0,
            user_id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            provider="deepseek",
            model="deepseek-reasoner",
            db=db,
        )

        db.execute.assert_not_called()
        db.add.assert_not_called()
        db.commit.assert_not_called()

    @patch("app.query.rag._embed_nl_query", side_effect=RuntimeError("embed failed"))
    def test_store_successful_query_swallow_errors(self, mock_embed):
        db = MagicMock()
        db.execute.return_value.scalar_one_or_none.return_value = None

        # Must never raise
        store_successful_query(
            nl_query="Show SST trend",
            generated_sql="SELECT 1",
            row_count=5,
            user_id=uuid.uuid4(),
            session_id=uuid.uuid4(),
            provider="deepseek",
            model="deepseek-reasoner",
            db=db,
        )

        db.rollback.assert_called_once()
        mock_embed.assert_called_once()


class TestRagRetrieve:
    @patch("app.query.rag._embed_nl_query", return_value=[0.1, 0.2, 0.3])
    def test_retrieve_similar_queries_returns_rows(self, mock_embed):
        db = MagicMock()
        db.execute.return_value.all.return_value = [
            SimpleNamespace(nl_query="Q1", generated_sql="SELECT 1", row_count=3),
            SimpleNamespace(nl_query="Q2", generated_sql="SELECT 2", row_count=7),
        ]

        results = retrieve_similar_queries(
            nl_query="Current query",
            user_id=uuid.uuid4(),
            db=db,
            limit=2,
        )

        assert len(results) == 2
        assert results[0]["nl_query"] == "Q1"
        assert results[0]["generated_sql"] == "SELECT 1"
        assert results[0]["row_count"] == 3
        mock_embed.assert_called_once()

    @patch("app.query.rag._embed_nl_query", return_value=[0.1, 0.2, 0.3])
    def test_retrieve_similar_queries_empty_is_valid(self, mock_embed):
        db = MagicMock()
        db.execute.return_value.all.return_value = []

        results = retrieve_similar_queries(
            nl_query="Current query",
            user_id=uuid.uuid4(),
            db=db,
        )

        assert results == []

    @patch("app.query.rag._embed_nl_query", side_effect=RuntimeError("embed failed"))
    def test_retrieve_similar_queries_swallow_errors(self, mock_embed):
        db = MagicMock()

        results = retrieve_similar_queries(
            nl_query="Current query",
            user_id=uuid.uuid4(),
            db=db,
        )

        assert results == []
        db.rollback.assert_called_once()


class TestBuildRagContext:
    def test_build_rag_context_empty(self):
        assert build_rag_context([]) == ""

    def test_build_rag_context_formats_examples(self):
        ctx = build_rag_context(
            [
                {
                    "nl_query": "Find salinity",
                    "generated_sql": "SELECT salinity FROM measurements",
                    "row_count": 12,
                }
            ]
        )
        assert "query history" in ctx.lower()
        assert "Find salinity" in ctx
        assert "```sql" in ctx


# =============================================================================
# API-level checks for Phase 4/5 contracts
# =============================================================================


@pytest.fixture()
def rag_client(db_session) -> Generator[TestClient, None, None]:
    """Client overriding both read-write and readonly DB dependencies."""
    from app.db.session import get_db, get_readonly_db
    from app.main import app

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_readonly_db] = _override_get_db

    with TestClient(app) as client:
        yield client

    app.dependency_overrides.clear()


@pytest.fixture()
def rag_user(db_session: Session) -> User:
    user = User(
        user_id=uuid.uuid4(),
        email="rag-user@example.com",
        hashed_password="test-hash",
        name="RAG User",
        role="researcher",
        is_active=True,
    )
    db_session.add(user)
    db_session.commit()
    db_session.refresh(user)
    return user


@pytest.fixture()
def rag_auth_headers(rag_user: User) -> dict[str, str]:
    token = create_token(
        {
            "sub": str(rag_user.user_id),
            "email": rag_user.email,
            "role": rag_user.role,
        },
        token_type="access",
    )
    return {"Authorization": f"Bearer {token}"}


def _create_chat_session(db_session: Session, user: User) -> ChatSession:
    session = ChatSession(
        session_id=uuid.uuid4(),
        user_identifier=str(user.user_id),
        name="RAG Test Session",
    )
    db_session.add(session)
    db_session.commit()
    db_session.refresh(session)
    return session


class TestBenchmarkStaticOnly:
    @patch("app.api.v1.query._get_configured_providers", return_value=["deepseek"])
    @patch("app.api.v1.query.nl_to_sql", new_callable=AsyncMock)
    def test_benchmark_calls_nl_to_sql_without_rag_context(
        self,
        mock_nl_to_sql,
        mock_providers,
        rag_client: TestClient,
        rag_auth_headers: dict[str, str],
    ):
        mock_nl_to_sql.return_value = MockPipelineResult(sql="SELECT 1")

        resp = rag_client.post(
            "/api/v1/query/benchmark",
            json={"query": "Show floats"},
            headers=rag_auth_headers,
        )

        assert resp.status_code == 200
        call_kwargs = mock_nl_to_sql.await_args.kwargs
        assert "user_id" not in call_kwargs
        assert "db" not in call_kwargs


class TestChatStoreScheduling:
    @patch("app.api.v1.chat._get_redis_client", return_value=None)
    @patch("app.api.v1.chat.append_context", new_callable=AsyncMock)
    @patch("app.api.v1.chat.get_context", new_callable=AsyncMock, return_value=[])
    @patch("app.api.v1.chat.resolve_geography", return_value=None)
    @patch("app.api.v1.chat.nl_to_sql", new_callable=AsyncMock)
    @patch("app.api.v1.chat.estimate_rows", return_value=10)
    @patch("app.api.v1.chat.execute_sql")
    @patch("app.api.v1.chat.interpret_results", new_callable=AsyncMock, return_value="ok")
    @patch("app.api.v1.chat.generate_follow_up_suggestions", new_callable=AsyncMock, return_value=[])
    @patch("app.api.v1.chat.asyncio.get_running_loop")
    def test_query_sse_schedules_background_store_on_success(
        self,
        mock_get_loop,
        mock_followups,
        mock_interpret,
        mock_execute,
        mock_estimate,
        mock_nl_to_sql,
        mock_geo,
        mock_get_ctx,
        mock_append,
        mock_redis,
        rag_client: TestClient,
        db_session: Session,
        rag_user: User,
        rag_auth_headers: dict[str, str],
    ):
        mock_nl_to_sql.return_value = MockPipelineResult(sql="SELECT 1")
        mock_execute.return_value = MockExecutionResult(row_count=2)

        loop = MagicMock()
        mock_get_loop.return_value = loop

        session = _create_chat_session(db_session, rag_user)

        resp = rag_client.post(
            f"/api/v1/chat/sessions/{session.session_id}/query",
            json={"query": "Show floats"},
            headers=rag_auth_headers,
        )

        assert resp.status_code == 200
        events = _parse_sse_events(resp)
        event_types = [e["event"] for e in events]
        assert "results" in event_types
        assert "done" in event_types

        loop.run_in_executor.assert_called_once()

    @patch("app.api.v1.chat._get_redis_client", return_value=None)
    @patch("app.api.v1.chat.append_context", new_callable=AsyncMock)
    @patch("app.api.v1.chat.get_context", new_callable=AsyncMock, return_value=[])
    @patch("app.api.v1.chat.resolve_geography", return_value=None)
    @patch("app.api.v1.chat.nl_to_sql", new_callable=AsyncMock)
    @patch("app.api.v1.chat.estimate_rows", return_value=10)
    @patch("app.api.v1.chat.execute_sql")
    @patch("app.api.v1.chat.interpret_results", new_callable=AsyncMock, return_value="ok")
    @patch("app.api.v1.chat.generate_follow_up_suggestions", new_callable=AsyncMock, return_value=[])
    @patch("app.api.v1.chat.asyncio.get_running_loop")
    def test_query_sse_does_not_schedule_store_for_zero_rows(
        self,
        mock_get_loop,
        mock_followups,
        mock_interpret,
        mock_execute,
        mock_estimate,
        mock_nl_to_sql,
        mock_geo,
        mock_get_ctx,
        mock_append,
        mock_redis,
        rag_client: TestClient,
        db_session: Session,
        rag_user: User,
        rag_auth_headers: dict[str, str],
    ):
        mock_nl_to_sql.return_value = MockPipelineResult(sql="SELECT 1")
        mock_execute.return_value = MockExecutionResult(row_count=0)

        loop = MagicMock()
        mock_get_loop.return_value = loop

        session = _create_chat_session(db_session, rag_user)

        resp = rag_client.post(
            f"/api/v1/chat/sessions/{session.session_id}/query",
            json={"query": "Show floats"},
            headers=rag_auth_headers,
        )

        assert resp.status_code == 200
        loop.run_in_executor.assert_not_called()
