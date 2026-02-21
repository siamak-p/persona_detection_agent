"""Unit tests for orchestrator/messages.py — Pydantic models & validators."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from orchestrator.messages import (
    ChatRequest,
    ChatResponse,
    CreatorRequest,
    CreatorResponse,
    PassiveRecordItem,
    PassiveRecordRequest,
    PassiveRecordResponse,
    OrchestratorInput,
    OrchestratorOutput,
    validate_iso8601,
)


# ──────────────────────────── validate_iso8601 ────────────────────────────


class TestValidateISO8601:
    def test_valid_without_microseconds(self):
        assert validate_iso8601("2025-01-15T10:30:00") == "2025-01-15T10:30:00"

    def test_valid_with_microseconds(self):
        ts = "2025-01-15T10:30:00.123456"
        assert validate_iso8601(ts) == ts

    def test_invalid_format_raises(self):
        with pytest.raises(ValueError, match="ISO8601"):
            validate_iso8601("not-a-timestamp")

    def test_date_only_raises(self):
        with pytest.raises(ValueError, match="ISO8601"):
            validate_iso8601("2025-01-15")

    def test_empty_string_raises(self):
        with pytest.raises(ValueError, match="ISO8601"):
            validate_iso8601("")

    def test_unix_timestamp_raises(self):
        with pytest.raises(ValueError, match="ISO8601"):
            validate_iso8601("1705312200")


# ──────────────────────────── ChatRequest ────────────────────────────────


class TestChatRequest:
    VALID_TS = "2025-01-15T10:30:00"

    def test_valid_creation(self):
        r = ChatRequest(
            user_id="u1",
            to_user_id="u2",
            message="Hello",
            conversation_id="conv1",
            timestamp=self.VALID_TS,
        )
        assert r.user_id == "u1"
        assert r.to_user_id == "u2"
        assert r.language == "fa"
        assert r.input_type == "text"
        assert r.voice_format == "webm"
        assert r.mode == "chat"

    def test_query_property(self):
        r = ChatRequest(
            user_id="u1",
            to_user_id="u2",
            message="Hey there",
            conversation_id="c1",
            timestamp=self.VALID_TS,
        )
        assert r.query == "Hey there"

    def test_missing_user_id(self):
        with pytest.raises(ValidationError):
            ChatRequest(
                to_user_id="u2",
                message="x",
                conversation_id="c1",
                timestamp=self.VALID_TS,
            )

    def test_empty_user_id(self):
        with pytest.raises(ValidationError):
            ChatRequest(
                user_id="",
                to_user_id="u2",
                message="x",
                conversation_id="c1",
                timestamp=self.VALID_TS,
            )

    def test_invalid_timestamp(self):
        with pytest.raises(ValidationError):
            ChatRequest(
                user_id="u1",
                to_user_id="u2",
                message="x",
                conversation_id="c1",
                timestamp="bad-ts",
            )

    def test_defaults(self):
        r = ChatRequest(
            user_id="u1",
            to_user_id="u2",
            conversation_id="c1",
            timestamp=self.VALID_TS,
        )
        assert r.message == ""
        assert r.message_id is None
        assert r.voice_data is None
        assert r.metadata == {}


# ──────────────────────────── CreatorRequest ──────────────────────────────


class TestCreatorRequest:
    VALID_TS = "2025-06-01T08:00:00"

    def test_valid_creation(self):
        r = CreatorRequest(
            user_id="creator1",
            message="Tell me about yourself",
            timestamp=self.VALID_TS,
        )
        assert r.user_id == "creator1"
        assert r.mode == "creator"
        assert r.query == "Tell me about yourself"

    def test_missing_user_id(self):
        with pytest.raises(ValidationError):
            CreatorRequest(message="x", timestamp=self.VALID_TS)

    def test_invalid_timestamp(self):
        with pytest.raises(ValidationError):
            CreatorRequest(
                user_id="c1", message="x", timestamp="not-valid"
            )


# ──────────────────────────── PassiveRecordItem ──────────────────────────


class TestPassiveRecordItem:
    VALID_TS = "2025-03-20T14:00:00.000"

    def test_valid_creation(self):
        item = PassiveRecordItem(
            user_id="u1",
            to_user_id="u2",
            conversation_id="conv1",
            message="Some message",
            message_id="msg1",
            timestamp=self.VALID_TS,
        )
        assert item.language == "fa"
        assert item.input_type == "text"

    def test_missing_required_fields(self):
        with pytest.raises(ValidationError):
            PassiveRecordItem(
                user_id="u1",
                # missing to_user_id, conversation_id, message_id, timestamp
            )

    def test_invalid_timestamp(self):
        with pytest.raises(ValidationError):
            PassiveRecordItem(
                user_id="u1",
                to_user_id="u2",
                conversation_id="c1",
                message_id="m1",
                timestamp="invalid",
            )


# ──────────────────────────── PassiveRecordRequest ───────────────────────


class TestPassiveRecordRequest:
    def test_valid(self):
        item = PassiveRecordItem(
            user_id="u1",
            to_user_id="u2",
            conversation_id="c1",
            message="hi",
            message_id="m1",
            timestamp="2025-01-01T00:00:00",
        )
        req = PassiveRecordRequest(items=[item])
        assert len(req.items) == 1

    def test_empty_items_fails(self):
        with pytest.raises(ValidationError):
            PassiveRecordRequest(items=[])


# ──────────────────────────── OrchestratorInput / Output ─────────────────


class TestOrchestratorModels:
    def test_orchestrator_input_defaults(self):
        inp = OrchestratorInput(user_id="u1", query="hello")
        assert inp.conversation_id is None
        assert inp.message_id is None
        assert inp.timestamp is None
        assert inp.metadata == {}

    def test_orchestrator_output(self):
        out = OrchestratorOutput(
            message_id="m1", response_text="Hello there"
        )
        assert out.response_text == "Hello there"
        assert out.metadata == {}

    def test_chat_response_output_type(self):
        r = ChatResponse(
            user_id="u1",
            agent_message="Hi",
            agent_message_id="am1",
            conversation_id="c1",
            agent_timestamp="2025-01-01T00:00:00",
            correlation_id="corr1",
        )
        assert r.output_type == "text"
        assert r.agent_voice_url is None
