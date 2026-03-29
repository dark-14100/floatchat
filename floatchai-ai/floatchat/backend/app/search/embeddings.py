"""
FloatChat Embedding Generation

Centralized module for all OpenAI embedding API calls and embedding text
construction. This is the ONLY module in the codebase that calls the
OpenAI embedding API (Hard Rule #1).

Functions:
    build_dataset_embedding_text  — Build embeddable text from a Dataset record
    build_float_embedding_text    — Build embeddable text from a Float record
    embed_texts                   — Batch-embed a list of texts via OpenAI API
    embed_single                  — Convenience wrapper to embed one text

Rules:
    - Never call the OpenAI embedding API outside this module
    - Never embed texts one at a time in a loop — always batch (Hard Rule #2)
    - Never log embedding vectors — only metadata (Hard Rule #9)
    - No DB access in this module — callers resolve DB data before calling
    - Raise errors immediately — retry logic lives in the Celery task
"""

import time
from typing import Optional

import structlog

from app.config import settings

logger = structlog.get_logger(__name__)


def build_dataset_embedding_text(dataset) -> str:
    """
    Build the text string to embed for a dataset.

    Combines the LLM-generated summary_text with a structured descriptor
    containing dataset name, variable list, date range, float count,
    and region description (derived from bbox).

    The combined text is what gets embedded — not each piece separately (FR-04).

    Args:
        dataset: A Dataset ORM object.

    Returns:
        A single string ready for embedding.
    """
    # Build structured descriptor parts
    parts = []

    if dataset.name:
        parts.append(f"Dataset: {dataset.name}")

    # Format variable list
    if dataset.variable_list:
        if isinstance(dataset.variable_list, list):
            vars_str = ", ".join(dataset.variable_list)
        elif isinstance(dataset.variable_list, dict):
            vars_str = ", ".join(dataset.variable_list.keys())
        else:
            vars_str = str(dataset.variable_list)
        parts.append(f"Variables: {vars_str}")

    # Format date range
    if dataset.date_range_start and dataset.date_range_end:
        start = dataset.date_range_start.strftime("%Y-%m-%d")
        end = dataset.date_range_end.strftime("%Y-%m-%d")
        parts.append(f"Date range: {start} to {end}")
    elif dataset.date_range_start:
        start = dataset.date_range_start.strftime("%Y-%m-%d")
        parts.append(f"Date range: from {start}")

    # Float count
    if dataset.float_count is not None:
        parts.append(f"Float count: {dataset.float_count}")

    # Profile count
    if dataset.profile_count is not None:
        parts.append(f"Profile count: {dataset.profile_count}")

    descriptor = ". ".join(parts)

    # Combine summary_text + descriptor with newline separator (FR-04)
    summary = dataset.summary_text or ""
    combined = f"{summary}\n{descriptor}".strip()

    return combined


def build_float_embedding_text(
    float_obj,
    variables_list: list[str],
    region_name: Optional[str] = None,
) -> str:
    """
    Build the text string to embed for a float.

    Includes float type, platform number, deployment region (pre-resolved
    by the caller from ocean_regions — this module does not access the DB),
    available variables, and active date range (FR-05).

    Args:
        float_obj: A Float ORM object.
        variables_list: List of variable names available for this float.
        region_name: Pre-resolved region name from ocean_regions table.
                     Resolved by the caller (indexer.py), not this module.

    Returns:
        A single string ready for embedding.
    """
    parts = []

    # Float type
    if float_obj.float_type:
        parts.append(f"Float type: {float_obj.float_type}")

    # Platform number (WMO ID)
    if float_obj.platform_number:
        parts.append(f"Platform number: {float_obj.platform_number}")

    # Deployment region (pre-resolved by caller)
    if region_name:
        parts.append(f"Deployment region: {region_name}")
    elif float_obj.deployment_lat is not None and float_obj.deployment_lon is not None:
        parts.append(
            f"Deployment position: {float_obj.deployment_lat:.2f}°N, "
            f"{float_obj.deployment_lon:.2f}°E"
        )

    # Available variables
    if variables_list:
        parts.append(f"Variables: {', '.join(variables_list)}")

    # Active date range (deployment date)
    if float_obj.deployment_date:
        parts.append(f"Deployed: {float_obj.deployment_date.strftime('%Y-%m-%d')}")

    # Country / Program
    if float_obj.country:
        parts.append(f"Country: {float_obj.country}")
    if float_obj.program:
        parts.append(f"Program: {float_obj.program}")

    descriptor = ". ".join(parts)
    return descriptor


def embed_texts(texts: list[str], client) -> list[list[float]]:
    """
    Embed a list of texts using the OpenAI embedding API with batching.

    Splits texts into batches of settings.EMBEDDING_BATCH_SIZE and makes
    one API call per batch. Returns a flat list of embedding vectors in
    the same order as the input texts.

    This function MUST be used for all embedding — never call the API
    once per text in a loop (Hard Rule #2).

    Args:
        texts: List of strings to embed.
        client: An openai.OpenAI client instance.

    Returns:
        List of embedding vectors (each a list of floats), same length
        and order as input texts.

    Raises:
        openai.APIError and subclasses on API failure — caller handles retries.
    """
    if not texts:
        return []

    batch_size = settings.EMBEDDING_BATCH_SIZE
    all_embeddings: list[list[float]] = []
    total_tokens = 0
    start_time = time.time()

    for i in range(0, len(texts), batch_size):
        batch = texts[i : i + batch_size]

        response = client.embeddings.create(
            input=batch,
            model=settings.EMBEDDING_MODEL,
        )

        # Extract embeddings in order (API returns them sorted by index)
        batch_embeddings = [item.embedding for item in response.data]
        all_embeddings.extend(batch_embeddings)

        # Track token usage
        if response.usage:
            total_tokens += response.usage.total_tokens

    elapsed = time.time() - start_time

    # Log metadata only — never log embedding vectors (Hard Rule #9)
    logger.info(
        "embeddings_generated",
        text_count=len(texts),
        batch_count=(len(texts) + batch_size - 1) // batch_size,
        total_tokens=total_tokens,
        elapsed_seconds=round(elapsed, 3),
    )

    return all_embeddings


def embed_single(text: str, client) -> list[float]:
    """
    Embed a single text string. Convenience wrapper around embed_texts.

    Used at query time for embedding search queries.

    Args:
        text: The string to embed.
        client: An openai.OpenAI client instance.

    Returns:
        A single embedding vector (list of floats).
    """
    results = embed_texts([text], client)
    return results[0]
