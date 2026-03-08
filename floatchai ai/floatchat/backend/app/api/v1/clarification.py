"""
FloatChat Clarification Detection API Router

Endpoint:
  POST /clarification/detect — Detect underspecified user queries.

Hard requirements:
- Server-side LLM call only (never expose API keys to browser)
- Fail-open on any error or malformed model output
- Use same provider setup as Feature 4 pipeline
"""

import asyncio
import json
import re
from typing import Any

import structlog
from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from app.auth.dependencies import get_current_user
from app.config import get_settings
from app.db.models import User
from app.query.pipeline import get_llm_client

log = structlog.get_logger(__name__)

router = APIRouter(
    prefix="/clarification",
    tags=["Clarification"],
    dependencies=[Depends(get_current_user)],
)

_ALLOWED_DIMENSIONS = {"variable", "region", "time_period", "depth"}


class ClarificationQuestion(BaseModel):
    dimension: str
    question_text: str
    options: list[str]


class ClarificationDetectRequest(BaseModel):
    query: str = Field(..., min_length=1, max_length=2000)


class ClarificationDetectResponse(BaseModel):
    is_underspecified: bool
    missing_dimensions: list[str]
    clarification_questions: list[ClarificationQuestion]


def _fail_open_response() -> ClarificationDetectResponse:
    return ClarificationDetectResponse(
        is_underspecified=False,
        missing_dimensions=[],
        clarification_questions=[],
    )


def _build_messages(query: str) -> list[dict[str, str]]:
    system_prompt = (
        "You are an oceanographic query analyst for ARGO data. "
        "Determine whether a user query is underspecified for reliable data retrieval. "
        "A query is underspecified if it is missing two or more of: variable, region, time_period, depth. "
        "Return ONLY valid JSON with this schema: "
        '{"is_underspecified": boolean, "missing_dimensions": string[], '
        '"clarification_questions": [{"dimension": string, "question_text": string, "options": string[]}]}.'
        "Allowed missing dimensions are: variable, region, time_period, depth. "
        "If not underspecified, return empty arrays for missing_dimensions and clarification_questions. "
        "Do not include markdown, code fences, or explanatory text."
    )

    user_prompt = (
        f"User query: {query}\n\n"
        "Return JSON only."
    )

    return [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": user_prompt},
    ]


def _extract_json_object(text: str) -> dict[str, Any] | None:
    """Best-effort JSON extraction for providers that return surrounding text."""
    if not text:
        return None

    # Direct parse first.
    try:
        payload = json.loads(text)
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        pass

    # Fallback: extract first JSON object region.
    match = re.search(r"\{.*\}", text, flags=re.DOTALL)
    if not match:
        return None

    try:
        payload = json.loads(match.group(0))
        return payload if isinstance(payload, dict) else None
    except json.JSONDecodeError:
        return None


def _normalize_response(payload: dict[str, Any]) -> ClarificationDetectResponse:
    """Normalize loosely formatted model output into strict response schema."""
    raw_missing = payload.get("missing_dimensions", [])
    missing_dimensions = [
        d for d in raw_missing if isinstance(d, str) and d in _ALLOWED_DIMENSIONS
    ]

    raw_questions = payload.get("clarification_questions", [])
    questions: list[ClarificationQuestion] = []
    if isinstance(raw_questions, list):
        for item in raw_questions:
            if not isinstance(item, dict):
                continue

            dimension = item.get("dimension")
            question_text = item.get("question_text")
            options = item.get("options", [])

            if not isinstance(dimension, str) or dimension not in _ALLOWED_DIMENSIONS:
                continue
            if not isinstance(question_text, str) or not question_text.strip():
                continue
            if not isinstance(options, list):
                continue

            cleaned_options = [str(opt).strip() for opt in options if str(opt).strip()]
            if not cleaned_options:
                continue

            questions.append(
                ClarificationQuestion(
                    dimension=dimension,
                    question_text=question_text.strip(),
                    options=cleaned_options[:5],
                )
            )

    is_underspecified = bool(payload.get("is_underspecified", False))

    # Guardrail: no valid missing dimensions means no clarification flow.
    if not missing_dimensions:
        is_underspecified = False
        questions = []

    return ClarificationDetectResponse(
        is_underspecified=is_underspecified,
        missing_dimensions=missing_dimensions,
        clarification_questions=questions,
    )


async def _call_detection_llm(
    *,
    provider: str,
    model: str,
    query: str,
    timeout_seconds: int,
) -> str:
    settings = get_settings()
    client = get_llm_client(provider, settings)
    messages = _build_messages(query)

    def _sync_call() -> str:
        response = client.chat.completions.create(
            model=model,
            messages=messages,
            temperature=0.0,
            max_tokens=300,
        )
        return response.choices[0].message.content or ""

    return await asyncio.wait_for(asyncio.to_thread(_sync_call), timeout=timeout_seconds)


@router.post("/detect", response_model=ClarificationDetectResponse)
async def detect_clarification(
    request: ClarificationDetectRequest,
    current_user: User = Depends(get_current_user),
):
    """
    Detect whether a query needs clarification before NL->SQL execution.

    Fail-open behavior: any exception, timeout, or malformed output returns
    `is_underspecified = false` so the user query proceeds normally.
    """
    settings = get_settings()
    provider = settings.QUERY_LLM_PROVIDER.lower().strip()
    model = settings.QUERY_LLM_MODEL

    try:
        raw_text = await _call_detection_llm(
            provider=provider,
            model=model,
            query=request.query,
            timeout_seconds=settings.LLM_TIMEOUT_SECONDS,
        )

        payload = _extract_json_object(raw_text)
        if payload is None:
            log.warning(
                "clarification_detect_invalid_json",
                user_id=str(current_user.user_id),
                provider=provider,
                model=model,
            )
            return _fail_open_response()

        result = _normalize_response(payload)

        log.info(
            "clarification_flow",
            user_id=str(current_user.user_id),
            original_query=request.query,
            missing_dimensions=result.missing_dimensions,
            chips_selected={},
            outcome="detected",
            assembled_query=None,
        )

        return result

    except Exception as exc:  # noqa: BLE001
        log.warning(
            "clarification_detect_failed",
            user_id=str(current_user.user_id),
            provider=provider,
            model=model,
            error=str(exc),
        )
        return _fail_open_response()
