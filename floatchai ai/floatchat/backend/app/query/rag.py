"""
FloatChat RAG Query History Module

Provides storage and retrieval helpers for tenant-scoped query-learning:
    - store_successful_query: fire-and-forget safe write path
    - retrieve_similar_queries: read path for dynamic few-shot examples
    - build_rag_context: prompt formatting helper

Hard rules:
    - Use embed_texts() from app.search.embeddings for all embeddings
    - Never raise from store/retrieve paths
    - Enforce user_id filtering at SQL layer for retrieval
"""

from datetime import datetime, timedelta, timezone
from typing import Any
from uuid import UUID

import openai
import structlog
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import QueryHistory
from app.search.embeddings import embed_texts

store_log = structlog.get_logger("rag.store")
retrieve_log = structlog.get_logger("rag.retrieve")
build_log = structlog.get_logger("rag.build_context")

# Module-level client pattern (decision D1). If no key is configured, retrieval
# and storage gracefully degrade to no-op behavior.
OPENAI_CLIENT = (
    openai.OpenAI(
        api_key=settings.OPENAI_API_KEY,
        timeout=settings.LLM_TIMEOUT_SECONDS,
    )
    if settings.OPENAI_API_KEY
    else None
)


def _embed_nl_query(nl_query: str) -> list[float]:
    """Embed one query text through the shared embedding pipeline."""
    if OPENAI_CLIENT is None:
        raise RuntimeError("OPENAI_API_KEY is not configured for RAG embeddings")

    vectors = embed_texts([nl_query], OPENAI_CLIENT)
    if not vectors:
        raise RuntimeError("Embedding generation returned no vectors")

    return vectors[0]


def store_successful_query(
    nl_query: str,
    generated_sql: str,
    row_count: int,
    user_id: UUID,
    session_id: UUID | None,
    provider: str,
    model: str,
    db: Session,
) -> None:
    """
    Persist a successful NL query for future retrieval.

    This function must never raise. Any exception is logged and swallowed.
    """
    try:
        if row_count <= 0:
            store_log.debug(
                "rag_store_skipped_zero_rows",
                user_id=str(user_id),
            )
            return

        dedup_cutoff = datetime.now(timezone.utc) - timedelta(
            hours=settings.RAG_DEDUP_WINDOW_HOURS
        )

        existing_query_id = db.execute(
            select(QueryHistory.query_id)
            .where(QueryHistory.user_id == user_id)
            .where(QueryHistory.nl_query == nl_query)
            .where(QueryHistory.created_at > dedup_cutoff)
            .limit(1)
        ).scalar_one_or_none()

        if existing_query_id is not None:
            store_log.debug(
                "rag_store_dedup_skipped",
                user_id=str(user_id),
                dedup_window_hours=settings.RAG_DEDUP_WINDOW_HOURS,
            )
            return

        query_vector = _embed_nl_query(nl_query)

        history = QueryHistory(
            nl_query=nl_query,
            generated_sql=generated_sql,
            embedding=query_vector,
            row_count=row_count,
            user_id=user_id,
            session_id=session_id,
            provider=provider,
            model=model,
        )
        db.add(history)
        db.commit()

        store_log.debug(
            "rag_store_success",
            user_id=str(user_id),
            session_id=str(session_id) if session_id else None,
            row_count=row_count,
        )
    except Exception as exc:  # noqa: BLE001
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass

        store_log.warning(
            "rag_store_failed",
            user_id=str(user_id),
            error=str(exc),
        )


def retrieve_similar_queries(
    nl_query: str,
    user_id: UUID,
    db: Session,
    limit: int | None = None,
) -> list[dict[str, Any]]:
    """
    Retrieve similar successful queries for one tenant.

    This function must never raise. Any exception is logged and returns [].
    """
    retrieval_limit = limit or settings.RAG_RETRIEVAL_LIMIT

    try:
        query_vector = _embed_nl_query(nl_query)

        cosine_distance = QueryHistory.embedding.cosine_distance(query_vector).label(
            "cosine_distance"
        )

        rows = db.execute(
            select(
                QueryHistory.nl_query,
                QueryHistory.generated_sql,
                QueryHistory.row_count,
                cosine_distance,
            )
            .where(QueryHistory.user_id == user_id)
            .where(cosine_distance < settings.RAG_SIMILARITY_THRESHOLD)
            .order_by(cosine_distance.asc())
            .limit(retrieval_limit)
        ).all()

        results = [
            {
                "nl_query": row.nl_query,
                "generated_sql": row.generated_sql,
                "row_count": row.row_count,
            }
            for row in rows
        ]

        retrieve_log.debug(
            "rag_retrieve_examples",
            user_id=str(user_id),
            threshold=settings.RAG_SIMILARITY_THRESHOLD,
            requested_limit=retrieval_limit,
            returned_count=len(results),
            examples=[
                {
                    "nl_query": item["nl_query"],
                    "generated_sql": item["generated_sql"],
                }
                for item in results
            ],
        )

        return results
    except Exception as exc:  # noqa: BLE001
        try:
            db.rollback()
        except Exception:  # noqa: BLE001
            pass

        retrieve_log.warning(
            "rag_retrieve_failed",
            user_id=str(user_id),
            error=str(exc),
        )
        return []


def build_rag_context(similar_queries: list[dict[str, Any]]) -> str:
    """Format retrieved query history into prompt-compatible few-shot examples."""
    if not similar_queries:
        return ""

    blocks: list[str] = []
    for idx, item in enumerate(similar_queries, start=1):
        history_query = str(item.get("nl_query", "")).strip()
        history_sql = str(item.get("generated_sql", "")).strip()
        history_rows = item.get("row_count")

        if not history_query or not history_sql:
            continue

        blocks.append(
            "\n".join(
                [
                    f"-- Query History Example {idx}",
                    f"Q: {history_query}",
                    f"Historical row_count: {history_rows}",
                    "```sql",
                    history_sql,
                    "```",
                ]
            )
        )

    if not blocks:
        return ""

    context = (
        "The following are real examples from your query history that succeeded against this database:\n\n"
        + "\n\n".join(blocks)
        + "\n"
    )

    build_log.debug(
        "rag_context_built",
        example_count=len(blocks),
        context_length=len(context),
    )

    return context
