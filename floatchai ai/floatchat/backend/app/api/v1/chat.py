"""
FloatChat Chat Interface — API Router

Endpoints:
  POST   /chat/sessions                              — Create a new chat session
  GET    /chat/sessions                              — List sessions for the current user
  GET    /chat/sessions/{session_id}                 — Get session details
  PATCH  /chat/sessions/{session_id}                 — Rename a session
  DELETE /chat/sessions/{session_id}                 — Soft-delete a session
  GET    /chat/sessions/{session_id}/messages        — Paginated message history
  POST   /chat/sessions/{session_id}/query           — SSE streaming query (FR-06)
  POST   /chat/sessions/{session_id}/query/confirm   — Confirm large result execution (FR-09)
  GET    /chat/suggestions                           — Load-time suggestions (FR-08)
"""

import json
import time
import uuid
from datetime import datetime, timezone
from typing import AsyncGenerator, Optional

import structlog
from fastapi import APIRouter, Depends, Header, HTTPException, Query
from fastapi.responses import StreamingResponse
from pydantic import BaseModel, Field
from redis import Redis
from sqlalchemy import select, func as sa_func
from sqlalchemy.orm import Session

from app.chat.follow_ups import generate_follow_up_suggestions
from app.chat.suggestions import generate_load_time_suggestions
from app.config import get_settings
from app.db.models import ChatSession, ChatMessage
from app.db.session import get_db, get_readonly_db
from app.query.context import append_context, get_context
from app.query.executor import estimate_rows, execute_sql
from app.query.geography import resolve_geography
from app.query.pipeline import nl_to_sql, interpret_results, get_llm_client

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/chat", tags=["Chat"])


# ── Request / Response schemas ──────────────────────────────────────────────

class CreateSessionRequest(BaseModel):
    name: Optional[str] = Field(None, max_length=255, description="Optional session name")


class CreateSessionResponse(BaseModel):
    session_id: str
    created_at: str


class SessionResponse(BaseModel):
    session_id: str
    name: Optional[str] = None
    message_count: int = 0
    created_at: str
    last_active_at: str
    is_active: bool = True


class RenameSessionRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=255, description="New session name")


class MessageResponse(BaseModel):
    message_id: str
    session_id: str
    role: str
    content: str
    nl_query: Optional[str] = None
    generated_sql: Optional[str] = None
    result_metadata: Optional[dict] = None
    follow_up_suggestions: Optional[list] = None
    error: Optional[dict] = None
    status: Optional[str] = None
    created_at: str


# ── Helpers ─────────────────────────────────────────────────────────────────

def _get_user_id(x_user_id: Optional[str] = Header(None)) -> Optional[str]:
    """Extract user identifier from X-User-ID header."""
    return x_user_id


def _session_to_response(session: ChatSession) -> SessionResponse:
    """Convert a ChatSession ORM object to a response model."""
    return SessionResponse(
        session_id=str(session.session_id),
        name=session.name,
        message_count=session.message_count,
        created_at=session.created_at.isoformat() if session.created_at else "",
        last_active_at=session.last_active_at.isoformat() if session.last_active_at else "",
        is_active=session.is_active,
    )


def _message_to_response(msg: ChatMessage) -> MessageResponse:
    """Convert a ChatMessage ORM object to a response model."""
    return MessageResponse(
        message_id=str(msg.message_id),
        session_id=str(msg.session_id),
        role=msg.role,
        content=msg.content,
        nl_query=msg.nl_query,
        generated_sql=msg.generated_sql,
        result_metadata=msg.result_metadata,
        follow_up_suggestions=msg.follow_up_suggestions,
        error=msg.error,
        status=msg.status,
        created_at=msg.created_at.isoformat() if msg.created_at else "",
    )


# ── POST /chat/sessions ────────────────────────────────────────────────────

@router.post("/sessions", response_model=CreateSessionResponse, status_code=201)
def create_session(
    request: CreateSessionRequest = CreateSessionRequest(),
    db: Session = Depends(get_db),
    user_id: Optional[str] = Depends(_get_user_id),
):
    """Create a new chat session."""
    session = ChatSession(
        session_id=uuid.uuid4(),
        user_identifier=user_id,
        name=request.name,
    )
    db.add(session)
    db.commit()
    db.refresh(session)

    log.info(
        "chat_session_created",
        session_id=str(session.session_id),
        user_id=user_id,
    )

    return CreateSessionResponse(
        session_id=str(session.session_id),
        created_at=session.created_at.isoformat(),
    )


# ── GET /chat/sessions ─────────────────────────────────────────────────────

@router.get("/sessions", response_model=list[SessionResponse])
def list_sessions(
    db: Session = Depends(get_db),
    user_id: Optional[str] = Depends(_get_user_id),
):
    """
    List all active sessions for the current user.

    Filtered by X-User-ID header. Ordered by last_active_at descending.
    """
    stmt = (
        select(ChatSession)
        .where(ChatSession.is_active == True)  # noqa: E712
    )

    if user_id:
        stmt = stmt.where(ChatSession.user_identifier == user_id)

    stmt = stmt.order_by(ChatSession.last_active_at.desc())

    sessions = db.execute(stmt).scalars().all()

    return [_session_to_response(s) for s in sessions]


# ── GET /chat/sessions/{session_id} ────────────────────────────────────────

@router.get("/sessions/{session_id}", response_model=SessionResponse)
def get_session(
    session_id: str,
    db: Session = Depends(get_db),
):
    """Get session details by ID."""
    session = _get_active_session(db, session_id)
    return _session_to_response(session)


# ── PATCH /chat/sessions/{session_id} ──────────────────────────────────────

@router.patch("/sessions/{session_id}", response_model=SessionResponse)
def rename_session(
    session_id: str,
    request: RenameSessionRequest,
    db: Session = Depends(get_db),
):
    """Rename a session."""
    session = _get_active_session(db, session_id)
    session.name = request.name
    db.commit()
    db.refresh(session)

    log.info("chat_session_renamed", session_id=session_id, new_name=request.name)

    return _session_to_response(session)


# ── DELETE /chat/sessions/{session_id} ──────────────────────────────────────

@router.delete("/sessions/{session_id}", status_code=204)
def delete_session(
    session_id: str,
    db: Session = Depends(get_db),
):
    """
    Soft-delete a session. Sets is_active=false without deleting messages.
    """
    session = _get_active_session(db, session_id)
    session.is_active = False
    db.commit()

    log.info("chat_session_soft_deleted", session_id=session_id)


# ── GET /chat/sessions/{session_id}/messages ────────────────────────────────

@router.get(
    "/sessions/{session_id}/messages",
    response_model=list[MessageResponse],
)
def get_messages(
    session_id: str,
    limit: int = Query(default=50, ge=1, le=200, description="Number of messages to return"),
    before_message_id: Optional[str] = Query(
        default=None, description="Cursor: return messages before this message ID"
    ),
    db: Session = Depends(get_db),
):
    """
    Get paginated message history for a session.

    Returns messages in ascending created_at order (oldest first).
    Use before_message_id for cursor-based pagination to load older messages.
    """
    settings = get_settings()
    page_size = min(limit, settings.CHAT_MESSAGE_PAGE_SIZE)

    # Verify session exists
    _get_active_session(db, session_id)

    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session_id format")

    stmt = (
        select(ChatMessage)
        .where(ChatMessage.session_id == session_uuid)
    )

    # Cursor pagination: fetch messages before the given message
    if before_message_id:
        try:
            cursor_uuid = uuid.UUID(before_message_id)
        except ValueError:
            raise HTTPException(status_code=400, detail="Invalid before_message_id format")

        # Get the created_at of the cursor message
        cursor_msg = db.execute(
            select(ChatMessage.created_at)
            .where(ChatMessage.message_id == cursor_uuid)
        ).scalar_one_or_none()

        if cursor_msg is None:
            raise HTTPException(status_code=404, detail="Cursor message not found")

        stmt = stmt.where(ChatMessage.created_at < cursor_msg)

    # Order by created_at ascending, limit to page_size
    stmt = stmt.order_by(ChatMessage.created_at.asc())

    # For cursor pagination going backward, we need the LAST N messages before the cursor
    # So we order desc, limit, then reverse
    if before_message_id:
        stmt_desc = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_uuid)
            .where(ChatMessage.created_at < cursor_msg)
            .order_by(ChatMessage.created_at.desc())
            .limit(page_size)
        )
        messages = list(db.execute(stmt_desc).scalars().all())
        messages.reverse()  # Back to ascending order
    else:
        # No cursor — get the most recent N messages
        # Subquery to get the last page_size messages, then order ascending
        stmt_desc = (
            select(ChatMessage)
            .where(ChatMessage.session_id == session_uuid)
            .order_by(ChatMessage.created_at.desc())
            .limit(page_size)
        )
        messages = list(db.execute(stmt_desc).scalars().all())
        messages.reverse()  # Back to ascending order

    return [_message_to_response(m) for m in messages]


# ── Internal helpers ────────────────────────────────────────────────────────

def _get_active_session(db: Session, session_id: str) -> ChatSession:
    """
    Retrieve an active session by ID or raise HTTP 404.
    """
    try:
        session_uuid = uuid.UUID(session_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid session_id format")

    session = db.execute(
        select(ChatSession)
        .where(ChatSession.session_id == session_uuid)
        .where(ChatSession.is_active == True)  # noqa: E712
    ).scalar_one_or_none()

    if session is None:
        raise HTTPException(status_code=404, detail="Session not found or inactive")

    return session


# ── Redis client helper (same pattern as Feature 4 query router) ────────────

def _get_redis_client() -> Optional[Redis]:
    """
    Create a Redis client for context and suggestions caching.
    Returns None if Redis is unavailable.
    """
    try:
        settings = get_settings()
        client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        client.ping()
        return client
    except Exception as exc:
        log.warning("redis_unavailable_for_chat", error=str(exc))
        return None


# ── SSE formatting helper ───────────────────────────────────────────────────

def _sse_event(event_type: str, payload: dict) -> str:
    """Format an SSE event as `event: {type}\\ndata: {json}\\n\\n`."""
    return f"event: {event_type}\ndata: {json.dumps(payload)}\n\n"


# ── Request schemas for query endpoints ─────────────────────────────────────

class QuerySSERequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000, description="Natural language query")
    confirm: bool = Field(False, description="Confirm execution of large results")


class ConfirmRequest(BaseModel):
    message_id: str = Field(..., description="ID of the pending_confirmation assistant message")


class SuggestionItem(BaseModel):
    query: str
    description: str


class SuggestionsResponse(BaseModel):
    suggestions: list[SuggestionItem]


# ── POST /chat/sessions/{session_id}/query (SSE streaming) ─────────────────

@router.post("/sessions/{session_id}/query")
async def query_sse(
    session_id: str,
    request: QuerySSERequest,
    db: Session = Depends(get_db),
    readonly_db: Session = Depends(get_readonly_db),
):
    """
    SSE streaming query endpoint (FR-06).

    Wraps Feature 4's pipeline with session management, message persistence,
    and real-time event streaming.
    """
    # Validate session exists and is active
    session = _get_active_session(db, session_id)

    # Persist user message
    user_message = ChatMessage(
        message_id=uuid.uuid4(),
        session_id=session.session_id,
        role="user",
        content=request.query,
        nl_query=request.query,
    )
    db.add(user_message)
    db.commit()

    settings = get_settings()
    redis_client = _get_redis_client()

    async def event_generator() -> AsyncGenerator[str, None]:
        try:
            # 1. thinking
            yield _sse_event("thinking", {"status": "thinking"})

            # 2. Resolve geography & get context
            geography = resolve_geography(request.query)
            context = await get_context(redis_client, str(session.session_id))

            # 3. Run NL-to-SQL pipeline (direct import, Hard Rule 1)
            pipeline_result = await nl_to_sql(
                query=request.query,
                context=context,
                geography=geography,
                settings=settings,
            )

            # Handle pipeline error
            if pipeline_result.error or not pipeline_result.sql:
                error_payload = {
                    "error": pipeline_result.error or "Failed to generate SQL",
                    "error_type": "generation_failure",
                }
                # Persist error assistant message
                error_msg = ChatMessage(
                    message_id=uuid.uuid4(),
                    session_id=session.session_id,
                    role="assistant",
                    content=pipeline_result.error or "Failed to generate SQL",
                    error=error_payload,
                    status="error",
                )
                db.add(error_msg)
                session.last_active_at = datetime.now(timezone.utc)
                session.message_count += 1
                db.commit()

                yield _sse_event("error", error_payload)
                yield _sse_event("done", {"status": "done"})
                return

            sql = pipeline_result.sql

            # 4. interpreting — brief query-intent template + SQL (Gap B1)
            interpretation_preview = _build_interpretation_preview(request.query)
            yield _sse_event("interpreting", {
                "interpretation": interpretation_preview,
                "sql": sql,
            })

            # 5. Check row estimate for confirmation flow (Gap D1)
            estimated = estimate_rows(sql, readonly_db)
            if (
                estimated is not None
                and estimated > settings.QUERY_CONFIRMATION_THRESHOLD
                and not request.confirm
            ):
                # Persist assistant message with pending_confirmation status
                pending_msg = ChatMessage(
                    message_id=uuid.uuid4(),
                    session_id=session.session_id,
                    role="assistant",
                    content=interpretation_preview,
                    generated_sql=sql,
                    result_metadata={"estimated_rows": estimated},
                    status="pending_confirmation",
                )
                db.add(pending_msg)
                session.last_active_at = datetime.now(timezone.utc)
                session.message_count += 1
                db.commit()

                yield _sse_event("awaiting_confirmation", {
                    "message_id": str(pending_msg.message_id),
                    "estimated_rows": estimated,
                    "sql": sql,
                    "interpretation": interpretation_preview,
                })
                yield _sse_event("done", {"status": "done"})
                return

            # 6. executing
            yield _sse_event("executing", {"status": "executing"})

            # 7. Execute SQL on readonly session (Hard Rule 1 — direct import)
            exec_start = time.time()
            exec_result = execute_sql(sql, readonly_db, max_rows=settings.QUERY_MAX_ROWS)
            exec_time_ms = round((time.time() - exec_start) * 1000, 1)

            if exec_result.error:
                error_payload = {
                    "error": exec_result.error,
                    "error_type": "execution_error",
                }
                error_msg = ChatMessage(
                    message_id=uuid.uuid4(),
                    session_id=session.session_id,
                    role="assistant",
                    content=exec_result.error,
                    generated_sql=sql,
                    error=error_payload,
                    status="error",
                )
                db.add(error_msg)
                session.last_active_at = datetime.now(timezone.utc)
                session.message_count += 1
                db.commit()

                yield _sse_event("error", error_payload)
                yield _sse_event("done", {"status": "done"})
                return

            # 8. Interpret results (separate LLM call)
            interpretation = await interpret_results(
                query=request.query,
                sql=sql,
                columns=exec_result.columns,
                rows=exec_result.rows,
                row_count=exec_result.row_count,
                settings=settings,
            )

            # 9. results event (Hard Rule 2 — yield results BEFORE suggestions)
            results_payload = {
                "columns": exec_result.columns,
                "rows": exec_result.rows,
                "row_count": exec_result.row_count,
                "truncated": exec_result.truncated,
                "sql": sql,
                "interpretation": interpretation,
                "execution_time_ms": exec_time_ms,
                "attempt_count": pipeline_result.retries_used,
            }
            yield _sse_event("results", results_payload)

            # 10. Follow-up suggestions (must not block results — Hard Rule 2)
            try:
                follow_ups = await generate_follow_up_suggestions(
                    nl_query=request.query,
                    sql=sql,
                    column_names=exec_result.columns,
                    row_count=exec_result.row_count,
                    settings=settings,
                )
            except Exception:
                follow_ups = []

            yield _sse_event("suggestions", {"suggestions": follow_ups})

            # 11. Persist assistant message with all metadata
            result_metadata = {
                "columns": exec_result.columns,
                "row_count": exec_result.row_count,
                "truncated": exec_result.truncated,
                "execution_time_ms": exec_time_ms,
                "attempt_count": pipeline_result.retries_used,
            }
            assistant_msg = ChatMessage(
                message_id=uuid.uuid4(),
                session_id=session.session_id,
                role="assistant",
                content=interpretation,
                generated_sql=sql,
                result_metadata=result_metadata,
                follow_up_suggestions=follow_ups,
                status="completed",
            )
            db.add(assistant_msg)

            # 12. Update session metadata
            session.last_active_at = datetime.now(timezone.utc)
            session.message_count += 2  # user + assistant
            db.commit()

            # 13. Store context (user + assistant turns)
            await append_context(redis_client, str(session.session_id), {
                "role": "user",
                "content": request.query,
                "sql": None,
                "row_count": None,
            }, settings)

            await append_context(redis_client, str(session.session_id), {
                "role": "assistant",
                "content": interpretation,
                "sql": sql,
                "row_count": exec_result.row_count,
            }, settings)

            # 14. done
            yield _sse_event("done", {"status": "done"})

        except Exception as exc:
            log.error("sse_stream_error", session_id=session_id, error=str(exc))
            try:
                yield _sse_event("error", {
                    "error": f"Unexpected error: {exc}",
                    "error_type": "execution_error",
                })
                yield _sse_event("done", {"status": "done"})
            except Exception:
                pass

    return StreamingResponse(
        event_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── POST /chat/sessions/{session_id}/query/confirm (FR-09) ─────────────────

@router.post("/sessions/{session_id}/query/confirm")
async def confirm_query(
    session_id: str,
    request: ConfirmRequest,
    db: Session = Depends(get_db),
    readonly_db: Session = Depends(get_readonly_db),
):
    """
    Confirmation endpoint (FR-09).

    Retrieves server-stored SQL from a pending_confirmation message and
    executes it. Skips thinking and interpreting events.
    """
    # Validate session
    session = _get_active_session(db, session_id)
    settings = get_settings()
    redis_client = _get_redis_client()

    # Retrieve the pending message
    try:
        message_uuid = uuid.UUID(request.message_id)
    except ValueError:
        raise HTTPException(status_code=400, detail="Invalid message_id format")

    pending_msg = db.execute(
        select(ChatMessage)
        .where(ChatMessage.message_id == message_uuid)
        .where(ChatMessage.session_id == session.session_id)
        .where(ChatMessage.status == "pending_confirmation")
    ).scalar_one_or_none()

    if pending_msg is None:
        raise HTTPException(
            status_code=404,
            detail="Pending confirmation message not found",
        )

    if not pending_msg.generated_sql:
        raise HTTPException(
            status_code=400,
            detail="No SQL found on the pending message",
        )

    sql = pending_msg.generated_sql

    # Update status to confirmed
    pending_msg.status = "confirmed"
    db.commit()

    async def confirm_generator() -> AsyncGenerator[str, None]:
        try:
            # Skip thinking/interpreting — already shown to user
            yield _sse_event("executing", {"status": "executing"})

            # Execute SQL
            exec_start = time.time()
            exec_result = execute_sql(sql, readonly_db, max_rows=settings.QUERY_MAX_ROWS)
            exec_time_ms = round((time.time() - exec_start) * 1000, 1)

            if exec_result.error:
                error_payload = {
                    "error": exec_result.error,
                    "error_type": "execution_error",
                }
                pending_msg.error = error_payload
                pending_msg.status = "error"
                session.last_active_at = datetime.now(timezone.utc)
                db.commit()

                yield _sse_event("error", error_payload)
                yield _sse_event("done", {"status": "done"})
                return

            # Interpret results
            # Get the original query from the user message before this one
            original_query = pending_msg.content or "the previous query"
            interpretation = await interpret_results(
                query=original_query,
                sql=sql,
                columns=exec_result.columns,
                rows=exec_result.rows,
                row_count=exec_result.row_count,
                settings=settings,
            )

            # Results event
            results_payload = {
                "columns": exec_result.columns,
                "rows": exec_result.rows,
                "row_count": exec_result.row_count,
                "truncated": exec_result.truncated,
                "sql": sql,
                "interpretation": interpretation,
                "execution_time_ms": exec_time_ms,
                "attempt_count": 0,
            }
            yield _sse_event("results", results_payload)

            # Follow-ups
            try:
                follow_ups = await generate_follow_up_suggestions(
                    nl_query=original_query,
                    sql=sql,
                    column_names=exec_result.columns,
                    row_count=exec_result.row_count,
                    settings=settings,
                )
            except Exception:
                follow_ups = []

            yield _sse_event("suggestions", {"suggestions": follow_ups})

            # Update the pending message with results
            pending_msg.content = interpretation
            pending_msg.result_metadata = {
                "columns": exec_result.columns,
                "row_count": exec_result.row_count,
                "truncated": exec_result.truncated,
                "execution_time_ms": exec_time_ms,
                "attempt_count": 0,
            }
            pending_msg.follow_up_suggestions = follow_ups
            pending_msg.status = "completed"
            session.last_active_at = datetime.now(timezone.utc)
            db.commit()

            # Store context
            await append_context(redis_client, str(session.session_id), {
                "role": "assistant",
                "content": interpretation,
                "sql": sql,
                "row_count": exec_result.row_count,
            }, settings)

            yield _sse_event("done", {"status": "done"})

        except Exception as exc:
            log.error("confirm_stream_error", session_id=session_id, error=str(exc))
            try:
                yield _sse_event("error", {
                    "error": f"Unexpected error: {exc}",
                    "error_type": "execution_error",
                })
                yield _sse_event("done", {"status": "done"})
            except Exception:
                pass

    return StreamingResponse(
        confirm_generator(),
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )


# ── GET /chat/suggestions (FR-08) ──────────────────────────────────────────

@router.get("/suggestions", response_model=SuggestionsResponse)
def get_suggestions(
    db: Session = Depends(get_db),
):
    """
    Load-time suggestions endpoint (FR-08).

    Returns 4–6 example queries tailored to available datasets.
    Cached in Redis for 1 hour.
    """
    settings = get_settings()
    redis_client = _get_redis_client()

    suggestions = generate_load_time_suggestions(db, redis_client, settings)

    return SuggestionsResponse(
        suggestions=[SuggestionItem(**s) for s in suggestions]
    )


# ── SSE helpers ─────────────────────────────────────────────────────────────

def _build_interpretation_preview(query: str) -> str:
    """
    Build a brief query-intent interpretation for the `interpreting` event.

    This is NOT the full interpret_results() output — that requires
    execution data. This is a short template derived from the query
    (Gap B1 resolution).
    """
    query_lower = query.lower()

    if any(word in query_lower for word in ["how many", "count", "number of"]):
        return "I'll count the matching records in the database..."
    elif any(word in query_lower for word in ["average", "mean", "avg"]):
        return "I'll calculate the average values from the matching data..."
    elif any(word in query_lower for word in ["show", "list", "find", "get"]):
        return "I'll search for matching ocean data profiles..."
    elif any(word in query_lower for word in ["compare", "between", "versus"]):
        return "I'll compare the requested data sets..."
    elif any(word in query_lower for word in ["maximum", "minimum", "max", "min"]):
        return "I'll find the extreme values in the matching data..."
    else:
        return "I'll query the ocean data database for you..."
