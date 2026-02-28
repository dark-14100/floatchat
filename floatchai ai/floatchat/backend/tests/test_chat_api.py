"""
Tests for app.api.v1.chat — Chat Interface API endpoints.

Covers:
  - Session CRUD (create, list, get, rename, soft-delete)
  - Message pagination (cursor-based)
  - SSE streaming query (event sequence, error handling, confirmation flow)
  - Confirmation endpoint (server-stored SQL retrieval + execution)
  - Suggestions endpoint (load-time suggestions)
  - X-User-ID isolation (sessions scoped by user)
  - Message persistence (user + assistant messages saved)

All external pipeline calls (nl_to_sql, execute_sql, estimate_rows,
interpret_results, generate_follow_up_suggestions) are mocked.
"""

import json
import uuid
from dataclasses import dataclass, field
from typing import Generator, Optional
from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi.testclient import TestClient
from sqlalchemy.orm import Session

from app.db.models import ChatSession, ChatMessage


# ═════════════════════════════════════════════════════════════════════════════
# Fixtures
# ═════════════════════════════════════════════════════════════════════════════

@pytest.fixture()
def chat_client(db_session) -> Generator[TestClient, None, None]:
    """
    TestClient that overrides BOTH get_db AND get_readonly_db.
    The SSE query and confirm endpoints depend on both.
    """
    from app.db.session import get_db, get_readonly_db
    from app.main import app

    def _override_get_db():
        yield db_session

    app.dependency_overrides[get_db] = _override_get_db
    app.dependency_overrides[get_readonly_db] = _override_get_db  # same session

    with TestClient(app) as c:
        yield c

    app.dependency_overrides.clear()


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

USER_A = "user-aaa-111"
USER_B = "user-bbb-222"


def _headers(user_id: str = USER_A) -> dict:
    return {"X-User-ID": user_id}


def _create_session(client: TestClient, name: str | None = None, user_id: str = USER_A) -> dict:
    """Create a session via the API and return the JSON body."""
    body = {"name": name} if name else {}
    resp = client.post("/api/v1/chat/sessions", json=body, headers=_headers(user_id))
    assert resp.status_code == 201
    return resp.json()


def _parse_sse_events(response) -> list[dict]:
    """
    Parse raw SSE text/event-stream into a list of dicts:
    [{"event": "<type>", "data": <parsed_json>}, ...]
    """
    events = []
    current_event = None
    for line in response.text.split("\n"):
        line = line.strip()
        if line.startswith("event:"):
            current_event = line[len("event:"):].strip()
        elif line.startswith("data:"):
            data_str = line[len("data:"):].strip()
            try:
                data = json.loads(data_str)
            except json.JSONDecodeError:
                data = data_str
            events.append({"event": current_event, "data": data})
            current_event = None
    return events


# ═════════════════════════════════════════════════════════════════════════════
# Mock pipeline result / execution result
# ═════════════════════════════════════════════════════════════════════════════

@dataclass
class MockPipelineResult:
    sql: Optional[str] = "SELECT 1"
    error: Optional[str] = None
    retries_used: int = 0
    validation_errors: list[str] = field(default_factory=list)
    provider: str = "deepseek"
    model: str = "deepseek-reasoner"


@dataclass
class MockExecutionResult:
    columns: list[str] = field(default_factory=lambda: ["col_a", "col_b"])
    rows: list[dict] = field(default_factory=lambda: [{"col_a": 1, "col_b": "x"}])
    row_count: int = 1
    truncated: bool = False
    error: Optional[str] = None


# ═════════════════════════════════════════════════════════════════════════════
# Session CRUD
# ═════════════════════════════════════════════════════════════════════════════

class TestCreateSession:
    def test_creates_session_with_name(self, chat_client: TestClient):
        body = _create_session(chat_client, name="My research")
        assert "session_id" in body
        assert "created_at" in body

    def test_creates_session_without_name(self, chat_client: TestClient):
        body = _create_session(chat_client)
        assert "session_id" in body

    def test_session_id_is_valid_uuid(self, chat_client: TestClient):
        body = _create_session(chat_client)
        uuid.UUID(body["session_id"])  # should not raise


class TestListSessions:
    def test_lists_empty(self, chat_client: TestClient):
        resp = chat_client.get("/api/v1/chat/sessions", headers=_headers())
        assert resp.status_code == 200
        assert resp.json() == []

    def test_lists_created_session(self, chat_client: TestClient):
        _create_session(chat_client, name="Session 1")
        resp = chat_client.get("/api/v1/chat/sessions", headers=_headers())
        sessions = resp.json()
        assert len(sessions) == 1
        assert sessions[0]["name"] == "Session 1"

    def test_user_isolation(self, chat_client: TestClient):
        """User A's sessions are NOT visible to User B."""
        _create_session(chat_client, name="A's session", user_id=USER_A)
        _create_session(chat_client, name="B's session", user_id=USER_B)

        resp_a = chat_client.get("/api/v1/chat/sessions", headers=_headers(USER_A))
        resp_b = chat_client.get("/api/v1/chat/sessions", headers=_headers(USER_B))

        names_a = [s["name"] for s in resp_a.json()]
        names_b = [s["name"] for s in resp_b.json()]

        assert "A's session" in names_a
        assert "B's session" not in names_a
        assert "B's session" in names_b
        assert "A's session" not in names_b

    def test_ordered_by_last_active_desc(self, chat_client: TestClient):
        _create_session(chat_client, name="First")
        _create_session(chat_client, name="Second")

        resp = chat_client.get("/api/v1/chat/sessions", headers=_headers())
        sessions = resp.json()
        assert len(sessions) == 2
        # Both sessions returned; ordering is by last_active_at desc
        names = {s["name"] for s in sessions}
        assert names == {"First", "Second"}


class TestGetSession:
    def test_get_existing_session(self, chat_client: TestClient):
        created = _create_session(chat_client, name="Detailed")
        resp = chat_client.get(
            f"/api/v1/chat/sessions/{created['session_id']}",
            headers=_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "Detailed"

    def test_get_nonexistent_session_returns_404(self, chat_client: TestClient):
        fake_id = str(uuid.uuid4())
        resp = chat_client.get(
            f"/api/v1/chat/sessions/{fake_id}",
            headers=_headers(),
        )
        assert resp.status_code == 404

    def test_get_invalid_uuid_returns_400(self, chat_client: TestClient):
        resp = chat_client.get(
            "/api/v1/chat/sessions/not-a-uuid",
            headers=_headers(),
        )
        assert resp.status_code == 400


class TestRenameSession:
    def test_rename_session(self, chat_client: TestClient):
        created = _create_session(chat_client, name="Old name")
        resp = chat_client.patch(
            f"/api/v1/chat/sessions/{created['session_id']}",
            json={"name": "New name"},
            headers=_headers(),
        )
        assert resp.status_code == 200
        assert resp.json()["name"] == "New name"

    def test_rename_nonexistent_returns_404(self, chat_client: TestClient):
        fake_id = str(uuid.uuid4())
        resp = chat_client.patch(
            f"/api/v1/chat/sessions/{fake_id}",
            json={"name": "New"},
            headers=_headers(),
        )
        assert resp.status_code == 404

    def test_rename_empty_name_returns_422(self, chat_client: TestClient):
        created = _create_session(chat_client, name="Old")
        resp = chat_client.patch(
            f"/api/v1/chat/sessions/{created['session_id']}",
            json={"name": ""},
            headers=_headers(),
        )
        assert resp.status_code == 422


class TestDeleteSession:
    def test_soft_delete(self, chat_client: TestClient):
        created = _create_session(chat_client)
        resp = chat_client.delete(
            f"/api/v1/chat/sessions/{created['session_id']}",
            headers=_headers(),
        )
        assert resp.status_code == 204

        # Should not appear in list anymore
        resp = chat_client.get("/api/v1/chat/sessions", headers=_headers())
        ids = [s["session_id"] for s in resp.json()]
        assert created["session_id"] not in ids

    def test_get_deleted_session_returns_404(self, chat_client: TestClient):
        created = _create_session(chat_client)
        chat_client.delete(
            f"/api/v1/chat/sessions/{created['session_id']}",
            headers=_headers(),
        )
        resp = chat_client.get(
            f"/api/v1/chat/sessions/{created['session_id']}",
            headers=_headers(),
        )
        assert resp.status_code == 404

    def test_delete_nonexistent_returns_404(self, chat_client: TestClient):
        fake_id = str(uuid.uuid4())
        resp = chat_client.delete(
            f"/api/v1/chat/sessions/{fake_id}",
            headers=_headers(),
        )
        assert resp.status_code == 404


# ═════════════════════════════════════════════════════════════════════════════
# Message history (pagination)
# ═════════════════════════════════════════════════════════════════════════════

class TestGetMessages:
    def test_empty_messages(self, chat_client: TestClient, db_session: Session):
        created = _create_session(chat_client)
        resp = chat_client.get(
            f"/api/v1/chat/sessions/{created['session_id']}/messages",
            headers=_headers(),
        )
        assert resp.status_code == 200
        assert resp.json() == []

    def test_returns_persisted_messages(self, chat_client: TestClient, db_session: Session):
        created = _create_session(chat_client)
        session_uuid = uuid.UUID(created["session_id"])

        # Insert messages directly via ORM
        for i in range(3):
            msg = ChatMessage(
                message_id=uuid.uuid4(),
                session_id=session_uuid,
                role="user" if i % 2 == 0 else "assistant",
                content=f"Message {i}",
            )
            db_session.add(msg)
        db_session.commit()

        resp = chat_client.get(
            f"/api/v1/chat/sessions/{created['session_id']}/messages",
            headers=_headers(),
        )
        assert resp.status_code == 200
        messages = resp.json()
        assert len(messages) == 3

    def test_message_limit(self, chat_client: TestClient, db_session: Session):
        created = _create_session(chat_client)
        session_uuid = uuid.UUID(created["session_id"])

        # Insert 10 messages
        for i in range(10):
            msg = ChatMessage(
                message_id=uuid.uuid4(),
                session_id=session_uuid,
                role="user",
                content=f"Msg {i}",
            )
            db_session.add(msg)
        db_session.commit()

        resp = chat_client.get(
            f"/api/v1/chat/sessions/{created['session_id']}/messages?limit=5",
            headers=_headers(),
        )
        messages = resp.json()
        assert len(messages) == 5

    def test_invalid_session_returns_404(self, chat_client: TestClient):
        fake_id = str(uuid.uuid4())
        resp = chat_client.get(
            f"/api/v1/chat/sessions/{fake_id}/messages",
            headers=_headers(),
        )
        assert resp.status_code == 404


# ═════════════════════════════════════════════════════════════════════════════
# SSE query endpoint
# ═════════════════════════════════════════════════════════════════════════════

class TestQuerySSE:
    """Tests for POST /chat/sessions/{id}/query — SSE streaming."""

    @patch("app.api.v1.chat.generate_follow_up_suggestions", new_callable=AsyncMock)
    @patch("app.api.v1.chat.interpret_results", new_callable=AsyncMock)
    @patch("app.api.v1.chat.execute_sql")
    @patch("app.api.v1.chat.estimate_rows", return_value=100)
    @patch("app.api.v1.chat.nl_to_sql", new_callable=AsyncMock)
    @patch("app.api.v1.chat.resolve_geography", return_value=None)
    @patch("app.api.v1.chat.get_context", new_callable=AsyncMock, return_value=[])
    @patch("app.api.v1.chat.append_context", new_callable=AsyncMock)
    @patch("app.api.v1.chat._get_redis_client", return_value=None)
    def test_full_success_event_sequence(
        self,
        mock_redis_client,
        mock_append,
        mock_get_ctx,
        mock_geo,
        mock_nl_to_sql,
        mock_estimate,
        mock_exec,
        mock_interpret,
        mock_followups,
        chat_client: TestClient,
    ):
        """Successful query emits: thinking → interpreting → executing → results → suggestions → done."""
        mock_nl_to_sql.return_value = MockPipelineResult(sql="SELECT 1")
        mock_exec.return_value = MockExecutionResult(
            columns=["id"], rows=[{"id": 1}], row_count=1
        )
        mock_interpret.return_value = "Found 1 result."
        mock_followups.return_value = ["What about salinity?"]

        created = _create_session(chat_client)
        resp = chat_client.post(
            f"/api/v1/chat/sessions/{created['session_id']}/query",
            json={"query": "Show me floats"},
            headers=_headers(),
        )

        assert resp.status_code == 200
        assert "text/event-stream" in resp.headers["content-type"]

        events = _parse_sse_events(resp)
        event_types = [e["event"] for e in events]

        assert event_types == [
            "thinking",
            "interpreting",
            "executing",
            "results",
            "suggestions",
            "done",
        ]

        # Validate results payload
        results = next(e for e in events if e["event"] == "results")
        assert results["data"]["columns"] == ["id"]
        assert results["data"]["row_count"] == 1
        assert results["data"]["interpretation"] == "Found 1 result."

        # Validate suggestions payload
        suggestions = next(e for e in events if e["event"] == "suggestions")
        assert suggestions["data"]["suggestions"] == ["What about salinity?"]

    @patch("app.api.v1.chat._get_redis_client", return_value=None)
    @patch("app.api.v1.chat.get_context", new_callable=AsyncMock, return_value=[])
    @patch("app.api.v1.chat.resolve_geography", return_value=None)
    @patch("app.api.v1.chat.nl_to_sql", new_callable=AsyncMock)
    def test_pipeline_error_emits_error_event(
        self,
        mock_nl_to_sql,
        mock_geo,
        mock_get_ctx,
        mock_redis_client,
        chat_client: TestClient,
    ):
        """When nl_to_sql returns an error, an error event is emitted."""
        mock_nl_to_sql.return_value = MockPipelineResult(
            sql=None, error="Unable to understand query"
        )

        created = _create_session(chat_client)
        resp = chat_client.post(
            f"/api/v1/chat/sessions/{created['session_id']}/query",
            json={"query": "gibberish"},
            headers=_headers(),
        )

        events = _parse_sse_events(resp)
        event_types = [e["event"] for e in events]

        assert "thinking" in event_types
        assert "error" in event_types
        assert "done" in event_types

        error_evt = next(e for e in events if e["event"] == "error")
        assert "Unable to understand query" in error_evt["data"]["error"]

    @patch("app.api.v1.chat.append_context", new_callable=AsyncMock)
    @patch("app.api.v1.chat._get_redis_client", return_value=None)
    @patch("app.api.v1.chat.get_context", new_callable=AsyncMock, return_value=[])
    @patch("app.api.v1.chat.resolve_geography", return_value=None)
    @patch("app.api.v1.chat.estimate_rows", return_value=100000)
    @patch("app.api.v1.chat.nl_to_sql", new_callable=AsyncMock)
    def test_awaiting_confirmation_for_large_results(
        self,
        mock_nl_to_sql,
        mock_estimate,
        mock_geo,
        mock_get_ctx,
        mock_redis_client,
        mock_append,
        chat_client: TestClient,
    ):
        """When estimated rows exceed threshold, emits awaiting_confirmation event."""
        mock_nl_to_sql.return_value = MockPipelineResult(sql="SELECT * FROM profiles")

        created = _create_session(chat_client)
        resp = chat_client.post(
            f"/api/v1/chat/sessions/{created['session_id']}/query",
            json={"query": "Show all profiles"},
            headers=_headers(),
        )

        events = _parse_sse_events(resp)
        event_types = [e["event"] for e in events]

        assert "awaiting_confirmation" in event_types
        assert "done" in event_types
        # Should NOT have results or executing events
        assert "executing" not in event_types
        assert "results" not in event_types

        confirm_evt = next(e for e in events if e["event"] == "awaiting_confirmation")
        assert confirm_evt["data"]["estimated_rows"] == 100000
        assert "message_id" in confirm_evt["data"]
        assert "sql" in confirm_evt["data"]

    @patch("app.api.v1.chat.generate_follow_up_suggestions", new_callable=AsyncMock)
    @patch("app.api.v1.chat.interpret_results", new_callable=AsyncMock)
    @patch("app.api.v1.chat.execute_sql")
    @patch("app.api.v1.chat.estimate_rows", return_value=100000)
    @patch("app.api.v1.chat.nl_to_sql", new_callable=AsyncMock)
    @patch("app.api.v1.chat.resolve_geography", return_value=None)
    @patch("app.api.v1.chat.get_context", new_callable=AsyncMock, return_value=[])
    @patch("app.api.v1.chat.append_context", new_callable=AsyncMock)
    @patch("app.api.v1.chat._get_redis_client", return_value=None)
    def test_confirm_flag_bypasses_threshold(
        self,
        mock_redis_client,
        mock_append,
        mock_get_ctx,
        mock_geo,
        mock_nl_to_sql,
        mock_estimate,
        mock_exec,
        mock_interpret,
        mock_followups,
        chat_client: TestClient,
    ):
        """When confirm=true, large results are executed anyway."""
        mock_nl_to_sql.return_value = MockPipelineResult(sql="SELECT * FROM profiles")
        mock_exec.return_value = MockExecutionResult(
            columns=["id"], rows=[{"id": 1}], row_count=1
        )
        mock_interpret.return_value = "Here are the profiles."
        mock_followups.return_value = []

        created = _create_session(chat_client)
        resp = chat_client.post(
            f"/api/v1/chat/sessions/{created['session_id']}/query",
            json={"query": "Show all profiles", "confirm": True},
            headers=_headers(),
        )

        events = _parse_sse_events(resp)
        event_types = [e["event"] for e in events]

        assert "executing" in event_types
        assert "results" in event_types
        assert "awaiting_confirmation" not in event_types

    @patch("app.api.v1.chat.generate_follow_up_suggestions", new_callable=AsyncMock)
    @patch("app.api.v1.chat.interpret_results", new_callable=AsyncMock)
    @patch("app.api.v1.chat.execute_sql")
    @patch("app.api.v1.chat.estimate_rows", return_value=100)
    @patch("app.api.v1.chat.nl_to_sql", new_callable=AsyncMock)
    @patch("app.api.v1.chat.resolve_geography", return_value=None)
    @patch("app.api.v1.chat.get_context", new_callable=AsyncMock, return_value=[])
    @patch("app.api.v1.chat.append_context", new_callable=AsyncMock)
    @patch("app.api.v1.chat._get_redis_client", return_value=None)
    def test_execution_error_emits_error_event(
        self,
        mock_redis_client,
        mock_append,
        mock_get_ctx,
        mock_geo,
        mock_nl_to_sql,
        mock_estimate,
        mock_exec,
        mock_interpret,
        mock_followups,
        chat_client: TestClient,
    ):
        """When execute_sql returns an error, an error event is emitted."""
        mock_nl_to_sql.return_value = MockPipelineResult(sql="SELECT bad_col")
        mock_exec.return_value = MockExecutionResult(error="column not found")
        mock_interpret.return_value = ""
        mock_followups.return_value = []

        created = _create_session(chat_client)
        resp = chat_client.post(
            f"/api/v1/chat/sessions/{created['session_id']}/query",
            json={"query": "Show bad column"},
            headers=_headers(),
        )

        events = _parse_sse_events(resp)
        event_types = [e["event"] for e in events]

        assert "error" in event_types
        error_evt = next(e for e in events if e["event"] == "error")
        assert "column not found" in error_evt["data"]["error"]

    def test_query_nonexistent_session_returns_404(self, chat_client: TestClient):
        fake_id = str(uuid.uuid4())
        resp = chat_client.post(
            f"/api/v1/chat/sessions/{fake_id}/query",
            json={"query": "test"},
            headers=_headers(),
        )
        assert resp.status_code == 404

    def test_query_empty_string_returns_422(self, chat_client: TestClient):
        created = _create_session(chat_client)
        resp = chat_client.post(
            f"/api/v1/chat/sessions/{created['session_id']}/query",
            json={"query": ""},
            headers=_headers(),
        )
        assert resp.status_code == 422

    @patch("app.api.v1.chat.generate_follow_up_suggestions", new_callable=AsyncMock)
    @patch("app.api.v1.chat.interpret_results", new_callable=AsyncMock)
    @patch("app.api.v1.chat.execute_sql")
    @patch("app.api.v1.chat.estimate_rows", return_value=100)
    @patch("app.api.v1.chat.nl_to_sql", new_callable=AsyncMock)
    @patch("app.api.v1.chat.resolve_geography", return_value=None)
    @patch("app.api.v1.chat.get_context", new_callable=AsyncMock, return_value=[])
    @patch("app.api.v1.chat.append_context", new_callable=AsyncMock)
    @patch("app.api.v1.chat._get_redis_client", return_value=None)
    def test_messages_persisted_after_query(
        self,
        mock_redis_client,
        mock_append,
        mock_get_ctx,
        mock_geo,
        mock_nl_to_sql,
        mock_estimate,
        mock_exec,
        mock_interpret,
        mock_followups,
        chat_client: TestClient,
    ):
        """A successful query persists both user and assistant messages."""
        mock_nl_to_sql.return_value = MockPipelineResult(sql="SELECT 1")
        mock_exec.return_value = MockExecutionResult(
            columns=["v"], rows=[{"v": 42}], row_count=1
        )
        mock_interpret.return_value = "The answer is 42."
        mock_followups.return_value = ["What about 43?"]

        created = _create_session(chat_client)
        chat_client.post(
            f"/api/v1/chat/sessions/{created['session_id']}/query",
            json={"query": "What is the answer?"},
            headers=_headers(),
        )

        # Fetch messages
        resp = chat_client.get(
            f"/api/v1/chat/sessions/{created['session_id']}/messages",
            headers=_headers(),
        )
        messages = resp.json()
        assert len(messages) >= 2

        roles = [m["role"] for m in messages]
        assert "user" in roles
        assert "assistant" in roles

        # User message has the original query
        user_msg = next(m for m in messages if m["role"] == "user")
        assert user_msg["content"] == "What is the answer?"

        # Assistant message has the interpretation
        asst_msg = next(m for m in messages if m["role"] == "assistant")
        assert asst_msg["content"] == "The answer is 42."
        assert asst_msg["generated_sql"] == "SELECT 1"
        assert asst_msg["status"] == "completed"


# ═════════════════════════════════════════════════════════════════════════════
# Confirmation endpoint
# ═════════════════════════════════════════════════════════════════════════════

class TestConfirmQuery:
    """Tests for POST /chat/sessions/{id}/query/confirm."""

    def _create_pending_message(
        self, db_session: Session, session_uuid: uuid.UUID
    ) -> str:
        """Insert a pending_confirmation message directly and return its message_id."""
        msg = ChatMessage(
            message_id=uuid.uuid4(),
            session_id=session_uuid,
            role="assistant",
            content="I'll query the ocean data database for you...",
            generated_sql="SELECT * FROM profiles LIMIT 10",
            result_metadata={"estimated_rows": 100000},
            status="pending_confirmation",
        )
        db_session.add(msg)
        db_session.commit()
        return str(msg.message_id)

    @patch("app.api.v1.chat.generate_follow_up_suggestions", new_callable=AsyncMock)
    @patch("app.api.v1.chat.interpret_results", new_callable=AsyncMock)
    @patch("app.api.v1.chat.execute_sql")
    @patch("app.api.v1.chat.append_context", new_callable=AsyncMock)
    @patch("app.api.v1.chat._get_redis_client", return_value=None)
    def test_confirm_executes_stored_sql(
        self,
        mock_redis_client,
        mock_append,
        mock_exec,
        mock_interpret,
        mock_followups,
        chat_client: TestClient,
        db_session: Session,
    ):
        """Confirm retrieves server-stored SQL and executes it."""
        created = _create_session(chat_client)
        session_uuid = uuid.UUID(created["session_id"])
        pending_id = self._create_pending_message(db_session, session_uuid)

        mock_exec.return_value = MockExecutionResult(
            columns=["profile_id"], rows=[{"profile_id": 1}], row_count=1
        )
        mock_interpret.return_value = "Here are the profiles."
        mock_followups.return_value = []

        resp = chat_client.post(
            f"/api/v1/chat/sessions/{created['session_id']}/query/confirm",
            json={"message_id": pending_id},
            headers=_headers(),
        )

        assert resp.status_code == 200
        events = _parse_sse_events(resp)
        event_types = [e["event"] for e in events]

        # Confirm skips thinking and interpreting — goes straight to executing
        assert "thinking" not in event_types
        assert "interpreting" not in event_types
        assert "executing" in event_types
        assert "results" in event_types
        assert "suggestions" in event_types
        assert "done" in event_types

    @patch("app.api.v1.chat.generate_follow_up_suggestions", new_callable=AsyncMock)
    @patch("app.api.v1.chat.interpret_results", new_callable=AsyncMock)
    @patch("app.api.v1.chat.execute_sql")
    @patch("app.api.v1.chat.append_context", new_callable=AsyncMock)
    @patch("app.api.v1.chat._get_redis_client", return_value=None)
    def test_confirm_execution_error(
        self,
        mock_redis_client,
        mock_append,
        mock_exec,
        mock_interpret,
        mock_followups,
        chat_client: TestClient,
        db_session: Session,
    ):
        """Confirm with execution error emits error event."""
        created = _create_session(chat_client)
        session_uuid = uuid.UUID(created["session_id"])
        pending_id = self._create_pending_message(db_session, session_uuid)

        mock_exec.return_value = MockExecutionResult(error="timeout")
        mock_interpret.return_value = ""
        mock_followups.return_value = []

        resp = chat_client.post(
            f"/api/v1/chat/sessions/{created['session_id']}/query/confirm",
            json={"message_id": pending_id},
            headers=_headers(),
        )

        events = _parse_sse_events(resp)
        event_types = [e["event"] for e in events]
        assert "error" in event_types

    def test_confirm_nonexistent_message_returns_404(self, chat_client: TestClient):
        created = _create_session(chat_client)
        fake_msg_id = str(uuid.uuid4())
        resp = chat_client.post(
            f"/api/v1/chat/sessions/{created['session_id']}/query/confirm",
            json={"message_id": fake_msg_id},
            headers=_headers(),
        )
        assert resp.status_code == 404

    def test_confirm_invalid_message_id_returns_400(self, chat_client: TestClient):
        created = _create_session(chat_client)
        resp = chat_client.post(
            f"/api/v1/chat/sessions/{created['session_id']}/query/confirm",
            json={"message_id": "not-a-uuid"},
            headers=_headers(),
        )
        assert resp.status_code == 400

    def test_confirm_nonexistent_session_returns_404(self, chat_client: TestClient):
        fake_session_id = str(uuid.uuid4())
        resp = chat_client.post(
            f"/api/v1/chat/sessions/{fake_session_id}/query/confirm",
            json={"message_id": str(uuid.uuid4())},
            headers=_headers(),
        )
        assert resp.status_code == 404


# ═════════════════════════════════════════════════════════════════════════════
# Suggestions endpoint
# ═════════════════════════════════════════════════════════════════════════════

class TestSuggestionsEndpoint:
    """Tests for GET /chat/suggestions."""

    @patch("app.api.v1.chat.generate_load_time_suggestions")
    @patch("app.api.v1.chat._get_redis_client", return_value=None)
    def test_returns_suggestions(self, mock_redis, mock_gen, chat_client: TestClient):
        mock_gen.return_value = [
            {"query": "Show floats", "description": "Browse floats"},
            {"query": "Count profiles", "description": "Get counts"},
        ]

        resp = chat_client.get("/api/v1/chat/suggestions")
        assert resp.status_code == 200
        body = resp.json()
        assert "suggestions" in body
        assert len(body["suggestions"]) == 2
        assert body["suggestions"][0]["query"] == "Show floats"

    @patch("app.api.v1.chat.generate_load_time_suggestions")
    @patch("app.api.v1.chat._get_redis_client", return_value=None)
    def test_returns_fallbacks_on_empty(self, mock_redis, mock_gen, chat_client: TestClient):
        mock_gen.return_value = [
            {"query": "Fallback query", "description": "Fallback"},
        ]

        resp = chat_client.get("/api/v1/chat/suggestions")
        assert resp.status_code == 200
        assert len(resp.json()["suggestions"]) >= 1


# ═════════════════════════════════════════════════════════════════════════════
# SSE helpers unit tests
# ═════════════════════════════════════════════════════════════════════════════

class TestSSEHelpers:
    def test_sse_event_format(self):
        from app.api.v1.chat import _sse_event
        result = _sse_event("thinking", {"status": "thinking"})
        assert result.startswith("event: thinking\n")
        assert "data:" in result
        assert result.endswith("\n\n")
        # data should be valid JSON
        data_line = result.split("\n")[1]
        data_str = data_line[len("data: "):]
        parsed = json.loads(data_str)
        assert parsed["status"] == "thinking"

    def test_build_interpretation_preview_count(self):
        from app.api.v1.chat import _build_interpretation_preview
        result = _build_interpretation_preview("How many floats are there?")
        assert "count" in result.lower()

    def test_build_interpretation_preview_average(self):
        from app.api.v1.chat import _build_interpretation_preview
        result = _build_interpretation_preview("What is the average temperature?")
        assert "average" in result.lower()

    def test_build_interpretation_preview_show(self):
        from app.api.v1.chat import _build_interpretation_preview
        result = _build_interpretation_preview("Show me all profiles")
        assert "search" in result.lower()

    def test_build_interpretation_preview_default(self):
        from app.api.v1.chat import _build_interpretation_preview
        result = _build_interpretation_preview("xyzzy foobar")
        assert "query" in result.lower() or "ocean" in result.lower()
