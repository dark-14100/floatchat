"""
FloatChat Indexer Module

Builds embedding texts from database records and persists them to the
dataset_embeddings and float_embeddings tables.  Calls embeddings.py for
all OpenAI API interactions — never calls the API directly (Hard Rule #1).

Functions:
    index_dataset              — Embed and upsert a single dataset
    index_floats_for_dataset   — Embed and upsert all floats for a dataset
    reindex_dataset            — Single entry point: dataset + all its floats

Rules:
    - All upserts use INSERT ... ON CONFLICT ... DO UPDATE for idempotency
    - Embedding failures set status='embedding_failed' — never crash
    - Region name resolution happens here, not in embeddings.py (Gap 4)
    - Both operations in reindex_dataset must run even if one fails
"""

import time
from typing import Optional

import structlog
from geoalchemy2.functions import ST_Contains
from sqlalchemy import distinct, func, select, text
from sqlalchemy.dialects.postgresql import insert as pg_insert
from sqlalchemy.orm import Session

from app.config import settings
from app.db.models import (
    Dataset,
    DatasetEmbedding,
    Float,
    FloatEmbedding,
    Measurement,
    OceanRegion,
    Profile,
)
from app.search.embeddings import (
    build_dataset_embedding_text,
    build_float_embedding_text,
    embed_single,
    embed_texts,
)

logger = structlog.get_logger(__name__)

# Allowed variable columns on the Measurement model for per-float variable detection
_VARIABLE_COLUMNS = [
    "temperature",
    "salinity",
    "dissolved_oxygen",
    "chlorophyll",
    "nitrate",
    "ph",
]


# ── Helpers ────────────────────────────────────────────────────────────────


def _resolve_region_for_point(
    lat: Optional[float],
    lon: Optional[float],
    db: Session,
) -> Optional[str]:
    """
    Resolve a (lat, lon) point to an ocean region name via spatial query.

    Returns the region_name of the ocean_region polygon containing the point,
    or None if the point does not fall within any known region.
    """
    if lat is None or lon is None:
        return None

    point_wkt = f"SRID=4326;POINT({lon} {lat})"
    stmt = (
        select(OceanRegion.region_name)
        .where(
            ST_Contains(
                OceanRegion.geom,
                func.ST_GeogFromText(point_wkt),
            )
        )
        .limit(1)
    )
    result = db.execute(stmt).scalar_one_or_none()
    return result


def _get_float_variables(float_id: int, db: Session) -> list[str]:
    """
    Determine which oceanographic variables have non-null measurements
    for the given float.

    Joins floats → profiles → measurements and checks each variable column.
    Returns a list of variable names (e.g., ['temperature', 'salinity']).
    """
    # Get all profile IDs for this float
    profile_ids_stmt = (
        select(Profile.profile_id).where(Profile.float_id == float_id)
    )

    variables = []
    for var_name in _VARIABLE_COLUMNS:
        col = getattr(Measurement, var_name)
        exists_stmt = (
            select(func.count())
            .select_from(Measurement)
            .where(Measurement.profile_id.in_(profile_ids_stmt))
            .where(col.isnot(None))
            .limit(1)
        )
        count = db.execute(exists_stmt).scalar()
        if count and count > 0:
            variables.append(var_name)

    return variables


def _get_floats_for_dataset(dataset_id: int, db: Session) -> list[Float]:
    """
    Fetch all distinct floats that have at least one profile in the given dataset.
    """
    float_ids_stmt = (
        select(distinct(Profile.float_id))
        .where(Profile.dataset_id == dataset_id)
    )
    stmt = select(Float).where(Float.float_id.in_(float_ids_stmt))
    return list(db.execute(stmt).scalars().all())


# ── Public API ─────────────────────────────────────────────────────────────


def index_dataset(
    dataset_id: int,
    db: Session,
    openai_client,
) -> bool:
    """
    Embed and upsert a single dataset into dataset_embeddings.

    Fetches the dataset from the database, builds the embedding text using
    build_dataset_embedding_text, calls embed_single, and upserts into
    dataset_embeddings using INSERT ... ON CONFLICT (dataset_id) DO UPDATE.

    If the embedding call fails, sets status='embedding_failed' and logs the
    error — does not re-raise (Hard Rule #3).

    Args:
        dataset_id: Primary key of the dataset to index.
        db: SQLAlchemy session.
        openai_client: An openai.OpenAI client instance.

    Returns:
        True if embedding succeeded, False if it failed.
    """
    start_time = time.time()

    # Fetch the dataset
    dataset = db.execute(
        select(Dataset).where(Dataset.dataset_id == dataset_id)
    ).scalar_one_or_none()

    if dataset is None:
        logger.warning("index_dataset_not_found", dataset_id=dataset_id)
        return False

    # Build the embedding text
    embedding_text = build_dataset_embedding_text(dataset)

    if not embedding_text.strip():
        logger.warning(
            "index_dataset_empty_text",
            dataset_id=dataset_id,
        )
        return False

    # Attempt to generate the embedding
    try:
        vector = embed_single(embedding_text, openai_client)
    except Exception as exc:
        # Embedding failed — upsert with status='embedding_failed'
        logger.error(
            "index_dataset_embedding_failed",
            dataset_id=dataset_id,
            error=str(exc),
        )
        _upsert_dataset_embedding(
            dataset_id=dataset_id,
            embedding_text=embedding_text,
            embedding=None,
            status="embedding_failed",
            db=db,
        )
        return False

    # Upsert with status='indexed'
    _upsert_dataset_embedding(
        dataset_id=dataset_id,
        embedding_text=embedding_text,
        embedding=vector,
        status="indexed",
        db=db,
    )

    elapsed = round(time.time() - start_time, 3)
    logger.info(
        "index_dataset_complete",
        dataset_id=dataset_id,
        text_length=len(embedding_text),
        elapsed_seconds=elapsed,
    )
    return True


def index_floats_for_dataset(
    dataset_id: int,
    db: Session,
    openai_client,
) -> dict:
    """
    Embed and upsert all floats associated with a dataset.

    Fetches all floats that have profiles in this dataset, pre-resolves
    region names from ocean_regions via spatial query (Gap 4 resolution),
    builds embedding texts, calls embed_texts with batching, and upserts
    all results into float_embeddings.

    Handles partial failures: if one batch of embedding calls fails, those
    floats are marked as 'embedding_failed' and remaining batches continue.

    Args:
        dataset_id: Primary key of the dataset whose floats to index.
        db: SQLAlchemy session.
        openai_client: An openai.OpenAI client instance.

    Returns:
        Dict with keys: total, succeeded, failed.
    """
    start_time = time.time()
    result = {"total": 0, "succeeded": 0, "failed": 0}

    # Fetch all floats linked to this dataset
    floats = _get_floats_for_dataset(dataset_id, db)
    result["total"] = len(floats)

    if not floats:
        logger.info(
            "index_floats_none_found",
            dataset_id=dataset_id,
        )
        return result

    # Pre-resolve region names and variables for all floats
    float_metadata: list[dict] = []
    for f in floats:
        region_name = _resolve_region_for_point(
            f.deployment_lat, f.deployment_lon, db
        )
        variables = _get_float_variables(f.float_id, db)
        embedding_text = build_float_embedding_text(f, variables, region_name)
        float_metadata.append({
            "float_obj": f,
            "embedding_text": embedding_text,
        })

    # Process in batches matching the embedding batch size
    batch_size = settings.EMBEDDING_BATCH_SIZE

    for batch_start in range(0, len(float_metadata), batch_size):
        batch = float_metadata[batch_start : batch_start + batch_size]
        batch_texts = [item["embedding_text"] for item in batch]

        try:
            vectors = embed_texts(batch_texts, openai_client)
        except Exception as exc:
            # Entire batch failed — mark all floats in this batch as failed
            logger.error(
                "index_floats_batch_failed",
                dataset_id=dataset_id,
                batch_start=batch_start,
                batch_size=len(batch),
                error=str(exc),
            )
            for item in batch:
                _upsert_float_embedding(
                    float_id=item["float_obj"].float_id,
                    embedding_text=item["embedding_text"],
                    embedding=None,
                    status="embedding_failed",
                    db=db,
                )
            result["failed"] += len(batch)
            continue

        # Upsert each float's embedding
        for item, vector in zip(batch, vectors):
            _upsert_float_embedding(
                float_id=item["float_obj"].float_id,
                embedding_text=item["embedding_text"],
                embedding=vector,
                status="indexed",
                db=db,
            )
            result["succeeded"] += 1

    elapsed = round(time.time() - start_time, 3)
    logger.info(
        "index_floats_complete",
        dataset_id=dataset_id,
        total=result["total"],
        succeeded=result["succeeded"],
        failed=result["failed"],
        elapsed_seconds=elapsed,
    )
    return result


def reindex_dataset(
    dataset_id: int,
    db: Session,
    openai_client,
) -> dict:
    """
    Single entry point for re-indexing a dataset and all its floats.

    Calls index_dataset then index_floats_for_dataset. Both operations
    must complete even if the first one fails — they are independent.

    Args:
        dataset_id: Primary key of the dataset to re-index.
        db: SQLAlchemy session.
        openai_client: An openai.OpenAI client instance.

    Returns:
        Dict with keys: dataset_indexed (bool), floats (dict with
        total/succeeded/failed).
    """
    start_time = time.time()

    # 1. Index the dataset itself
    dataset_ok = False
    try:
        dataset_ok = index_dataset(dataset_id, db, openai_client)
    except Exception as exc:
        logger.error(
            "reindex_dataset_failed",
            dataset_id=dataset_id,
            error=str(exc),
        )

    # 2. Index all floats — runs even if dataset indexing failed
    floats_result = {"total": 0, "succeeded": 0, "failed": 0}
    try:
        floats_result = index_floats_for_dataset(dataset_id, db, openai_client)
    except Exception as exc:
        logger.error(
            "reindex_floats_failed",
            dataset_id=dataset_id,
            error=str(exc),
        )

    elapsed = round(time.time() - start_time, 3)
    logger.info(
        "reindex_complete",
        dataset_id=dataset_id,
        dataset_indexed=dataset_ok,
        floats_total=floats_result["total"],
        floats_succeeded=floats_result["succeeded"],
        floats_failed=floats_result["failed"],
        elapsed_seconds=elapsed,
    )

    return {
        "dataset_indexed": dataset_ok,
        "floats": floats_result,
    }


# ── Upsert Helpers ─────────────────────────────────────────────────────────


def _upsert_dataset_embedding(
    dataset_id: int,
    embedding_text: str,
    embedding: Optional[list[float]],
    status: str,
    db: Session,
) -> None:
    """
    Upsert a row into dataset_embeddings using INSERT ... ON CONFLICT DO UPDATE.

    If embedding is None (failure case), we still upsert the text and status
    so the failure is recorded and the row can be retried later.
    """
    if embedding is None:
        # For failure case, we need to handle the NOT NULL constraint on embedding.
        # Check if a row already exists — if so, update status only.
        # If not, we cannot insert without a valid embedding vector.
        existing = db.execute(
            select(DatasetEmbedding).where(
                DatasetEmbedding.dataset_id == dataset_id
            )
        ).scalar_one_or_none()

        if existing:
            existing.status = status
            existing.embedding_text = embedding_text
            existing.updated_at = func.now()
            db.commit()
        else:
            # No existing row and no valid embedding — create with a zero vector
            # so the row exists and can be identified as failed
            zero_vector = [0.0] * settings.EMBEDDING_DIMENSIONS
            stmt = pg_insert(DatasetEmbedding).values(
                dataset_id=dataset_id,
                embedding_text=embedding_text,
                embedding=zero_vector,
                status=status,
            ).on_conflict_do_update(
                index_elements=["dataset_id"],
                set_={
                    "embedding_text": embedding_text,
                    "embedding": zero_vector,
                    "status": status,
                    "updated_at": func.now(),
                },
            )
            db.execute(stmt)
            db.commit()
        return

    stmt = pg_insert(DatasetEmbedding).values(
        dataset_id=dataset_id,
        embedding_text=embedding_text,
        embedding=embedding,
        status=status,
    ).on_conflict_do_update(
        index_elements=["dataset_id"],
        set_={
            "embedding_text": embedding_text,
            "embedding": embedding,
            "status": status,
            "updated_at": func.now(),
        },
    )
    db.execute(stmt)
    db.commit()


def _upsert_float_embedding(
    float_id: int,
    embedding_text: str,
    embedding: Optional[list[float]],
    status: str,
    db: Session,
) -> None:
    """
    Upsert a row into float_embeddings using INSERT ... ON CONFLICT DO UPDATE.

    Same failure handling as _upsert_dataset_embedding.
    """
    if embedding is None:
        existing = db.execute(
            select(FloatEmbedding).where(
                FloatEmbedding.float_id == float_id
            )
        ).scalar_one_or_none()

        if existing:
            existing.status = status
            existing.embedding_text = embedding_text
            existing.updated_at = func.now()
            db.commit()
        else:
            zero_vector = [0.0] * settings.EMBEDDING_DIMENSIONS
            stmt = pg_insert(FloatEmbedding).values(
                float_id=float_id,
                embedding_text=embedding_text,
                embedding=zero_vector,
                status=status,
            ).on_conflict_do_update(
                index_elements=["float_id"],
                set_={
                    "embedding_text": embedding_text,
                    "embedding": zero_vector,
                    "status": status,
                    "updated_at": func.now(),
                },
            )
            db.execute(stmt)
            db.commit()
        return

    stmt = pg_insert(FloatEmbedding).values(
        float_id=float_id,
        embedding_text=embedding_text,
        embedding=embedding,
        status=status,
    ).on_conflict_do_update(
        index_elements=["float_id"],
        set_={
            "embedding_text": embedding_text,
            "embedding": embedding,
            "status": status,
            "updated_at": func.now(),
        },
    )
    db.execute(stmt)
    db.commit()
