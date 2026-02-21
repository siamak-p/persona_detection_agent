"""Unit tests for service/creator_service.py."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from service.creator_service import CreatorService


class TestCreatorServiceTextInput:

    @pytest.mark.asyncio
    async def test_text_message_flow(self, mock_orchestrator):
        svc = CreatorService(orchestrator=mock_orchestrator)

        result = await svc.handle_creator(
            user_id="creator1",
            message="من سیامک هستم، ۳۰ سالمه",
            message_id="msg1",
            timestamp="2025-01-01T00:00:00",
            correlation_id="corr1",
        )

        mock_orchestrator.handle_creator.assert_called_once()

        assert result["user_id"] == "creator1"
        assert result["agent_message"] == "Test response from orchestrator"
        assert result["correlation_id"] == "corr1"
        assert result["output_type"] == "text"
        assert result["agent_voice_url"] is None
        assert "agent_message_id" in result
        assert "agent_timestamp" in result

    @pytest.mark.asyncio
    async def test_orchestrator_receives_correct_request(self, mock_orchestrator):
        svc = CreatorService(orchestrator=mock_orchestrator)

        await svc.handle_creator(
            user_id="owner",
            message="I like hiking",
            message_id="m1",
            timestamp="2025-06-01T12:00:00",
            correlation_id="x",
            language="en",
        )

        orch_req = mock_orchestrator.handle_creator.call_args[0][0]
        assert orch_req.user_id == "owner"
        assert orch_req.message == "I like hiking"
        assert orch_req.language == "en"


class TestCreatorServiceVoiceInput:

    @pytest.mark.asyncio
    async def test_voice_input_calls_stt(self, mock_orchestrator, mock_voice_processor):
        svc = CreatorService(
            orchestrator=mock_orchestrator,
            voice_processor=mock_voice_processor,
        )

        await svc.handle_creator(
            user_id="creator1",
            message="",
            message_id="m1",
            timestamp="2025-01-01T00:00:00",
            correlation_id="c",
            voice_data="base64audio",
            input_type="voice",
        )

        mock_voice_processor.process_voice_input.assert_called_once_with(
            "base64audio", "fa"
        )
        orch_req = mock_orchestrator.handle_creator.call_args[0][0]
        assert orch_req.message == "transcribed text"

    @pytest.mark.asyncio
    async def test_voice_stt_failure_raises(self, mock_orchestrator, mock_voice_processor):
        mock_voice_processor.process_voice_input = AsyncMock(
            side_effect=RuntimeError("STT error")
        )
        svc = CreatorService(
            orchestrator=mock_orchestrator,
            voice_processor=mock_voice_processor,
        )

        with pytest.raises(RuntimeError, match="STT error"):
            await svc.handle_creator(
                user_id="c1",
                message="",
                message_id="m1",
                timestamp="2025-01-01T00:00:00",
                correlation_id="c",
                voice_data="data",
                input_type="voice",
            )

    @pytest.mark.asyncio
    async def test_voice_tts_response(self, mock_orchestrator, mock_voice_processor):
        mock_voice_processor._tts_enabled = True
        svc = CreatorService(
            orchestrator=mock_orchestrator,
            voice_processor=mock_voice_processor,
        )

        result = await svc.handle_creator(
            user_id="c1",
            message="",
            message_id="m1",
            timestamp="2025-01-01T00:00:00",
            correlation_id="c",
            voice_data="data",
            input_type="voice",
        )

        assert result["output_type"] == "voice"
        assert result["agent_voice_url"] == "/voices/test.mp3"

    @pytest.mark.asyncio
    async def test_tts_failure_falls_back_to_text(
        self, mock_orchestrator, mock_voice_processor
    ):
        mock_voice_processor._tts_enabled = True
        mock_voice_processor.generate_voice_response = AsyncMock(
            side_effect=RuntimeError("TTS error")
        )
        svc = CreatorService(
            orchestrator=mock_orchestrator,
            voice_processor=mock_voice_processor,
        )

        result = await svc.handle_creator(
            user_id="c1",
            message="",
            message_id="m1",
            timestamp="2025-01-01T00:00:00",
            correlation_id="c",
            voice_data="data",
            input_type="voice",
        )

        assert result["output_type"] == "text"
        assert result["agent_voice_url"] is None
