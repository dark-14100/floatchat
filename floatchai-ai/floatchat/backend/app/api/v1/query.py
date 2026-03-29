"""
FloatChat NL Query Engine - API Router

Two endpoints:
  POST /query           - Full NL-to-SQL pipeline with execution
  POST /query/benchmark - Compare SQL generation across LLM providers (no execution)
"""

import time
import uuid
from typing import Optional

import structlog
from fastapi import APIRouter, Body, Depends, HTTPException, Request
from pydantic import BaseModel, Field
from redis import Redis
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.auth.dependencies import get_api_key_or_user
from app.config import get_settings
from app.db.models import ApiKey, User
from app.db.session import SessionLocal, get_readonly_db
from app.monitoring.sentry import set_sentry_request_tags
from app.query.context import append_context, get_context
from app.query.executor import estimate_rows, execute_sql
from app.query.geography import resolve_geography
from app.query.pipeline import _PROVIDER_CONFIG, interpret_results, nl_to_sql
from app.rate_limiter import limiter

log = structlog.get_logger(__name__)

router = APIRouter(prefix="/query", tags=["Query"], dependencies=[Depends(get_api_key_or_user)])


def _query_rate_limit(key: str) -> str:
    settings = get_settings()
    if isinstance(key, str) and key.startswith("apikey:"):
        api_key_id = key.split(":", 1)[1]
        db = SessionLocal()
        try:
            api_key = db.scalar(select(ApiKey).where(ApiKey.key_id == uuid.UUID(api_key_id)))
            if api_key and api_key.rate_limit_override:
                return f"{int(api_key.rate_limit_override)}/minute"
        except Exception:
            pass
        finally:
            db.close()
        return f"{settings.API_KEY_RATE_LIMIT_PER_MINUTE}/minute"
    return f"{settings.JWT_RATE_LIMIT_PER_MINUTE}/minute"


def _get_redis_client() -> Optional[Redis]:
    """Create a Redis client for conversation context; return None on failure."""
    try:
        settings = get_settings()
        client = Redis.from_url(settings.REDIS_URL, decode_responses=True)
        client.ping()
        return client
    except Exception as exc:
        log.warning("redis_unavailable_for_query_context", error=str(exc))
        return None


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


@router.post("", response_model=QueryResponse)
@limiter.limit(_query_rate_limit)
async def query_endpoint(
    request: Request,
    payload: QueryRequest = Body(...),
    db: Session = Depends(get_readonly_db),
    current_user: User = Depends(get_api_key_or_user),
):
    """Natural language query endpoint."""
    settings = get_settings()
    set_sentry_request_tags(
        query_type="nl_query",
        provider=payload.provider or settings.QUERY_LLM_PROVIDER,
        user_id=str(current_user.user_id),
        api_key_request=bool(getattr(current_user, "api_key_scoped", False)),
    )
    session_id = payload.session_id or str(uuid.uuid4())
    redis_client = _get_redis_client()

    geography = resolve_geography(payload.query)
    context = await get_context(redis_client, session_id)

    pipeline_result = await nl_to_sql(
        query=payload.query,
        context=context,
        geography=geography,
        settings=settings,
        provider=payload.provider,
        model=payload.model,
        user_id=current_user.user_id,
        db=db,
        api_key_scoped=bool(getattr(current_user, "api_key_scoped", False)),
    )

    if pipeline_result.error or not pipeline_result.sql:
        await append_context(
            redis_client,
            session_id,
            {"role": "user", "content": payload.query, "sql": None, "row_count": None},
            settings,
        )
        return QueryResponse(
            session_id=session_id,
            sql=pipeline_result.sql,
            error=pipeline_result.error,
            provider=pipeline_result.provider,
            model=pipeline_result.model,
        )

    sql = pipeline_result.sql

    if payload.confirm_execution is not True:
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

    exec_result = execute_sql(sql, db, max_rows=settings.QUERY_MAX_ROWS)
    if exec_result.error:
        return QueryResponse(
            session_id=session_id,
            sql=sql,
            error=exec_result.error,
            provider=pipeline_result.provider,
            model=pipeline_result.model,
        )

    interpretation = await interpret_results(
        query=payload.query,
        sql=sql,
        columns=exec_result.columns,
        rows=exec_result.rows,
        row_count=exec_result.row_count,
        settings=settings,
    )

    await append_context(
        redis_client,
        session_id,
        {"role": "user", "content": payload.query, "sql": None, "row_count": None},
        settings,
    )
    await append_context(
        redis_client,
        session_id,
        {
            "role": "assistant",
            "content": interpretation,
            "sql": sql,
            "row_count": exec_result.row_count,
        },
        settings,
    )

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


@router.post("/benchmark", response_model=BenchmarkResponse)
@limiter.limit(_query_rate_limit)
async def benchmark_endpoint(
    request: Request,
    payload: BenchmarkRequest = Body(...),
    current_user: User = Depends(get_api_key_or_user),
):
    """Benchmark SQL generation across multiple LLM providers without execution."""
    del request

    settings = get_settings()
    set_sentry_request_tags(
        query_type="query_benchmark",
        user_id=str(current_user.user_id),
        api_key_request=bool(getattr(current_user, "api_key_scoped", False)),
    )
    total_timeout = settings.QUERY_BENCHMARK_TIMEOUT
    start_time = time.time()

    if payload.providers:
        providers = [p.lower().strip() for p in payload.providers]
    else:
        providers = _get_configured_providers(settings)

    if not providers:
        raise HTTPException(
            status_code=400,
            detail="No LLM providers configured. Set at least one provider API key.",
        )

    geography = resolve_geography(payload.query)
    results: list[BenchmarkProviderResult] = []

    for provider in providers:
        elapsed = time.time() - start_time
        if elapsed >= total_timeout:
            results.append(
                BenchmarkProviderResult(
                    provider=provider,
                    model="",
                    error=f"Skipped - total benchmark timeout ({total_timeout}s) exceeded.",
                )
            )
            continue

        t0 = time.time()
        try:
            pipeline_result = await nl_to_sql(
                query=payload.query,
                context=[],
                geography=geography,
                settings=settings,
                provider=provider,
            )
            latency_ms = (time.time() - t0) * 1000
            results.append(
                BenchmarkProviderResult(
                    provider=pipeline_result.provider,
                    model=pipeline_result.model,
                    sql=pipeline_result.sql,
                    valid=pipeline_result.sql is not None and pipeline_result.error is None,
                    validation_errors=pipeline_result.validation_errors,
                    latency_ms=round(latency_ms, 1),
                    error=pipeline_result.error,
                )
            )
        except Exception as exc:
            latency_ms = (time.time() - t0) * 1000
            results.append(
                BenchmarkProviderResult(
                    provider=provider,
                    model="",
                    latency_ms=round(latency_ms, 1),
                    error=str(exc),
                )
            )

    log.info(
        "benchmark_complete",
        query_preview=payload.query[:80],
        provider_count=len(results),
        total_ms=round((time.time() - start_time) * 1000, 1),
    )

    return BenchmarkResponse(query=payload.query, results=results)


def _get_configured_providers(settings) -> list[str]:
    """Return list of providers that have API keys set."""
    configured = []
    for provider, config in _PROVIDER_CONFIG.items():
        key = getattr(settings, config["key_attr"], None)
        if key:
            configured.append(provider)
    return configured
