"""
FloatChat Search API Router

REST API endpoints for dataset/float semantic search, float discovery,
dataset summaries, and manual re-indexing.

Mount point: /api/v1/search

Endpoints:
    GET    /datasets                      — Semantic search over datasets
    GET    /floats                        — Semantic search over floats
    GET    /floats/by-region              — Spatial float discovery by region
    GET    /datasets/{dataset_id}/summary — Rich summary for one dataset
    GET    /datasets/summaries            — Lightweight summaries for all datasets
    POST   /reindex/{dataset_id}          — Admin-only: trigger re-indexing

Rules:
    - GET endpoints have no auth requirement
    - POST reindex requires admin JWT (Hard Rule #8)
    - Return 404 for not found, 400 for invalid params, 503 if pgvector unavailable
    - Log endpoint name, params, and response time via structlog
"""

import time
from datetime import date, datetime
from typing import Optional

import openai
import structlog
from fastapi import APIRouter, Depends, HTTPException, Query, status
from sqlalchemy.orm import Session

from app.api.auth import get_current_admin_user
from app.config import settings
from app.db.session import get_db

logger = structlog.get_logger(__name__)

router = APIRouter(tags=["Search"])


# ── Helpers ────────────────────────────────────────────────────────────────

def _get_openai_client() -> openai.OpenAI:
    """Create an OpenAI client from settings."""
    return openai.OpenAI(api_key=settings.OPENAI_API_KEY)


def _handle_pgvector_error(exc: Exception) -> None:
    """
    Check if an exception is related to pgvector unavailability.
    Raises HTTP 503 if so, otherwise re-raises.
    """
    error_str = str(exc).lower()
    if "vector" in error_str or "could not access" in error_str:
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Vector search is temporarily unavailable. Please try again later.",
        )


# ── GET /datasets — Semantic dataset search ───────────────────────────────

@router.get(
    "/datasets",
    summary="Search datasets by natural language query",
    response_description="Ranked list of matching datasets with relevance scores",
)
async def search_datasets_endpoint(
    q: str = Query(..., min_length=1, description="Search query text"),
    variable: Optional[str] = Query(None, description="Filter by variable name"),
    float_type: Optional[str] = Query(None, description="Filter by float type (core/BGC/deep)"),
    date_from: Optional[date] = Query(None, description="Filter: dataset covers dates from"),
    date_to: Optional[date] = Query(None, description="Filter: dataset covers dates to"),
    region: Optional[str] = Query(None, description="Filter by region name (fuzzy matched)"),
    limit: Optional[int] = Query(None, ge=1, le=settings.SEARCH_MAX_LIMIT, description="Max results"),
    db: Session = Depends(get_db),
):
    """
    Semantic search over dataset embeddings with optional structured filters.

    Returns a ranked list of matching datasets ordered by relevance score (0–1).
    All filter parameters are optional.
    """
    start_time = time.time()
    log = logger.bind(endpoint="search_datasets", query=q[:100])

    try:
        from app.search.search import search_datasets

        client = _get_openai_client()

        filters = {}
        if variable:
            filters["variable"] = variable
        if float_type:
            filters["float_type"] = float_type
        if date_from:
            filters["date_from"] = datetime.combine(date_from, datetime.min.time())
        if date_to:
            filters["date_to"] = datetime.combine(date_to, datetime.max.time())
        if region:
            filters["region_name"] = region

        results = search_datasets(
            query=q,
            db=db,
            openai_client=client,
            filters=filters if filters else None,
            limit=limit,
        )

        elapsed = round(time.time() - start_time, 3)
        log.info("search_datasets_response", result_count=len(results), elapsed_seconds=elapsed)

        return {"results": results, "count": len(results)}

    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        _handle_pgvector_error(exc)
        log.error("search_datasets_error", error=str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Search failed")


# ── GET /floats — Semantic float search ───────────────────────────────────

@router.get(
    "/floats",
    summary="Search floats by natural language query",
    response_description="Ranked list of matching floats with relevance scores",
)
async def search_floats_endpoint(
    q: str = Query(..., min_length=1, description="Search query text"),
    float_type: Optional[str] = Query(None, description="Filter by float type (core/BGC/deep)"),
    region: Optional[str] = Query(None, description="Filter by region name (fuzzy matched)"),
    limit: Optional[int] = Query(None, ge=1, le=settings.SEARCH_MAX_LIMIT, description="Max results"),
    db: Session = Depends(get_db),
):
    """
    Semantic search over float embeddings with optional structured filters.

    Returns a ranked list of matching floats ordered by relevance score (0–1).
    """
    start_time = time.time()
    log = logger.bind(endpoint="search_floats", query=q[:100])

    try:
        from app.search.search import search_floats

        client = _get_openai_client()

        filters = {}
        if float_type:
            filters["float_type"] = float_type
        if region:
            filters["region_name"] = region

        results = search_floats(
            query=q,
            db=db,
            openai_client=client,
            filters=filters if filters else None,
            limit=limit,
        )

        elapsed = round(time.time() - start_time, 3)
        log.info("search_floats_response", result_count=len(results), elapsed_seconds=elapsed)

        return {"results": results, "count": len(results)}

    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=str(exc))
    except Exception as exc:
        _handle_pgvector_error(exc)
        log.error("search_floats_error", error=str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Search failed")


# ── GET /floats/by-region — Float discovery by region ─────────────────────

@router.get(
    "/floats/by-region",
    summary="Discover floats within a named ocean region",
    response_description="List of floats in the specified region",
)
async def discover_floats_by_region_endpoint(
    region: str = Query(..., min_length=1, description="Ocean region name (fuzzy matched)"),
    float_type: Optional[str] = Query(None, description="Filter by float type (core/BGC/deep)"),
    db: Session = Depends(get_db),
):
    """
    Spatial float discovery — not semantic search. Returns all floats whose
    latest position falls within the named ocean region polygon.

    Region names are fuzzy-matched (e.g., "Bengal Bay" → "Bay of Bengal").
    """
    start_time = time.time()
    log = logger.bind(endpoint="discover_floats_by_region", region=region)

    try:
        from app.search.discovery import discover_floats_by_region

        results = discover_floats_by_region(
            region_name=region,
            float_type=float_type,
            db=db,
        )

        elapsed = round(time.time() - start_time, 3)
        log.info("discover_floats_response", result_count=len(results), elapsed_seconds=elapsed)

        return {"results": results, "count": len(results)}

    except ValueError as exc:
        error_msg = str(exc)
        if "not found" in error_msg.lower():
            raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=error_msg)
        raise HTTPException(status_code=status.HTTP_400_BAD_REQUEST, detail=error_msg)
    except Exception as exc:
        _handle_pgvector_error(exc)
        log.error("discover_floats_error", error=str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Discovery failed")


# ── GET /datasets/{dataset_id}/summary — Single dataset summary ───────────

@router.get(
    "/datasets/{dataset_id}/summary",
    summary="Get rich summary for a single dataset",
    response_description="Full dataset summary with metadata and bbox",
)
async def get_dataset_summary_endpoint(
    dataset_id: int,
    db: Session = Depends(get_db),
):
    """
    Returns a rich summary for a single dataset including name, summary text,
    date range, counts, variable list, and bbox as GeoJSON.
    """
    start_time = time.time()
    log = logger.bind(endpoint="get_dataset_summary", dataset_id=dataset_id)

    try:
        from app.search.discovery import get_dataset_summary

        result = get_dataset_summary(dataset_id=dataset_id, db=db)

        elapsed = round(time.time() - start_time, 3)
        log.info("dataset_summary_response", elapsed_seconds=elapsed)

        return result

    except ValueError as exc:
        raise HTTPException(status_code=status.HTTP_404_NOT_FOUND, detail=str(exc))
    except Exception as exc:
        log.error("dataset_summary_error", error=str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve summary")


# ── GET /datasets/summaries — All dataset summaries ───────────────────────

@router.get(
    "/datasets/summaries",
    summary="Get lightweight summaries for all active datasets",
    response_description="List of summary cards for all active datasets",
)
async def get_all_summaries_endpoint(
    db: Session = Depends(get_db),
):
    """
    Returns lightweight summary cards for all active datasets, ordered by
    ingestion date descending. Summary text is truncated to 300 characters.
    """
    start_time = time.time()
    log = logger.bind(endpoint="get_all_summaries")

    try:
        from app.search.discovery import get_all_summaries

        results = get_all_summaries(db=db)

        elapsed = round(time.time() - start_time, 3)
        log.info("all_summaries_response", result_count=len(results), elapsed_seconds=elapsed)

        return {"results": results, "count": len(results)}

    except Exception as exc:
        log.error("all_summaries_error", error=str(exc))
        raise HTTPException(status_code=status.HTTP_500_INTERNAL_SERVER_ERROR, detail="Failed to retrieve summaries")


# ── POST /reindex/{dataset_id} — Admin-only re-indexing ───────────────────

@router.post(
    "/reindex/{dataset_id}",
    summary="Trigger re-indexing for a dataset (admin only)",
    response_description="Acknowledgement that re-indexing has been enqueued",
    status_code=status.HTTP_202_ACCEPTED,
)
async def reindex_dataset_endpoint(
    dataset_id: int,
    db: Session = Depends(get_db),
    admin: dict = Depends(get_current_admin_user),
):
    """
    Enqueues the index_dataset_task for the given dataset. Requires admin JWT.

    Returns immediately with an acknowledgement — does not wait for indexing
    to complete.
    """
    start_time = time.time()
    log = logger.bind(
        endpoint="reindex_dataset",
        dataset_id=dataset_id,
        user_id=admin.get("sub"),
    )

    # Verify dataset exists
    from sqlalchemy import select
    from app.db.models import Dataset

    dataset = db.execute(
        select(Dataset).where(Dataset.dataset_id == dataset_id)
    ).scalar_one_or_none()

    if dataset is None:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail=f"Dataset not found: {dataset_id}",
        )

    # Enqueue the indexing task
    try:
        from app.search.tasks import index_dataset_task
        index_dataset_task.delay(dataset_id=dataset_id)
    except Exception as exc:
        log.error("reindex_enqueue_failed", error=str(exc))
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            detail="Failed to enqueue re-indexing task. Please try again later.",
        )

    elapsed = round(time.time() - start_time, 3)
    log.info("reindex_enqueued", elapsed_seconds=elapsed)

    return {
        "message": "Re-indexing started",
        "dataset_id": dataset_id,
    }
