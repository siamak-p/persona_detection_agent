
from __future__ import annotations

import base64
import logging
from typing import Optional

from .base import SpeechToTextProvider, TextToSpeechProvider, VoiceStorageProvider

logger = logging.getLogger(__name__)


class VoiceTooLongError(Exception):
    pass


class VoiceProcessor:
    def __init__(
        self,
        stt: SpeechToTextProvider,
        tts: TextToSpeechProvider,
        storage: VoiceStorageProvider,
        max_duration: int = 300,
        tts_enabled: bool = False,
    ):
        self._stt = stt
        self._tts = tts
        self._storage = storage
        self._max_duration = max_duration
        self._tts_enabled = tts_enabled

        logger.info(
            "voice_processor:init",
            extra={"max_duration": max_duration, "tts_enabled": tts_enabled},
        )

    async def process_voice_input(
        self,
        voice_data_base64: str,
        language: str = "fa",
    ) -> str:
        logger.info(
            "voice_processor:input:start",
            extra={"language": language},
        )

        try:
            audio_bytes = base64.b64decode(voice_data_base64)

            estimated_duration = len(audio_bytes) / 16000
            if estimated_duration > self._max_duration:
                raise VoiceTooLongError(
                    f"Voice input (~{estimated_duration:.0f}s) exceeds maximum "
                    f"allowed duration ({self._max_duration}s)"
                )

            result = await self._stt.transcribe(audio_bytes, language)

            logger.info(
                "voice_processor:input:success",
                extra={
                    "language": language,
                    "text_length": len(result.text),
                    "duration": result.duration,
                },
            )

            return result.text

        except VoiceTooLongError:
            raise
        except Exception as e:
            logger.error(
                "voice_processor:input:error",
                extra={"language": language, "error": str(e)},
                exc_info=True,
            )
            raise

    async def generate_voice_response(
        self,
        text: str,
        conversation_id: str,
        message_id: str,
        voice: str = "alloy",
        speed: float = 1.0,
    ) -> str:
        logger.info(
            "voice_processor:response:start",
            extra={
                "conversation_id": conversation_id,
                "message_id": message_id,
                "text_length": len(text),
                "voice": voice,
            },
        )

        try:
            audio_bytes = await self._tts.synthesize(text, voice, speed)

            voice_url = await self._storage.save(
                audio_bytes,
                conversation_id,
                message_id,
                prefix="response",
            )

            logger.info(
                "voice_processor:response:success",
                extra={
                    "conversation_id": conversation_id,
                    "voice_url": voice_url,
                    "audio_size": len(audio_bytes),
                },
            )

            return voice_url

        except Exception as e:
            logger.error(
                "voice_processor:response:error",
                extra={"conversation_id": conversation_id, "error": str(e)},
                exc_info=True,
            )
            raise

    async def save_input_voice(
        self,
        voice_data_base64: str,
        conversation_id: str,
        message_id: str,
    ) -> str:
        logger.info(
            "voice_processor:save_input:start",
            extra={
                "conversation_id": conversation_id,
                "message_id": message_id,
            },
        )

        try:
            audio_bytes = base64.b64decode(voice_data_base64)

            voice_url = await self._storage.save(
                audio_bytes,
                conversation_id,
                message_id,
                prefix="input",
            )

            logger.info(
                "voice_processor:save_input:success",
                extra={"voice_url": voice_url},
            )

            return voice_url

        except Exception as e:
            logger.error(
                "voice_processor:save_input:error",
                extra={"error": str(e)},
                exc_info=True,
            )
            raise
