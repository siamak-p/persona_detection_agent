
from __future__ import annotations

from datetime import datetime
from typing import Any, Dict, List, Literal, Optional

from pydantic import BaseModel, Field, field_validator


def validate_iso8601(value: str) -> str:
    formats = (
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%S.%f",
    )
    for fmt in formats:
        try:
            datetime.strptime(value, fmt)
            return value
        except ValueError:
            continue
    raise ValueError("timestamp must be ISO8601 format")


class ChatRequest(BaseModel):

    user_id: str = Field(..., min_length=1, description="Sending user identifier")
    to_user_id: str = Field(..., min_length=1, description="Recipient user identifier")
    language: str = Field(
        "fa", min_length=2, description="Preferred response language (ISO 639-1 code)"
    )
    message: str = Field("", description="Message content (can be empty if voice)")
    message_id: str | None = Field(None, description="Client message identifier")
    conversation_id: str = Field(..., min_length=1, description="Conversation identifier")
    timestamp: str = Field(..., description="User timestamp (ISO 8601)")
    metadata: dict[str, Any] = Field(default_factory=dict)
    mode: Literal["chat"] = "chat"
    
    voice_data: Optional[str] = Field(None, description="Base64 encoded audio data")
    input_type: Literal["text", "voice"] = Field("text", description="Input type")
    voice_format: str = Field("webm", description="Audio format (webm, opus, mp3, wav)")

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        return validate_iso8601(v)

    @property
    def query(self) -> str:
        return self.message


class ChatResponse(BaseModel):

    user_id: str = Field(..., description="Recipient user identifier")
    agent_message: str = Field(..., description="Agent generated message")
    agent_message_id: str = Field(..., description="Agent message identifier")
    conversation_id: str = Field(..., description="Conversation identifier")
    agent_timestamp: str = Field(..., description="Agent timestamp")
    correlation_id: str = Field(..., description="Correlation tracking ID")
    
    agent_voice_url: Optional[str] = Field(None, description="URL to voice response file")
    output_type: Literal["text", "voice"] = Field("text", description="Output type")


class CreatorRequest(BaseModel):

    user_id: str = Field(..., min_length=1, description="User identifier")
    language: str = Field(
        "fa", min_length=2, description="Preferred response language (ISO 639-1 code)"
    )
    message: str = Field("", description="User message (can be empty if voice)")
    message_id: str | None = Field(None, description="Message identifier")
    timestamp: str = Field(..., description="Timestamp from user's system (ISO 8601)")
    metadata: dict[str, Any] = Field(default_factory=dict)
    mode: Literal["creator"] = "creator"
    
    voice_data: Optional[str] = Field(None, description="Base64 encoded audio data")
    input_type: Literal["text", "voice"] = Field("text", description="Input type")
    voice_format: str = Field("webm", description="Audio format (webm, opus, mp3, wav)")

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        return validate_iso8601(v)

    @property
    def query(self) -> str:
        return self.message


class CreatorResponse(BaseModel):

    user_id: str = Field(..., description="Original user identifier")
    agent_message: str = Field(..., description="Agent generated message")
    agent_message_id: str = Field(..., description="Agent-generated message identifier")
    agent_timestamp: str = Field(..., description="Agent-generated timestamp")
    correlation_id: str = Field(..., description="Correlation ID for tracking")
    
    agent_voice_url: Optional[str] = Field(None, description="URL to voice response file")
    output_type: Literal["text", "voice"] = Field("text", description="Output type")


class PassiveRecordItem(BaseModel):

    user_id: str = Field(..., min_length=1, description="User identifier")
    to_user_id: str = Field(..., min_length=1, description="User to identifier")
    language: str = Field(
        "fa", min_length=2, description="Preferred language for this context (ISO 639-1 code)"
    )
    conversation_id: str = Field(..., min_length=1, description="Conversation identifier")
    message: str = Field("", description="Bundled messages (can be empty if voice)")
    message_id: str = Field(..., description="Bundled message identifier")
    timestamp: str = Field(..., description="User timestamp (ISO 8601)")
    
    voice_data: Optional[str] = Field(None, description="Base64 encoded audio data")
    input_type: Literal["text", "voice"] = Field("text", description="Input type")
    voice_format: str = Field("webm", description="Audio format (webm, opus, mp3, wav)")

    @field_validator("timestamp")
    @classmethod
    def validate_timestamp(cls, v: str) -> str:
        return validate_iso8601(v)


class PassiveRecordRequest(BaseModel):

    items: List[PassiveRecordItem] = Field(..., min_length=1)


class PassiveRecordResponse(BaseModel):

    received: bool = Field(..., description="Indicates successful ingestion")
    agent_timestamp: str = Field(..., description="Agent timestamp")
    correlation_id: str = Field(..., description="Correlation tracking ID")


class PassiveLastMessageIdResponse(BaseModel):

    lastMsgId: str = Field(..., description="Last synced message identifier")


class OrchestratorInput(BaseModel):

    user_id: str
    query: str
    conversation_id: str | None = None
    message_id: str | None = None
    timestamp: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)


class PassiveCompactRequest(BaseModel):

    user_id: str | None = None
    since: str | None = None
    until: str | None = None
    metadata: dict[str, Any] = Field(default_factory=dict)
    mode: Literal["passive_batch"] = "passive_batch"


class OrchestratorOutput(BaseModel):

    message_id: str
    response_text: str
    metadata: dict[str, Any] = Field(default_factory=dict)
