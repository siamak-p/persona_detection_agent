"""Unit tests for orchestrator/financial_topic_detector.py."""

from __future__ import annotations

import json
import pytest
from unittest.mock import AsyncMock, MagicMock

from orchestrator.financial_topic_detector import (
    FinancialTopicDetector,
    FinancialDetectionResult,
    ThreadContinuationResult,
)


@pytest.fixture
def detector(mock_settings, mock_openai_client):
    return FinancialTopicDetector(
        openai_client=mock_openai_client, settings=mock_settings
    )


# ──────────── generate_acknowledgment ────────────────────────────


class TestGenerateAcknowledgment:
    @pytest.mark.asyncio
    async def test_farsi_with_name(self, detector):
        msg = await detector.generate_acknowledgment("سرمایه‌گذاری", "سیامک")
        assert "سیامک" in msg
        assert "💰" in msg

    @pytest.mark.asyncio
    async def test_farsi_without_name(self, detector):
        msg = await detector.generate_acknowledgment("سرمایه‌گذاری", None)
        assert "ایشان" in msg

    @pytest.mark.asyncio
    async def test_english_with_name(self, detector):
        msg = await detector.generate_acknowledgment("investment", "John", language="en")
        assert "John" in msg
        assert "financial" in msg.lower()

    @pytest.mark.asyncio
    async def test_english_without_name(self, detector):
        msg = await detector.generate_acknowledgment("investment", None, language="en")
        assert "ایشان" in msg or "check" in msg.lower()


# ──────────── generate_pending_response ──────────────────────────


class TestGeneratePendingResponse:
    @pytest.mark.asyncio
    async def test_farsi_with_name(self, detector):
        msg = await detector.generate_pending_response("بیت‌کوین", "سیامک")
        assert "سیامک" in msg
        assert "⏳" in msg

    @pytest.mark.asyncio
    async def test_english_with_name(self, detector):
        msg = await detector.generate_pending_response("bitcoin", "John", language="en")
        assert "John" in msg
        assert "⏳" in msg


# ──────────── generate_delivery_message ──────────────────────────


class TestGenerateDeliveryMessage:
    @pytest.mark.asyncio
    async def test_farsi(self, detector):
        msg = await detector.generate_delivery_message(
            creator_response="آره، سرمایه‌گذاری کن",
            topic_summary="سرمایه‌گذاری",
            creator_name="سیامک",
        )
        assert "سیامک" in msg
        assert "💰" in msg
        assert "سرمایه‌گذاری کن" in msg

    @pytest.mark.asyncio
    async def test_english(self, detector):
        msg = await detector.generate_delivery_message(
            creator_response="Yes, go ahead",
            topic_summary="investment",
            creator_name="John",
            language="en",
        )
        assert "John" in msg
        assert "Yes, go ahead" in msg


# ──────────── detect (LLM mocked) ───────────────────────────────


class TestDetect:
    @pytest.mark.asyncio
    async def test_financial_detected(self, detector, mock_openai_client):
        llm_response = json.dumps(
            {
                "is_financial": True,
                "topic_summary": "Cryptocurrency investment",
                "amount": "$10,000",
                "urgency": "medium",
                "confidence": 0.95,
                "reason": "Direct financial question",
            }
        )
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = llm_response
        mock_resp.usage = MagicMock()
        mock_resp.usage.prompt_tokens = 50
        mock_resp.usage.completion_tokens = 30
        mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        detector._client = mock_openai_client

        result = await detector.detect(
            message="میخوام ۱۰ هزار دلار بیت‌کوین بخرم",
            sender_id="user1",
            creator_id="owner",
        )

        assert isinstance(result, FinancialDetectionResult)
        assert result.is_financial is True
        assert result.confidence >= 0.9

    @pytest.mark.asyncio
    async def test_non_financial(self, detector, mock_openai_client):
        llm_response = json.dumps(
            {
                "is_financial": False,
                "topic_summary": "",
                "amount": None,
                "urgency": "none",
                "confidence": 0.1,
                "reason": "Regular greeting",
            }
        )
        mock_resp = MagicMock()
        mock_resp.choices = [MagicMock()]
        mock_resp.choices[0].message.content = llm_response
        mock_resp.usage = MagicMock()
        mock_resp.usage.prompt_tokens = 50
        mock_resp.usage.completion_tokens = 20
        mock_openai_client.chat.completions.create = AsyncMock(return_value=mock_resp)
        detector._client = mock_openai_client

        result = await detector.detect(
            message="سلام، حالت چطوره؟",
            sender_id="user1",
            creator_id="owner",
        )

        assert result.is_financial is False

    @pytest.mark.asyncio
    async def test_llm_failure_returns_safe_default(self, detector, mock_openai_client):
        mock_openai_client.chat.completions.create = AsyncMock(
            side_effect=RuntimeError("API down")
        )
        detector._client = mock_openai_client

        result = await detector.detect(
            message="بیت‌کوین بخرم؟",
            sender_id="u1",
            creator_id="owner",
        )

        # Should not crash; safe default
        assert isinstance(result, FinancialDetectionResult)
        assert result.is_financial is False
