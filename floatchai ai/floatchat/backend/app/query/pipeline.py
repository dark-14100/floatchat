"""
FloatChat NL Query Engine — Pipeline

Core LLM orchestration module.  ALL LLM calls happen here and only here
(Hard Rule 7).

Pipeline flow:
  1. Build prompt (schema + context + geography + user query)
  2. Call LLM
  3. Extract SQL from response
  4. Validate SQL (3-check)
  5. If invalid → retry with validation error in prompt (up to QUERY_MAX_RETRIES)
  6. After max retries fail → return error, never execute (Hard Rule 10)

Context is NOT stored here — that happens in the API layer (Gap 3).
"""

import re
import time
from dataclasses import dataclass, field
from typing import Optional

import structlog
from openai import OpenAI

from app.query.schema_prompt import SCHEMA_PROMPT
from app.query.validator import validate_sql

log = structlog.get_logger(__name__)


# ── Result dataclass ────────────────────────────────────────────────────────
@dataclass
class PipelineResult:
    """Result of the NL-to-SQL pipeline."""
    sql: Optional[str] = None
    error: Optional[str] = None
    retries_used: int = 0
    validation_errors: list[str] = field(default_factory=list)
    provider: str = ""
    model: str = ""


# ── Provider configuration ──────────────────────────────────────────────────
_PROVIDER_CONFIG = {
    "deepseek": {
        "key_attr": "DEEPSEEK_API_KEY",
        "base_url_attr": "DEEPSEEK_BASE_URL",
        "default_model": "deepseek-reasoner",
    },
    "qwen": {
        "key_attr": "QWEN_API_KEY",
        "base_url_attr": "QWEN_BASE_URL",
        "default_model": "qwq-32b",
    },
    "gemma": {
        "key_attr": "GEMMA_API_KEY",
        "base_url_attr": "GEMMA_BASE_URL",
        "default_model": "gemma3",
    },
    "openai": {
        "key_attr": "OPENAI_API_KEY",
        "base_url_attr": None,  # Uses default OpenAI URL
        "default_model": "gpt-4o",
    },
}


def get_llm_client(provider: str, settings) -> OpenAI:
    """
    Factory function — returns an OpenAI-compatible client for the provider.

    Parameters
    ----------
    provider : str
        One of: deepseek, qwen, gemma, openai.
    settings : Settings
        Application settings instance.

    Returns
    -------
    OpenAI
        Configured client.

    Raises
    ------
    ValueError
        If the provider is unknown or the API key is not set.
    """
    provider = provider.lower().strip()
    if provider not in _PROVIDER_CONFIG:
        raise ValueError(
            f"Unknown LLM provider: '{provider}'. "
            f"Supported: {', '.join(_PROVIDER_CONFIG.keys())}"
        )

    config = _PROVIDER_CONFIG[provider]
    api_key = getattr(settings, config["key_attr"], None)

    if not api_key:
        raise ValueError(
            f"API key not configured for provider '{provider}'. "
            f"Set the {config['key_attr']} environment variable."
        )

    kwargs = {"api_key": api_key}
    if config["base_url_attr"] is not None:
        base_url = getattr(settings, config["base_url_attr"], None)
        if base_url:
            kwargs["base_url"] = base_url

    return OpenAI(**kwargs)


def _get_model(provider: str, model_override: Optional[str], settings) -> str:
    """Resolve the model name for a provider."""
    if model_override:
        return model_override
    # Use the configured QUERY_LLM_MODEL if the provider matches the default
    if provider.lower() == settings.QUERY_LLM_PROVIDER.lower():
        return settings.QUERY_LLM_MODEL
    # Otherwise use the provider's default model
    return _PROVIDER_CONFIG.get(provider.lower(), {}).get("default_model", "gpt-4o")


# ── Prompt assembly ─────────────────────────────────────────────────────────

def _build_messages(
    query: str,
    context: list[dict],
    geography: Optional[dict],
    validation_error: Optional[str] = None,
) -> list[dict]:
    """
    Build the message list for the LLM chat completion call.

    Structure:
      - system: SCHEMA_PROMPT
      - (optional) system addendum: geography bounding box
      - context turns (user/assistant pairs from previous conversation)
      - user: the current query
      - (optional) user addendum: previous validation error for retry
    """
    messages = [{"role": "system", "content": SCHEMA_PROMPT}]

    # Inject geography context if resolved
    if geography:
        geo_msg = (
            f"\n[Geography detected: {geography['name']}]\n"
            f"Bounding box: lat {geography['lat_min']}–{geography['lat_max']}, "
            f"lon {geography['lon_min']}–{geography['lon_max']}\n"
            f"Use these coordinates for spatial filtering."
        )
        messages.append({"role": "system", "content": geo_msg})

    # Add conversation context turns
    for turn in context:
        role = turn.get("role", "user")
        content = turn.get("content", "")
        sql = turn.get("sql")
        if role == "assistant" and sql:
            # Include the SQL the assistant generated in previous turns
            content = f"{content}\n\nSQL generated:\n```sql\n{sql}\n```"
        messages.append({"role": role, "content": content})

    # Current user query
    user_msg = query
    if validation_error:
        user_msg = (
            f"{query}\n\n"
            f"[RETRY] Your previous SQL had a validation error:\n"
            f"{validation_error}\n"
            f"Please fix the issue and generate corrected SQL."
        )
    messages.append({"role": "user", "content": user_msg})

    return messages


# ── SQL extraction ──────────────────────────────────────────────────────────

# Pattern to find ```sql ... ``` blocks
_SQL_BLOCK_RE = re.compile(r"```sql\s*\n?(.*?)```", re.DOTALL | re.IGNORECASE)
# Fallback: find a raw SELECT statement
_RAW_SELECT_RE = re.compile(
    r"((?:WITH\s+.+?\s+)?SELECT\s+.+?)(?:\n\n|\Z)",
    re.DOTALL | re.IGNORECASE,
)


def _extract_sql(response_text: str) -> Optional[str]:
    """
    Extract SQL from the LLM response.

    Priority:
      1. ```sql ... ``` code block
      2. Raw SELECT/WITH statement
    """
    # Try code block first
    match = _SQL_BLOCK_RE.search(response_text)
    if match:
        sql = match.group(1).strip()
        if sql:
            return sql

    # Fallback to raw SELECT
    match = _RAW_SELECT_RE.search(response_text)
    if match:
        sql = match.group(1).strip()
        if sql:
            return sql

    return None


# ── Core pipeline ───────────────────────────────────────────────────────────

async def nl_to_sql(
    query: str,
    context: list[dict],
    geography: Optional[dict],
    settings,
    provider: Optional[str] = None,
    model: Optional[str] = None,
) -> PipelineResult:
    """
    Core NL-to-SQL pipeline.

    Builds prompt → calls LLM → extracts SQL → validates → retries.

    Parameters
    ----------
    query : str
        The user's natural language question.
    context : list[dict]
        Previous conversation turns.
    geography : Optional[dict]
        Resolved geography bounding box, or None.
    settings : Settings
        Application settings.
    provider : Optional[str]
        Override provider (for benchmark). Defaults to settings.QUERY_LLM_PROVIDER.
    model : Optional[str]
        Override model (for benchmark). Defaults to settings.QUERY_LLM_MODEL.

    Returns
    -------
    PipelineResult
    """
    active_provider = (provider or settings.QUERY_LLM_PROVIDER).lower().strip()
    active_model = _get_model(active_provider, model, settings)
    max_retries = settings.QUERY_MAX_RETRIES

    result = PipelineResult(provider=active_provider, model=active_model)

    # Get LLM client
    try:
        client = get_llm_client(active_provider, settings)
    except ValueError as exc:
        result.error = str(exc)
        return result

    validation_error: Optional[str] = None

    for attempt in range(max_retries):
        result.retries_used = attempt

        # Build messages
        messages = _build_messages(query, context, geography, validation_error)

        # Call LLM
        try:
            response = client.chat.completions.create(
                model=active_model,
                messages=messages,
                temperature=settings.QUERY_LLM_TEMPERATURE,
                max_tokens=settings.QUERY_LLM_MAX_TOKENS,
            )
            response_text = response.choices[0].message.content or ""
        except Exception as exc:
            log.error(
                "llm_call_failed",
                provider=active_provider,
                model=active_model,
                attempt=attempt + 1,
                error=str(exc),
            )
            result.error = f"LLM call failed: {exc}"
            return result

        # Extract SQL
        sql = _extract_sql(response_text)
        if not sql:
            validation_error = (
                "Could not extract a SQL statement from your response. "
                "Please return the SQL inside a ```sql ... ``` code block."
            )
            result.validation_errors.append(validation_error)
            log.warning(
                "sql_extraction_failed",
                attempt=attempt + 1,
                response_preview=response_text[:200],
            )
            continue

        # Validate SQL
        vr = validate_sql(sql)
        if not vr.valid:
            validation_error = vr.error or "Unknown validation error"
            result.validation_errors.append(validation_error)
            log.warning(
                "sql_validation_failed",
                attempt=attempt + 1,
                check=vr.check_failed,
                error=vr.error,
            )
            continue

        # Validation passed — return the SQL
        result.sql = sql
        result.retries_used = attempt
        if vr.warnings:
            log.info("sql_validation_warnings", warnings=vr.warnings)
        log.info(
            "pipeline_success",
            provider=active_provider,
            model=active_model,
            retries=attempt,
        )
        return result

    # All retries exhausted — Hard Rule 10: never execute
    result.error = (
        f"SQL generation failed after {max_retries} attempts. "
        f"Validation errors: {'; '.join(result.validation_errors[-3:])}"
    )
    result.retries_used = max_retries
    log.error(
        "pipeline_exhausted",
        provider=active_provider,
        model=active_model,
        max_retries=max_retries,
        errors=result.validation_errors,
    )
    return result


# ── Interpretation ──────────────────────────────────────────────────────────

async def interpret_results(
    query: str,
    sql: str,
    columns: list[str],
    rows: list[dict],
    row_count: int,
    settings,
) -> str:
    """
    Generate a natural language interpretation of query results.

    This is a SEPARATE LLM call (Gap 1 resolution), using the same
    provider/model as the main query.

    Parameters
    ----------
    query : str
        The original NL question.
    sql : str
        The SQL that was executed.
    columns : list[str]
        Column names in the result.
    rows : list[dict]
        Result rows (may be truncated).
    row_count : int
        Total rows returned.
    settings : Settings
        Application settings.

    Returns
    -------
    str
        Natural language summary of the results.
    """
    try:
        client = get_llm_client(settings.QUERY_LLM_PROVIDER, settings)
    except ValueError:
        return _fallback_interpretation(row_count, columns)

    # Build a concise data preview (first 10 rows max)
    preview_rows = rows[:10]
    preview_text = _format_preview(columns, preview_rows)

    system_msg = (
        "You are a data analyst assistant. The user asked a question about "
        "oceanographic data, and a SQL query was executed against the database. "
        "Summarize the results in 2-4 sentences. Be specific with numbers. "
        "If the result is empty, say so clearly."
    )

    user_msg = (
        f"Question: {query}\n\n"
        f"SQL executed:\n```sql\n{sql}\n```\n\n"
        f"Results ({row_count} rows):\n{preview_text}"
    )

    try:
        response = client.chat.completions.create(
            model=_get_model(settings.QUERY_LLM_PROVIDER, None, settings),
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=0.3,
            max_tokens=512,
        )
        interpretation = response.choices[0].message.content or ""
        return interpretation.strip()

    except Exception as exc:
        log.warning("interpretation_failed", error=str(exc))
        return _fallback_interpretation(row_count, columns)


def _fallback_interpretation(row_count: int, columns: list[str]) -> str:
    """Template-based fallback when LLM interpretation fails."""
    if row_count == 0:
        return "The query returned no results."
    cols_str = ", ".join(columns[:5])
    suffix = f" and {len(columns) - 5} more" if len(columns) > 5 else ""
    return (
        f"The query returned {row_count} row{'s' if row_count != 1 else ''} "
        f"with columns: {cols_str}{suffix}."
    )


def _format_preview(columns: list[str], rows: list[dict]) -> str:
    """Format a few rows as a simple text table for the interpretation prompt."""
    if not rows:
        return "(empty result set)"

    lines = [" | ".join(columns)]
    lines.append("-" * len(lines[0]))
    for row in rows:
        values = [str(row.get(c, "")) for c in columns]
        lines.append(" | ".join(values))

    return "\n".join(lines)
