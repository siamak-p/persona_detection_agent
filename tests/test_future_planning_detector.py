"""Unit tests for orchestrator/future_planning_detector.py."""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from orchestrator.future_planning_detector import (
    FuturePlanningDetector,
    FuturePlanningResult,
)


@pytest.fixture
def detector(mock_settings, mock_openai_client):
    return FuturePlanningDetector(
        openai_client=mock_openai_client, settings=mock_settings
    )


# ──────────── detect (LLM mocked) ───────────────────────────────


class TestDetect:
    @pytest.mark.asyncio
    async def test_planning_detected(self, detector, mock_openai_client):
        llm_response = json.dumps(
            {
                "is_future_planning": True,
                "detected_plan": "رفتن به کوه",
                "detected_datetime": "فردا",
                "confidence": 0.92,
                "reason": "Direct planning request",
            }
        )
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = llm_response
        mock_resp.usage = MagicMock()
        mock_resp.usage.prompt_tokens = 40
        mock_resp.usage.completion_tokens = 25
        mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        detector._client = mock_openai_client

        result = await detector.detect(
            message="فردا بریم کوه؟",
            sender_id="user1",
            recipient_id="owner",
        )

        assert isinstance(result, FuturePlanningResult)
        assert result.is_future_planning is True
        assert result.detected_plan == "رفتن به کوه"
        assert result.confidence >= 0.9

    @pytest.mark.asyncio
    async def test_non_planning(self, detector, mock_openai_client):
        llm_response = json.dumps(
            {
                "is_future_planning": False,
                "detected_plan": "",
                "detected_datetime": None,
                "confidence": 0.05,
                "reason": "Just a greeting",
            }
        )
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = llm_response
        mock_resp.usage = MagicMock()
        mock_resp.usage.prompt_tokens = 30
        mock_resp.usage.completion_tokens = 15
        mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        detector._client = mock_openai_client

        result = await detector.detect(
            message="سلام، چطوری؟",
            sender_id="user1",
            recipient_id="owner",
        )

        assert result.is_future_planning is False

    @pytest.mark.asyncio
    async def test_llm_error_returns_safe_default(self, detector, mock_openai_client):
        mock_openai_client.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("API error")
        )
        detector._client = mock_openai_client

        result = await detector.detect(
            message="فردا بریم سینما",
            sender_id="u1",
            recipient_id="owner",
        )

        assert isinstance(result, FuturePlanningResult)
        assert result.is_future_planning is False
        assert result.confidence == 0.0

    @pytest.mark.asyncio
    async def test_detect_with_context(self, detector, mock_openai_client):
        llm_response = json.dumps(
            {
                "is_future_planning": True,
                "detected_plan": "ناهار رفتن",
                "detected_datetime": "هفته بعد",
                "confidence": 0.88,
                "reason": "Planning with context",
            }
        )
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = llm_response
        mock_resp.usage = MagicMock()
        mock_resp.usage.prompt_tokens = 60
        mock_resp.usage.completion_tokens = 25
        mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        detector._client = mock_openai_client

        result = await detector.detect(
            message="هفته بعد وقت داری ناهار بریم؟",
            sender_id="u1",
            recipient_id="owner",
            context=["سلام", "خوبی؟", "ممنون"],
        )

        assert result.is_future_planning is True
        assert result.detected_plan == "ناهار رفتن"


# ──────────── generate_acknowledgment_response ───────────────────


class TestGenerateAcknowledgmentResponse:
    @pytest.mark.asyncio
    async def test_farsi_with_name(self, detector):
        msg = await detector.generate_acknowledgment_response(
            detected_plan="رفتن به کوه",
            detected_datetime="فردا",
            twin_name="سیامک",
        )
        assert "سیامک" in msg
        assert "👍" in msg

    @pytest.mark.asyncio
    async def test_farsi_without_name(self, detector):
        msg = await detector.generate_acknowledgment_response(
            detected_plan="ناهار",
            detected_datetime=None,
            twin_name=None,
        )
        assert "ایشان" in msg

    @pytest.mark.asyncio
    async def test_english_with_name(self, detector):
        msg = await detector.generate_acknowledgment_response(
            detected_plan="hiking",
            detected_datetime="tomorrow",
            twin_name="John",
            language="en",
        )
        assert "John" in msg
        assert "👍" in msg

    @pytest.mark.asyncio
    async def test_english_without_name(self, detector):
        msg = await detector.generate_acknowledgment_response(
            detected_plan="dinner",
            detected_datetime=None,
            twin_name=None,
            language="en",
        )
        assert "ایشان" in msg or "know" in msg.lower()
