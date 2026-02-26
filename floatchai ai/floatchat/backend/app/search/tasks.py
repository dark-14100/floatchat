"""
FloatChat Search Indexing Celery Task

Background task that indexes a dataset and its floats into the vector
embedding tables after ingestion completes.

Tasks:
    index_dataset_task — Re-index a single dataset and all associated floats

IMPORTANT: This is app/search/tasks.py — NOT a root-level tasks.py.
Do not confuse with app/ingestion/tasks.py.

Rules:
    - Retry only on transient OpenAI errors (APIConnectionError, RateLimitError)
    - Do NOT retry on permanent errors (AuthenticationError, NotFoundError)
    - Never crash on indexing failure (Hard Rule #3)
    - Refresh both materialized views after successful reindex (Gap 7)
"""

import time

import openai
import structlog

from app.celery_app import celery
from app.config import settings
from app.db.session import SessionLocal

logger = structlog.get_logger(__name__)


@celery.task(
    name="app.search.tasks.index_dataset_task",
    bind=True,
    max_retries=3,
    default_retry_delay=10,
    autoretry_for=(openai.APIConnectionError, openai.RateLimitError),
    retry_backoff=True,
    retry_jitter=True,
)
def index_dataset_task(self, dataset_id: int) -> dict:
    """
    Celery task that re-indexes a dataset and all its floats.

    Called after successful ingestion (fire-and-forget from ingest_file_task)
    or manually via the POST /reindex endpoint.

    Steps:
        1. Create DB session and OpenAI client
        2. Call reindex_dataset(dataset_id, db, openai_client)
        3. Refresh materialized views (Gap 7 resolution)
        4. Log completion

    Retry policy:
        - Retries on transient OpenAI errors (APIConnectionError, RateLimitError)
        - Does NOT retry on permanent errors (AuthenticationError, NotFoundError)
        - max_retries=3, default_retry_delay=10s with backoff

    Args:
        dataset_id: Primary key of the dataset to index.

    Returns:
        Dict with indexing results.
    """
    start_time = time.time()
    logger.info(
        "index_dataset_task_started",
        dataset_id=dataset_id,
        retry_count=self.request.retries,
    )

    db = SessionLocal()
    try:
        # Create OpenAI client
        openai_client = openai.OpenAI(api_key=settings.OPENAI_API_KEY)

        # Import here to avoid circular imports
        from app.search.indexer import reindex_dataset

        # Run the reindex operation
        result = reindex_dataset(dataset_id, db, openai_client)

        # Refresh materialized views after successful reindex (Gap 7)
        _refresh_materialized_views(db)

        elapsed = round(time.time() - start_time, 3)
        logger.info(
            "index_dataset_task_complete",
            dataset_id=dataset_id,
            dataset_indexed=result["dataset_indexed"],
            floats_total=result["floats"]["total"],
            floats_succeeded=result["floats"]["succeeded"],
            floats_failed=result["floats"]["failed"],
            elapsed_seconds=elapsed,
        )

        return result

    except (openai.AuthenticationError, openai.NotFoundError) as exc:
        # Permanent errors — do NOT retry
        logger.error(
            "index_dataset_task_permanent_error",
            dataset_id=dataset_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return {
            "dataset_indexed": False,
            "floats": {"total": 0, "succeeded": 0, "failed": 0},
            "error": str(exc),
        }

    except (openai.APIConnectionError, openai.RateLimitError):
        # Transient errors — let autoretry_for handle the retry
        raise

    except Exception as exc:
        # Unexpected errors — log but do not crash (Hard Rule #3)
        logger.error(
            "index_dataset_task_unexpected_error",
            dataset_id=dataset_id,
            error_type=type(exc).__name__,
            error=str(exc),
        )
        return {
            "dataset_indexed": False,
            "floats": {"total": 0, "succeeded": 0, "failed": 0},
            "error": str(exc),
        }

    finally:
        db.close()


def _refresh_materialized_views(db) -> None:
    """
    Refresh both materialized views after indexing (Gap 7 resolution).

    Uses CONCURRENTLY where possible, falling back to normal refresh
    on empty views.
    """
    from sqlalchemy import text

    views = ["mv_float_latest_position", "mv_dataset_stats"]
    for view in views:
        try:
            db.execute(text(f"REFRESH MATERIALIZED VIEW CONCURRENTLY {view}"))
        except Exception:
            # CONCURRENTLY fails on empty views — fall back
            db.rollback()
            try:
                db.execute(text(f"REFRESH MATERIALIZED VIEW {view}"))
            except Exception as exc:
                logger.warning(
                    "materialized_view_refresh_failed",
                    view=view,
                    error=str(exc),
                )
                db.rollback()
                continue

    try:
        db.commit()
    except Exception:
        db.rollback()

    logger.info("materialized_views_refreshed", views=views)
