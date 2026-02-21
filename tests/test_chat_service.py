"""Unit tests for service/chat_service.py."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock

from service.chat_service import ChatService


# ──────────────────────── Text Input ─────────────────────────────


class TestChatServiceTextInput:

    @pytest.mark.asyncio
    async def test_text_message_flow(self, mock_orchestrator):
        svc = ChatService(orchestrator=mock_orchestrator)

        result = await svc.handle_chat(
            user_id="user1",
            to_user_id="user2",
            message="سلام",
            message_id="msg1",
            conversation_id="conv1",
            timestamp="2025-01-01T00:00:00",
            correlation_id="corr1",
        )

        # Orchestrator called
        mock_orchestrator.handle_chat.assert_called_once()

        # Response structure
        assert result["user_id"] == "user2"
        assert result["agent_message"] == "Test response from orchestrator"
        assert result["conversation_id"] == "conv1"
        assert result["correlation_id"] == "corr1"
        assert result["output_type"] == "text"
        assert result["agent_voice_url"] is None
        assert "agent_message_id" in result
        assert "agent_timestamp" in result

    @pytest.mark.asyncio
    async def test_orchestrator_receives_correct_request(self, mock_orchestrator):
        svc = ChatService(orchestrator=mock_orchestrator)

        await svc.handle_chat(
            user_id="alice",
            to_user_id="bob",
            message="How are you?",
            message_id="m1",
            conversation_id="c1",
            timestamp="2025-06-01T12:00:00",
            correlation_id="x",
            language="en",
        )

        call_args = mock_orchestrator.handle_chat.call_args
        orch_req = call_args[0][0]
        assert orch_req.user_id == "alice"
        assert orch_req.to_user_id == "bob"
        assert orch_req.message == "How are you?"
        assert orch_req.language == "en"


# ──────────────────────── Voice Input ────────────────────────────


class TestChatServiceVoiceInput:

    @pytest.mark.asyncio
    async def test_voice_input_calls_stt(self, mock_orchestrator, mock_voice_processor):
        svc = ChatService(
            orchestrator=mock_orchestrator,
            voice_processor=mock_voice_processor,
        )

        result = await svc.handle_chat(
            user_id="u1",
            to_user_id="u2",
            message="",
            message_id="m1",
            conversation_id="c1",
            timestamp="2025-01-01T00:00:00",
            correlation_id="corr1",
            voice_data="base64audiodata",
            input_type="voice",
        )

        # STT called
        mock_voice_processor.process_voice_input.assert_called_once_with(
            "base64audiodata", "fa"
        )

        # Orchestrator receives transcribed text
        orch_req = mock_orchestrator.handle_chat.call_args[0][0]
        assert orch_req.message == "transcribed text"

    @pytest.mark.asyncio
    async def test_voice_input_stt_failure(self, mock_orchestrator, mock_voice_processor):
        mock_voice_processor.process_voice_input = AsyncMock(
            side_effect=RuntimeError("STT failed")
        )
        svc = ChatService(
            orchestrator=mock_orchestrator,
            voice_processor=mock_voice_processor,
        )

        with pytest.raises(RuntimeError, match="STT failed"):
            await svc.handle_chat(
                user_id="u1",
                to_user_id="u2",
                message="",
                message_id="m1",
                conversation_id="c1",
                timestamp="2025-01-01T00:00:00",
                correlation_id="c",
                voice_data="data",
                input_type="voice",
            )

    @pytest.mark.asyncio
    async def test_voice_output_with_tts_enabled(
        self, mock_orchestrator, mock_voice_processor
    ):
        mock_voice_processor._tts_enabled = True
        svc = ChatService(
            orchestrator=mock_orchestrator,
            voice_processor=mock_voice_processor,
        )

        result = await svc.handle_chat(
            user_id="u1",
            to_user_id="u2",
            message="",
            message_id="m1",
            conversation_id="c1",
            timestamp="2025-01-01T00:00:00",
            correlation_id="c",
            voice_data="data",
            input_type="voice",
        )

        mock_voice_processor.generate_voice_response.assert_called_once()
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
        svc = ChatService(
            orchestrator=mock_orchestrator,
            voice_processor=mock_voice_processor,
        )

        result = await svc.handle_chat(
            user_id="u1",
            to_user_id="u2",
            message="",
            message_id="m1",
            conversation_id="c1",
            timestamp="2025-01-01T00:00:00",
            correlation_id="c",
            voice_data="data",
            input_type="voice",
        )

        # Should fall back to text (TTS error is logged, not raised)
        assert result["output_type"] == "text"
        assert result["agent_voice_url"] is None


# ──────────────────────── No Voice Processor ─────────────────────


class TestChatServiceNoVoice:

    @pytest.mark.asyncio
    async def test_voice_input_without_processor_uses_empty_message(
        self, mock_orchestrator
    ):
        """When voice_processor is None, voice data is ignored."""
        svc = ChatService(orchestrator=mock_orchestrator)

        result = await svc.handle_chat(
            user_id="u1",
            to_user_id="u2",
            message="",
            message_id="m1",
            conversation_id="c1",
            timestamp="2025-01-01T00:00:00",
            correlation_id="c",
            voice_data="some-data",
            input_type="voice",
        )

        # Orchestrator receives empty message (no STT)
        orch_req = mock_orchestrator.handle_chat.call_args[0][0]
        assert orch_req.message == ""
