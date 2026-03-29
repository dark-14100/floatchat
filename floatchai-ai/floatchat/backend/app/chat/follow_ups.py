"""
FloatChat Chat Interface — Follow-Up Suggestion Generator

After a query executes successfully, this module generates 2–3 natural
follow-up questions a marine researcher might ask. Uses the same LLM
provider as Feature 4 (QUERY_LLM_PROVIDER).

Never raises — all exceptions are caught, logged, and an empty list
is returned. Follow-up suggestions must never block the results event
(Hard Rule 2 of Feature 5).
"""

import json
from typing import Any

import structlog

from app.query.pipeline import get_llm_client, _get_model

log = structlog.get_logger(__name__)


async def generate_follow_up_suggestions(
    nl_query: str,
    sql: str,
    column_names: list[str],
    row_count: int,
    settings: Any,
) -> list[str]:
    """
    Generate 2–3 follow-up question suggestions using the LLM.

    Parameters
    ----------
    nl_query : str
        The original natural language query from the user.
    sql : str
        The SQL that was executed.
    column_names : list[str]
        Column names from the result set.
    row_count : int
        Number of rows returned.
    settings : Settings
        Application settings (for LLM provider, temperature, max tokens).

    Returns
    -------
    list[str]
        2–3 follow-up question strings. Empty list on any failure.
    """
    try:
        client = get_llm_client(settings.QUERY_LLM_PROVIDER, settings)
    except ValueError as exc:
        log.warning("follow_up_llm_client_failed", error=str(exc))
        return []

    model = _get_model(settings.QUERY_LLM_PROVIDER, None, settings)

    system_msg = (
        "You are a helpful assistant for marine researchers using an ocean data platform. "
        "Given a user's query, the SQL that was executed, the result columns, and the row count, "
        "suggest exactly 2-3 natural follow-up questions the researcher might ask next.\n\n"
        "Rules:\n"
        "- Questions should be related but explore different angles (depth, time, region, variable)\n"
        "- Questions should be self-contained (a new user could understand them)\n"
        "- Questions should be concise (under 100 characters each)\n"
        "- Return ONLY a JSON array of strings, no other text\n"
        "- Example: [\"What is the average salinity at this depth?\", \"How has this changed over the last 5 years?\"]"
    )

    columns_str = ", ".join(column_names[:10])
    user_msg = (
        f"User query: {nl_query}\n"
        f"SQL executed: {sql}\n"
        f"Result columns: {columns_str}\n"
        f"Row count: {row_count}\n\n"
        f"Generate 2-3 follow-up questions as a JSON array of strings."
    )

    try:
        response = client.chat.completions.create(
            model=model,
            messages=[
                {"role": "system", "content": system_msg},
                {"role": "user", "content": user_msg},
            ],
            temperature=settings.FOLLOW_UP_LLM_TEMPERATURE,
            max_tokens=settings.FOLLOW_UP_LLM_MAX_TOKENS,
        )
        content = response.choices[0].message.content or ""
    except Exception as exc:
        log.warning("follow_up_llm_call_failed", error=str(exc))
        return []

    # Parse the response — expect a JSON array of strings
    return _parse_suggestions(content)


def _parse_suggestions(content: str) -> list[str]:
    """
    Parse LLM response into a list of follow-up question strings.

    Handles JSON arrays and plain text fallback. Returns 2–3 items
    or an empty list on parse failure.
    """
    content = content.strip()

    # Try to extract JSON array from the response
    # The LLM may wrap it in markdown code blocks
    if "```" in content:
        # Extract content between code block markers
        parts = content.split("```")
        for part in parts:
            part = part.strip()
            if part.startswith("json"):
                part = part[4:].strip()
            if part.startswith("["):
                content = part
                break

    try:
        parsed = json.loads(content)
        if isinstance(parsed, list):
            # Filter to strings only, limit to 3
            suggestions = [
                str(item).strip()
                for item in parsed
                if isinstance(item, str) and item.strip()
            ][:3]
            if suggestions:
                return suggestions
    except (json.JSONDecodeError, TypeError):
        pass

    # Fallback: try to extract lines that look like questions
    lines = content.split("\n")
    suggestions = []
    for line in lines:
        line = line.strip().lstrip("0123456789.-) ")
        if line and line.endswith("?") and len(line) > 10:
            suggestions.append(line)
        if len(suggestions) >= 3:
            break

    if suggestions:
        log.debug("follow_up_parsed_from_text", count=len(suggestions))
        return suggestions

    log.warning("follow_up_parse_failed", content_preview=content[:200])
    return []
