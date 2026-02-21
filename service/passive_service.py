
from __future__ import annotations

import logging
import json
from datetime import datetime
from typing import Any, Optional, TYPE_CHECKING
from uuid import uuid4

from sqlalchemy import text

from config.settings import Settings
from db.postgres import create_async_engine, create_async_session_factory, get_async_session

if TYPE_CHECKING:
    from service.voice import VoiceProcessor

logger = logging.getLogger(__name__)


class PassiveService:

    def __init__(
        self,
        passive_memory: Any,
        settings: Settings | None = None,
        voice_processor: Optional["VoiceProcessor"] = None,
    ):
        self._passive = passive_memory
        self._settings = settings or Settings()
        self._session_factory = None
        self._voice = voice_processor

    def _get_session_factory(self):
        if self._session_factory is None:
            dsn = (self._settings.POSTGRES_DSN or self._settings.postgres_url).strip()
            if dsn.startswith("postgresql://") and "+asyncpg" not in dsn:
                dsn = dsn.replace("postgresql://", "postgresql+asyncpg://", 1)
            engine = create_async_engine(dsn)
            self._session_factory = create_async_session_factory(engine)
        return self._session_factory

    async def record_observations(
        self,
        items: list[dict],
        correlation_id: str,
    ) -> dict:
        logger.info(
            "passive_service:record:start",
            extra={"count": len(items), "correlation_id": correlation_id},
        )

        session_factory = self._get_session_factory()

        async with get_async_session(session_factory) as session:
            for item in items:
                language = (item.get("language") or "fa").lower()
                ts_str = item.get("timestamp") or ""
                try:
                    parsed_ts = datetime.fromisoformat(ts_str)
                except Exception:
                    parsed_ts = datetime.utcnow()

                message = item.get("message", "")
                input_type = item.get("input_type", "text")
                voice_data = item.get("voice_data")
                voice_url = None

                if input_type == "voice" and voice_data and self._voice:
                    logger.info(
                        "passive_service:voice_input:processing",
                        extra={
                            "correlation_id": correlation_id,
                            "message_id": item["message_id"],
                        },
                    )
                    try:
                        message = await self._voice.process_voice_input(
                            voice_data, language
                        )
                        voice_url = await self._voice.save_input_voice(
                            voice_data,
                            item["conversation_id"],
                            item["message_id"],
                        )
                        logger.info(
                            "passive_service:voice_input:success",
                            extra={
                                "correlation_id": correlation_id,
                                "transcription_length": len(message),
                                "voice_url": voice_url,
                            },
                        )
                    except Exception as e:
                        logger.error(
                            "passive_service:voice_input:error",
                            extra={
                                "correlation_id": correlation_id,
                                "message_id": item["message_id"],
                                "error": str(e),
                            },
                            exc_info=True,
                        )
                        continue

                meta_data = {"raw": item}
                if voice_url:
                    meta_data["voice_url"] = voice_url
                    meta_data["input_type"] = "voice"

                await session.execute(
                    text(
                    ),
                    {
                        "id": str(uuid4()),
                        "user_id": item["user_id"],
                        "to_user_id": item["to_user_id"],
                        "conversation_id": item["conversation_id"],
                        "message_id": item["message_id"],
                        "message": message,
                        "language": language,
                        "timestamp_iso": ts_str or parsed_ts.isoformat(),
                        "ts": parsed_ts,
                        "meta_data": json.dumps(meta_data),
                    },
                )

                await session.execute(
                    text(
                    ),
                    {
                        "id": str(uuid4()),
                        "user_id": item["user_id"],
                        "last_message_id": item["message_id"],
                    },
                )

        return {
            "received": True,
            "agent_timestamp": datetime.utcnow().isoformat(),
            "correlation_id": correlation_id,
        }

    async def get_last_message_id(self) -> dict:
        session_factory = self._get_session_factory()

        async with get_async_session(session_factory) as session:
            result = await session.execute(
                text(
                )
            )
            state_row = result.first()
            state_msg_id = state_row[0] if state_row else None
            state_updated_at = state_row[1] if state_row else None

            result = await session.execute(
                text(
                )
            )
            archive_row = result.first()
            archive_msg_id = archive_row[0] if archive_row else None
            archive_updated_at = archive_row[1] if archive_row else None

        if state_msg_id and archive_msg_id:
            if state_updated_at and archive_updated_at:
                if state_updated_at >= archive_updated_at:
                    return {"lastMsgId": state_msg_id}
                else:
                    return {"lastMsgId": archive_msg_id}
            return {"lastMsgId": state_msg_id}
        elif state_msg_id:
            return {"lastMsgId": state_msg_id}
        elif archive_msg_id:
            return {"lastMsgId": archive_msg_id}
        else:
            return {"lastMsgId": ""}
