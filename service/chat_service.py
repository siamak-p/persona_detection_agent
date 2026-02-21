
from __future__ import annotations

import logging
import uuid
from datetime import datetime
from typing import Any, Optional, TYPE_CHECKING

from orchestrator.messages import ChatRequest as OrchestratorChatRequest

if TYPE_CHECKING:
    from service.voice import VoiceProcessor

logger = logging.getLogger(__name__)


class ChatService:

    def __init__(
        self,
        orchestrator: Any,
        voice_processor: Optional["VoiceProcessor"] = None,
    ):
        self._orchestrator = orchestrator
        self._voice = voice_processor

    async def handle_chat(
        self,
        user_id: str,
        to_user_id: str,
        message: str,
        message_id: str,
        conversation_id: str,
        timestamp: str,
        correlation_id: str,
        language: str = "fa",
        voice_data: Optional[str] = None,
        input_type: str = "text",
        voice_format: str = "webm",
    ) -> dict:
        logger.info(
            "chat_service:handle:start",
            extra={
                "correlation_id": correlation_id,
                "input_type": input_type,
            },
        )

        actual_message = message
        if input_type == "voice" and voice_data and self._voice:
            logger.info(
                "chat_service:voice_input:processing",
                extra={"correlation_id": correlation_id},
            )
            try:
                actual_message = await self._voice.process_voice_input(
                    voice_data, language
                )
                logger.info(
                    "chat_service:voice_input:success",
                    extra={
                        "correlation_id": correlation_id,
                        "transcription_length": len(actual_message),
                    },
                )
            except Exception as e:
                logger.error(
                    "chat_service:voice_input:error",
                    extra={"correlation_id": correlation_id, "error": str(e)},
                    exc_info=True,
                )
                raise

        orch_req = OrchestratorChatRequest(
            user_id=user_id,
            to_user_id=to_user_id,
            language=language,
            message=actual_message,
            message_id=message_id,
            conversation_id=conversation_id,
            timestamp=timestamp,
        )

        result = await self._orchestrator.handle_chat(orch_req, correlation_id)

        agent_message_id = str(uuid.uuid4())
        voice_url = None
        output_type = "text"

        if input_type == "voice" and self._voice and self._voice._tts_enabled:
            logger.info(
                "chat_service:voice_response:generating",
                extra={"correlation_id": correlation_id},
            )
            try:
                voice_url = await self._voice.generate_voice_response(
                    text=result.response_text,
                    conversation_id=conversation_id,
                    message_id=agent_message_id,
                )
                output_type = "voice"
                logger.info(
                    "chat_service:voice_response:success",
                    extra={
                        "correlation_id": correlation_id,
                        "voice_url": voice_url,
                    },
                )
            except Exception as e:
                logger.error(
                    "chat_service:voice_response:error",
                    extra={"correlation_id": correlation_id, "error": str(e)},
                    exc_info=True,
                )

        return {
            "user_id": to_user_id,
            "agent_message": result.response_text,
            "agent_message_id": agent_message_id,
            "conversation_id": conversation_id,
            "agent_timestamp": datetime.utcnow().isoformat(),
            "correlation_id": correlation_id,
            "agent_voice_url": voice_url,
            "output_type": output_type,
        }
