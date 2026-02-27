"""
FloatChat NL Query Engine — API Router

Two endpoints:
  POST /query           — Full NL-to-SQL pipeline with execution
  POST /query/benchmark — Compare SQL generation across LLM providers (no execution)

Context is stored HERE after execution completes (Gap 3 resolution).
Redis client is created locally — returns None on failure (Gap 6 resolution).
"""

import time
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from redis import Redis
from sqlalchemy.orm import Session

from app.config import get_settings
from app.db.session import get_readonly_db
from app.query.context import append_context, clear_context, get_context
from app.query.executor import estimate_rows, execute_sql
from app.query.geography import resolve_geography
from app.query.pipeline import nl_to_sql, interpret_results, get_llm_client, _PROVIDER_CONFIG

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/query", tags=["Query"])


# ── Redis client helper (local to this router, Gap 6) ──────────────────────

def _get_redis_client() -> Optional[Redis]:
    """
    Create a Redis client for conversation context.
    Returns None if Redis is unavailable — the query engine continues without
    context rather than failing.
    """
    try:
        settings = get_settings()
        client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        client.ping()
        return client
    except Exception as exc:
        log.warning("redis_unavailable_for_query_context", error=str(exc))
        return None


# ── Request / Response schemas ──────────────────────────────────────────────

class QueryRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000, description="Natural language query")
    session_id: Optional[str] = Field(None, description="Session ID for conversation context")
    provider: Optional[str] = Field(None, description="Override LLM provider")
    model: Optional[str] = Field(None, description="Override LLM model")
    confirm_execution: Optional[bool] = Field(None, description="Confirm large result execution")


class QueryResponse(BaseModel):
    session_id: str
    sql: Optional[str] = None
    columns: list[str] = []
    rows: list[dict] = []
    row_count: int = 0
    truncated: bool = False
    interpretation: Optional[str] = None
    confirmation_required: Optional[bool] = None
    estimated_rows: Optional[int] = None
    error: Optional[str] = None
    provider: str = ""
    model: str = ""


class BenchmarkRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000, description="Natural language query")
    providers: Optional[list[str]] = Field(None, description="Providers to benchmark (default: all configured)")


class BenchmarkProviderResult(BaseModel):
    provider: str
    model: str
    sql: Optional[str] = None
    valid: bool = False
    validation_errors: list[str] = []
    latency_ms: float = 0.0
    error: Optional[str] = None


class BenchmarkResponse(BaseModel):
    query: str
    results: list[BenchmarkProviderResult] = []


# ── POST /query ─────────────────────────────────────────────────────────────

@router.post("", response_model=QueryResponse)
async def query_endpoint(
    request: QueryRequest,
    db: Session = Depends(get_readonly_db),
):
    """
    Natural language query endpoint.

    Flow: geography → context → pipeline (NL→SQL) → estimate → execute →
    interpret → store context.
    """
    settings = get_settings()
    session_id = request.session_id or str(uuid.uuid4())
    redis_client = _get_redis_client()

    # 1. Resolve geography
    geography = resolve_geography(request.query)

    # 2. Get conversation context
    context = await get_context(redis_client, session_id)

    # 3. Run NL-to-SQL pipeline
    pipeline_result = await nl_to_sql(
        query=request.query,
        context=context,
        geography=geography,
        settings=settings,
        provider=request.provider,
        model=request.model,
    )

    if pipeline_result.error or not pipeline_result.sql:
        # Store user turn even on failure (no SQL, no row_count)
        await append_context(redis_client, session_id, {
            "role": "user",
            "content": request.query,
            "sql": None,
            "row_count": None,
        }, settings)

        return QueryResponse(
            session_id=session_id,
            sql=pipeline_result.sql,
            error=pipeline_result.error,
            provider=pipeline_result.provider,
            model=pipeline_result.model,
        )

    sql = pipeline_result.sql

    # 4. Estimate rows (confirmation flow)
    if request.confirm_execution is not True:
        estimated = estimate_rows(sql, db)
        if estimated is not None and estimated > settings.QUERY_CONFIRMATION_THRESHOLD:
            return QueryResponse(
                session_id=session_id,
                sql=sql,
                confirmation_required=True,
                estimated_rows=estimated,
                provider=pipeline_result.provider,
                model=pipeline_result.model,
            )

    # 5. Execute SQL
    exec_result = execute_sql(sql, db, max_rows=settings.QUERY_MAX_ROWS)

    if exec_result.error:
        return QueryResponse(
            session_id=session_id,
            sql=sql,
            error=exec_result.error,
            provider=pipeline_result.provider,
            model=pipeline_result.model,
        )

    # 6. Interpret results (separate LLM call)
    interpretation = await interpret_results(
        query=request.query,
        sql=sql,
        columns=exec_result.columns,
        rows=exec_result.rows,
        row_count=exec_result.row_count,
        settings=settings,
    )

    # 7. Store context AFTER execution with real row_count (Gap 3)
    await append_context(redis_client, session_id, {
        "role": "user",
        "content": request.query,
        "sql": None,
        "row_count": None,
    }, settings)

    await append_context(redis_client, session_id, {
        "role": "assistant",
        "content": interpretation,
        "sql": sql,
        "row_count": exec_result.row_count,
    }, settings)

    return QueryResponse(
        session_id=session_id,
        sql=sql,
        columns=exec_result.columns,
        rows=exec_result.rows,
        row_count=exec_result.row_count,
        truncated=exec_result.truncated,
        interpretation=interpretation,
        provider=pipeline_result.provider,
        model=pipeline_result.model,
    )


# ── POST /query/benchmark ──────────────────────────────────────────────────

@router.post("/benchmark", response_model=BenchmarkResponse)
async def benchmark_endpoint(request: BenchmarkRequest):
    """
    Benchmark SQL generation across multiple LLM providers.

    SQL generation only — no execution (safe + fast).
    Runs providers sequentially with a total timeout.
    """
    settings = get_settings()
    total_timeout = settings.QUERY_BENCHMARK_TIMEOUT
    start_time = time.time()

    # Determine which providers to benchmark
    if request.providers:
        providers = [p.lower().strip() for p in request.providers]
    else:
        # All providers that have API keys configured
        providers = _get_configured_providers(settings)

    if not providers:
        raise HTTPException(
            status_code=400,
            detail="No LLM providers configured. Set at least one provider API key.",
        )

    geography = resolve_geography(request.query)
    results: list[BenchmarkProviderResult] = []

    for provider in providers:
        # Check total timeout
        elapsed = time.time() - start_time
        if elapsed >= total_timeout:
            results.append(BenchmarkProviderResult(
                provider=provider,
                model="",
                error=f"Skipped — total benchmark timeout ({total_timeout}s) exceeded.",
            ))
            continue

        t0 = time.time()
        try:
            pipeline_result = await nl_to_sql(
                query=request.query,
                context=[],           # No context for benchmarks
                geography=geography,
                settings=settings,
                provider=provider,
            )
            latency_ms = (time.time() - t0) * 1000

            results.append(BenchmarkProviderResult(
                provider=pipeline_result.provider,
                model=pipeline_result.model,
                sql=pipeline_result.sql,
                valid=pipeline_result.sql is not None and pipeline_result.error is None,
                validation_errors=pipeline_result.validation_errors,
                latency_ms=round(latency_ms, 1),
                error=pipeline_result.error,
            ))

        except Exception as exc:
            latency_ms = (time.time() - t0) * 1000
            results.append(BenchmarkProviderResult(
                provider=provider,
                model="",
                latency_ms=round(latency_ms, 1),
                error=str(exc),
            ))

    log.info(
        "benchmark_complete",
        query_preview=request.query[:80],
        provider_count=len(results),
        total_ms=round((time.time() - start_time) * 1000, 1),
    )

    return BenchmarkResponse(query=request.query, results=results)


# ── Helpers ─────────────────────────────────────────────────────────────────

def _get_configured_providers(settings) -> list[str]:
    """Return list of providers that have API keys set."""
    configured = []
    for provider, config in _PROVIDER_CONFIG.items():
        key = getattr(settings, config["key_attr"], None)
        if key:
            configured.append(provider)
    return configured
