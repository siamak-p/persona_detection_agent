
from __future__ import annotations

import logging
from typing import Literal

from openai import AsyncOpenAI

from .base import TextToSpeechProvider

logger = logging.getLogger(__name__)

VoiceType = Literal["alloy", "echo", "fable", "onyx", "nova", "shimmer"]


class OpenAITextToSpeech(TextToSpeechProvider):
    def __init__(
        self,
        client: AsyncOpenAI,
        model: str = "tts-1",
        default_voice: VoiceType = "alloy",
    ):
        self._client = client
        self._model = model
        self._default_voice = default_voice

    async def synthesize(
        self,
        text: str,
        voice: str = None,
        speed: float = 1.0,
    ) -> bytes:
        voice = voice or self._default_voice

        logger.info(
            "openai_tts:synthesize:start",
            extra={"text_length": len(text), "voice": voice, "speed": speed},
        )

        try:
            speed = max(0.25, min(4.0, speed))

            if len(text) > 4096:
                logger.warning(
                    "openai_tts:text_truncated",
                    extra={"original_length": len(text), "truncated_to": 4096},
                )
                text = text[:4096]

            response = await self._client.audio.speech.create(
                model=self._model,
                voice=voice,
                input=text,
                response_format="mp3",
                speed=speed,
            )

            audio_bytes = response.content

            logger.info(
                "openai_tts:synthesize:success",
                extra={"voice": voice, "audio_size": len(audio_bytes)},
            )

            return audio_bytes

        except Exception as e:
            logger.error(
                "openai_tts:synthesize:error",
                extra={"voice": voice, "error": str(e)},
                exc_info=True,
            )
            raise
