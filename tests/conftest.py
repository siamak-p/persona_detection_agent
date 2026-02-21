"""Shared test fixtures for joowme-agent unit tests."""

from __future__ import annotations

import pytest
from unittest.mock import AsyncMock, MagicMock, patch


@pytest.fixture
def mock_settings():
    """Return a mock Settings object with sensible defaults."""
    s = MagicMock()
    s.QDRANT_URL = "http://localhost:6333"
    s.POSTGRES_HOST = "localhost"
    s.POSTGRES_PORT = 5432
    s.POSTGRES_DB = "joowme"
    s.POSTGRES_USER = "joowme"
    s.POSTGRES_PASSWORD = "joowme"
    s.TENANT_ID = "default"
    s.APP_ENV = "test"
    s.LOG_LEVEL = "DEBUG"

    # LLM
    s.COMPOSER_MODEL = "gpt-4o-mini"
    s.COMPOSER_TEMPERATURE = 0.6
    s.COMPOSER_MAX_TOKENS = 300
    s.GUARDRAIL_MODEL = "gpt-4o-mini"
    s.GUARDRAIL_TEMPERATURE = 0.1
    s.GUARDRAIL_MAX_TOKENS = 200
    s.AGENTS_MODEL = "gpt-4o-mini"
    s.AGENTS_TEMPERATURE = 0.2
    s.TONE_MODEL = "gpt-4o-mini"
    s.TONE_TEMPERATURE = 0.3
    s.TONE_MAX_TOKENS = 1000
    s.FACT_EXTRACTOR_MODEL = "gpt-4o-mini"
    s.FACT_EXTRACTOR_TEMPERATURE = 0.1
    s.FACT_EXTRACTOR_MAX_TOKENS = 2000
    s.SUMMARIZER_MODEL = "gpt-4o-mini"
    s.SUMMARIZER_TEMPERATURE = 0.2
    s.SUMMARIZER_MAX_TOKENS = 1200

    # Voice
    s.VOICE_ENABLED = True
    s.VOICE_TTS_ENABLED = False
    s.VOICE_STT_MODEL = "gpt-4o-audio-preview"

    return s


@pytest.fixture
def mock_openai_client():
    """Return a mock AsyncOpenAI client."""
    client = AsyncMock()
    return client


@pytest.fixture
def mock_voice_processor():
    """Return a mock VoiceProcessor."""
    vp = AsyncMock()
    vp._tts_enabled = False
    vp.process_voice_input = AsyncMock(return_value="transcribed text")
    vp.generate_voice_response = AsyncMock(return_value="/voices/test.mp3")
    return vp


@pytest.fixture
def mock_orchestrator():
    """Return a mock orchestrator with handle_chat and handle_creator."""
    orch = AsyncMock()

    result = MagicMock()
    result.response_text = "Test response from orchestrator"
    result.message_id = "orch-msg-001"
    result.metadata = {}

    orch.handle_chat = AsyncMock(return_value=result)
    orch.handle_creator = AsyncMock(return_value=result)
    return orch
