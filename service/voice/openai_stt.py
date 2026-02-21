
from __future__ import annotations

import base64
import logging
from typing import Optional

from openai import AsyncOpenAI

from .base import SpeechToTextProvider, TranscriptionResult

logger = logging.getLogger(__name__)


class OpenAISpeechToText(SpeechToTextProvider):
    def __init__(
        self,
        client: AsyncOpenAI,
        model: str = "openai/gpt-4o-audio-preview",
    ):
        self._client = client
        self._model = model

    async def transcribe(
        self,
        audio_data: bytes,
        language: str = "fa",
    ) -> TranscriptionResult:
        logger.info(
            "openai_stt:transcribe:start",
            extra={"language": language, "audio_size": len(audio_data), "model": self._model},
        )

        try:
            audio_b64 = base64.b64encode(audio_data).decode("utf-8")
            audio_format = self._detect_format(audio_data)

            messages = [
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "input_audio",
                            "input_audio": {
                                "data": audio_b64,
                                "format": audio_format,
                            }
                        },
                        {
                            "type": "text",
                            "text": f"Please transcribe this audio. The audio is in {language} language. "
                                    f"Return ONLY the transcription text, nothing else. No explanations."
                        }
                    ]
                }
            ]

            response = await self._client.chat.completions.create(
                model=self._model,
                messages=messages,
                max_tokens=4096,
            )

            text = response.choices[0].message.content.strip() if response.choices else ""

            word_count = len(text.split())
            estimated_duration = (word_count / 150) * 60

            logger.info(
                "openai_stt:transcribe:success",
                extra={
                    "language": language,
                    "text_length": len(text),
                    "word_count": word_count,
                    "estimated_duration": estimated_duration,
                },
            )

            return TranscriptionResult(
                text=text,
                confidence=1.0,
                duration=estimated_duration,
                language=language,
            )

        except Exception as e:
            logger.error(
                "openai_stt:transcribe:error",
                extra={"language": language, "error": str(e)},
                exc_info=True,
            )
            raise

    def _detect_format(self, audio_data: bytes) -> str:
        if audio_data[:4] == b'RIFF':
            return "wav"
        if audio_data[:3] == b'ID3' or (len(audio_data) > 1 and audio_data[0:2] == b'\xff\xfb'):
            return "mp3"
        if audio_data[:4] == b'OggS':
            return "ogg"
        if audio_data[:4] == b'\x1a\x45\xdf\xa3':
            return "webm"
        return "wav"
