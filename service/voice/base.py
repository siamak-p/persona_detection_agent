
from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Optional


@dataclass
class TranscriptionResult:
    text: str
    confidence: float = 1.0
    duration: float = 0.0
    language: Optional[str] = None


class SpeechToTextProvider(ABC):
    @abstractmethod
    async def transcribe(
        self,
        audio_data: bytes,
        language: str = "fa",
    ) -> TranscriptionResult:
        pass


class TextToSpeechProvider(ABC):
    @abstractmethod
    async def synthesize(
        self,
        text: str,
        voice: str = "alloy",
        speed: float = 1.0,
    ) -> bytes:
        pass


class VoiceStorageProvider(ABC):
    @abstractmethod
    async def save(
        self,
        audio_data: bytes,
        conversation_id: str,
        message_id: str,
        prefix: str = "response",
    ) -> str:
        pass

    @abstractmethod
    async def get(self, url: str) -> Optional[bytes]:
        pass

    @abstractmethod
    async def delete(self, url: str) -> bool:
        pass
