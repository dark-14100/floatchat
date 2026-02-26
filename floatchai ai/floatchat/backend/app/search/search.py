"""
FloatChat Semantic Search Module

Implements semantic similarity search over dataset and float embeddings
using pgvector's cosine distance operator (<=>) with hybrid scoring.

Functions:
    search_datasets  — Semantic search over dataset embeddings with filters
    search_floats    — Semantic search over float embeddings with filters

Rules:
    - Always use the <=> cosine distance operator (Hard Rule #6)
    - Never return results below SEARCH_SIMILARITY_THRESHOLD (Hard Rule #5)
    - Never log embedding vectors — only metadata (Hard Rule #9)
    - Fuzzy region matching goes through resolve_region_name (Hard Rule #7)
    - Empty list is a valid response when no results meet threshold
"""

import time
from datetime import datetime, timedelta, timezone
from typing import Any, Optional

import structlog
from geoalchemy2.functions import ST_Intersects
from sqlalchemy import select
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    Dataset,
    DatasetEmbedding,
    Float,
    FloatEmbedding,
    OceanRegion,
)
from app.search.embeddings import embed_single

logger = structlog.get_logger(__name__)


def _resolve_region_polygon(region_name: str, db: Session):
    """
    Resolve a region name to its OceanRegion record via the centralized
    resolve_region_name function from the discovery module (Hard Rule #7).

    Falls back to an exact-match query if the discovery module is not
    yet available (pre-Phase 8).

    Returns the OceanRegion object or None if not found.
    """
    # Try using the centralized fuzzy resolver (Hard Rule #7)
    try:
        from app.search.discovery import resolve_region_name
        return resolve_region_name(region_name, db)
    except ImportError:
        # Discovery module not yet implemented — fall back to exact match
        pass
    except ValueError:
        # Region not found by fuzzy matcher — no boost to apply
        return None

    # Fallback: exact match on region_name
    region = db.execute(
        select(OceanRegion).where(OceanRegion.region_name == region_name)
    ).scalar_one_or_none()
    return region


def search_datasets(
    query: str,
    db: Session,
    openai_client,
    filters: Optional[dict[str, Any]] = None,
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    """
    Semantic similarity search over dataset embeddings with hybrid scoring.

    Steps:
        1. Embed the query using embed_single
        2. Query dataset_embeddings using <=> cosine distance for 3× limit candidates
        3. Join datasets table to apply structured filters
        4. Filter out status='embedding_failed'
        5. Apply recency boost (+0.05 for recent datasets)
        6. Apply region boost (+0.10 when region filter matches bbox)
        7. Filter results below SEARCH_SIMILARITY_THRESHOLD
        8. Sort by final score descending, return top limit results

    Args:
        query: Plain English search text.
        db: SQLAlchemy session.
        openai_client: An openai.OpenAI client instance.
        filters: Optional dict with keys: variable, float_type, date_from,
                 date_to, region_name.
        limit: Max results to return. Defaults to SEARCH_DEFAULT_LIMIT,
               capped at SEARCH_MAX_LIMIT.

    Returns:
        List of dicts with: dataset_id, name, summary_text, score,
        date_range_start, date_range_end, float_count, variable_list.

    Raises:
        ValueError: If limit exceeds SEARCH_MAX_LIMIT.
    """
    start_time = time.time()
    filters = filters or {}

    # Validate and set limit
    if limit is None:
        limit = settings.SEARCH_DEFAULT_LIMIT
    if limit > settings.SEARCH_MAX_LIMIT:
        raise ValueError(
            f"limit ({limit}) exceeds maximum ({settings.SEARCH_MAX_LIMIT})"
        )

    # 1. Embed the query text
    query_vector = embed_single(query, openai_client)

    # 2. Build the candidate query — retrieve 3× limit before filtering/boosting
    candidate_limit = limit * 3
    cosine_distance = DatasetEmbedding.embedding.cosine_distance(query_vector)

    stmt = (
        select(
            DatasetEmbedding.dataset_id,
            DatasetEmbedding.status,
            Dataset.name,
            Dataset.summary_text,
            Dataset.date_range_start,
            Dataset.date_range_end,
            Dataset.float_count,
            Dataset.variable_list,
            Dataset.ingestion_date,
            Dataset.bbox,
            Dataset.is_active,
            cosine_distance.label("cosine_distance"),
        )
        .join(Dataset, DatasetEmbedding.dataset_id == Dataset.dataset_id)
        .where(DatasetEmbedding.status == "indexed")
        .where(Dataset.is_active == True)  # noqa: E712
        .order_by(cosine_distance.asc())
        .limit(candidate_limit)
    )

    # 3. Apply structured filters
    if filters.get("variable"):
        # variable_list is JSONB — check if it contains the variable key
        variable = filters["variable"]
        stmt = stmt.where(
            Dataset.variable_list.has_key(variable)  # noqa: W601
        )

    if filters.get("float_type"):
        # Filter datasets that have profiles from floats of a specific type.
        # Join through profiles → floats to check float_type.
        from app.db.models import Profile
        float_type = filters["float_type"]
        float_subquery = (
            select(Profile.dataset_id)
            .join(Float, Profile.float_id == Float.float_id)
            .where(Float.float_type == float_type)
            .distinct()
            .subquery()
        )
        stmt = stmt.where(
            DatasetEmbedding.dataset_id.in_(select(float_subquery.c.dataset_id))
        )

    if filters.get("date_from"):
        date_from = filters["date_from"]
        if isinstance(date_from, str):
            date_from = datetime.fromisoformat(date_from)
        stmt = stmt.where(Dataset.date_range_end >= date_from)

    if filters.get("date_to"):
        date_to = filters["date_to"]
        if isinstance(date_to, str):
            date_to = datetime.fromisoformat(date_to)
        stmt = stmt.where(Dataset.date_range_start <= date_to)

    # Execute candidate query
    rows = db.execute(stmt).all()

    # 4–8. Apply hybrid scoring and filtering
    recency_cutoff = datetime.now(timezone.utc) - timedelta(
        days=settings.RECENCY_BOOST_DAYS
    )

    # Resolve region polygon if region filter provided (for region boost)
    region_obj = None
    if filters.get("region_name"):
        region_obj = _resolve_region_polygon(filters["region_name"], db)

    results = []
    for row in rows:
        # Base score: 1 - cosine_distance (FR-16)
        cosine_score = 1.0 - float(row.cosine_distance)

        # Skip if base cosine similarity is extremely low (negative scores)
        if cosine_score <= 0:
            continue

        score = cosine_score

        # 5. Recency boost
        if row.ingestion_date and row.ingestion_date >= recency_cutoff:
            score += settings.RECENCY_BOOST_VALUE

        # 6. Region match boost
        if region_obj is not None and row.bbox is not None:
            try:
                intersects = db.execute(
                    select(
                        ST_Intersects(row.bbox, region_obj.geom)
                    )
                ).scalar()
                if intersects:
                    score += settings.REGION_MATCH_BOOST_VALUE
            except Exception:
                # If spatial check fails, skip the boost silently
                pass

        # Cap score at 1.0
        score = min(score, 1.0)

        # 7. Filter below threshold (Hard Rule #5)
        if score < settings.SEARCH_SIMILARITY_THRESHOLD:
            continue

        results.append({
            "dataset_id": row.dataset_id,
            "name": row.name,
            "summary_text": row.summary_text,
            "score": round(score, 4),
            "date_range_start": (
                row.date_range_start.isoformat() if row.date_range_start else None
            ),
            "date_range_end": (
                row.date_range_end.isoformat() if row.date_range_end else None
            ),
            "float_count": row.float_count,
            "variable_list": row.variable_list,
        })

    # 8. Sort by final score descending, return top limit
    results.sort(key=lambda r: r["score"], reverse=True)
    results = results[:limit]

    elapsed = round(time.time() - start_time, 3)
    logger.info(
        "search_datasets",
        query=query[:100],
        filter_keys=list(filters.keys()) if filters else [],
        result_count=len(results),
        candidate_count=len(rows),
        elapsed_seconds=elapsed,
    )

    return results


def search_floats(
    query: str,
    db: Session,
    openai_client,
    filters: Optional[dict[str, Any]] = None,
    limit: Optional[int] = None,
) -> list[dict[str, Any]]:
    """
    Semantic similarity search over float embeddings with hybrid scoring.

    Same structure as search_datasets but searches float_embeddings
    and joins the floats table for filtering.

    Args:
        query: Plain English search text.
        db: SQLAlchemy session.
        openai_client: An openai.OpenAI client instance.
        filters: Optional dict with keys: float_type, region_name.
        limit: Max results to return. Defaults to SEARCH_DEFAULT_LIMIT,
               capped at SEARCH_MAX_LIMIT.

    Returns:
        List of dicts with: float_id, platform_number, float_type, score,
        deployment_lat, deployment_lon.

    Raises:
        ValueError: If limit exceeds SEARCH_MAX_LIMIT.
    """
    start_time = time.time()
    filters = filters or {}

    # Validate and set limit
    if limit is None:
        limit = settings.SEARCH_DEFAULT_LIMIT
    if limit > settings.SEARCH_MAX_LIMIT:
        raise ValueError(
            f"limit ({limit}) exceeds maximum ({settings.SEARCH_MAX_LIMIT})"
        )

    # 1. Embed the query text
    query_vector = embed_single(query, openai_client)

    # 2. Build the candidate query — retrieve 3× limit
    candidate_limit = limit * 3
    cosine_distance = FloatEmbedding.embedding.cosine_distance(query_vector)

    stmt = (
        select(
            FloatEmbedding.float_id,
            FloatEmbedding.status,
            Float.platform_number,
            Float.float_type,
            Float.deployment_lat,
            Float.deployment_lon,
            Float.deployment_date,
            cosine_distance.label("cosine_distance"),
        )
        .join(Float, FloatEmbedding.float_id == Float.float_id)
        .where(FloatEmbedding.status == "indexed")
        .order_by(cosine_distance.asc())
        .limit(candidate_limit)
    )

    # 3. Apply structured filters
    if filters.get("float_type"):
        stmt = stmt.where(Float.float_type == filters["float_type"])

    if filters.get("region_name"):
        region_obj = _resolve_region_polygon(filters["region_name"], db)
        if region_obj is not None:
            # Filter floats whose deployment position falls within the region
            from geoalchemy2.functions import ST_Contains as _ST_Contains
            from sqlalchemy import func as _func

            stmt = stmt.where(
                _ST_Contains(
                    region_obj.geom,
                    _func.ST_SetSRID(
                        _func.ST_MakePoint(
                            Float.deployment_lon, Float.deployment_lat
                        ),
                        4326,
                    ),
                )
            )

    # Execute candidate query
    rows = db.execute(stmt).all()

    # 4–8. Apply scoring and filtering
    results = []
    for row in rows:
        # Base score: 1 - cosine_distance
        cosine_score = 1.0 - float(row.cosine_distance)

        if cosine_score <= 0:
            continue

        score = cosine_score

        # Cap score at 1.0
        score = min(score, 1.0)

        # Filter below threshold (Hard Rule #5)
        if score < settings.SEARCH_SIMILARITY_THRESHOLD:
            continue

        results.append({
            "float_id": row.float_id,
            "platform_number": row.platform_number,
            "float_type": row.float_type,
            "score": round(score, 4),
            "deployment_lat": row.deployment_lat,
            "deployment_lon": row.deployment_lon,
        })

    # Sort by score descending, return top limit
    results.sort(key=lambda r: r["score"], reverse=True)
    results = results[:limit]

    elapsed = round(time.time() - start_time, 3)
    logger.info(
        "search_floats",
        query=query[:100],
        filter_keys=list(filters.keys()) if filters else [],
        result_count=len(results),
        candidate_count=len(rows),
        elapsed_seconds=elapsed,
    )

    return results
