"""Tests for Feature 9 clarification detection endpoint."""

import asyncio
from unittest.mock import AsyncMock, patch

from fastapi.testclient import TestClient


class TestClarificationDetectEndpoint:
    def test_requires_auth(self, client: TestClient):
        response = client.post(
            "/api/v1/clarification/detect",
            json={"query": "show me ocean data"},
        )
        assert response.status_code == 401

    def test_returns_structured_detection_on_success(self, client: TestClient, auth_headers: dict[str, str]):
        mock_payload = (
            '{"is_underspecified": true, '
            '"missing_dimensions": ["variable", "region"], '
            '"clarification_questions": ['
            '{"dimension": "variable", "question_text": "Which variable?", "options": ["temperature", "salinity"]}, '
            '{"dimension": "region", "question_text": "Which region?", "options": ["Indian Ocean", "Arabian Sea"]}'
            ']}'
        )

        with patch(
            "app.api.v1.clarification._call_detection_llm",
            new=AsyncMock(return_value=mock_payload),
        ):
            response = client.post(
                "/api/v1/clarification/detect",
                json={"query": "show me ocean data"},
                headers=auth_headers,
            )

        assert response.status_code == 200
        body = response.json()
        assert body["is_underspecified"] is True
        assert body["missing_dimensions"] == ["variable", "region"]
        assert len(body["clarification_questions"]) == 2

    def test_fail_open_on_invalid_json(self, client: TestClient, auth_headers: dict[str, str]):
        with patch(
            "app.api.v1.clarification._call_detection_llm",
            new=AsyncMock(return_value="not json"),
        ):
            response = client.post(
                "/api/v1/clarification/detect",
                json={"query": "show me ocean data"},
                headers=auth_headers,
            )

        assert response.status_code == 200
        assert response.json() == {
            "is_underspecified": False,
            "missing_dimensions": [],
            "clarification_questions": [],
        }

    def test_fail_open_on_llm_exception(self, client: TestClient, auth_headers: dict[str, str]):
        with patch(
            "app.api.v1.clarification._call_detection_llm",
            new=AsyncMock(side_effect=RuntimeError("provider failure")),
        ):
            response = client.post(
                "/api/v1/clarification/detect",
                json={"query": "show me ocean data"},
                headers=auth_headers,
            )

        assert response.status_code == 200
        assert response.json() == {
            "is_underspecified": False,
            "missing_dimensions": [],
            "clarification_questions": [],
        }

    def test_fail_open_on_timeout(self, client: TestClient, auth_headers: dict[str, str]):
        with patch(
            "app.api.v1.clarification._call_detection_llm",
            new=AsyncMock(side_effect=asyncio.TimeoutError()),
        ):
            response = client.post(
                "/api/v1/clarification/detect",
                json={"query": "show me ocean data"},
                headers=auth_headers,
            )

        assert response.status_code == 200
        assert response.json() == {
            "is_underspecified": False,
            "missing_dimensions": [],
            "clarification_questions": [],
        }
