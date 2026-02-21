
from __future__ import annotations

import logging
from typing import Any, Dict, List, Optional

import asyncpg

logger = logging.getLogger(__name__)

MAX_MESSAGES_PER_USER = 40


class CreatorChatStore:
    def __init__(self, dsn: str) -> None:
        self._dsn = dsn

    async def _require_pool(self) -> asyncpg.Pool:
        from db.shared_pool import SharedPostgresPool
        return await SharedPostgresPool.get_pool(self._dsn)

    async def connect(self) -> None:
        await self._require_pool()

    async def disconnect(self) -> None:
        pass

    async def log_message(
        self,
        *,
        user_id: str,
        text: str,
        role: str = "human",
        input_type: str = "text",
        voice_url: str | None = None,
        voice_duration_seconds: float | None = None,
    ) -> int:
        pool = await self._require_pool()

        async with pool.acquire() as conn:
            rec_id = await conn.fetchval(
                """
                INSERT INTO creator_chat_events
                    (user_id, role, text, input_type, voice_url, voice_duration_seconds)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING id
                """,
                user_id,
                role,
                text,
                input_type,
                voice_url,
                voice_duration_seconds,
            )

            await conn.execute(
                """
                DELETE FROM creator_chat_events
                WHERE id NOT IN (
                    SELECT id FROM creator_chat_events
                    WHERE user_id = $1
                    ORDER BY ts DESC
                    LIMIT $2
                )
                AND user_id = $1
                """,
                user_id,
                MAX_MESSAGES_PER_USER,
            )

            logger.debug(
                "creator_chat_store:log_message",
                extra={"user_id": user_id, "role": role, "id": rec_id, "input_type": input_type}
            )

        return int(rec_id)

    async def get_recent_messages(
        self,
        *,
        user_id: str,
        limit: int = MAX_MESSAGES_PER_USER,
    ) -> List[Dict[str, Any]]:
        pool = await self._require_pool()

        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, role, text, ts
                FROM creator_chat_events
                WHERE user_id = $1
                ORDER BY ts DESC
                LIMIT $2
                """,
                user_id,
                limit,
            )

        return [
            {
                "id": r["id"],
                "role": r["role"],
                "text": r["text"],
                "ts": r["ts"].isoformat() if r["ts"] else None,
            }
            for r in reversed(rows)
        ]

    async def get_last_ai_message(self, *, user_id: str) -> Optional[str]:
        pool = await self._require_pool()

        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT text FROM creator_chat_events
                WHERE user_id = $1 AND role = 'ai'
                ORDER BY ts DESC
                LIMIT 1
                """,
                user_id,
            )

        return row["text"] if row else None

    async def get_message_count(self, *, user_id: str) -> int:
        pool = await self._require_pool()

        async with pool.acquire() as conn:
            count = await conn.fetchval(
                "SELECT COUNT(*) FROM creator_chat_events WHERE user_id = $1",
                user_id,
            )

        return int(count or 0)

    async def clear_history(self, *, user_id: str) -> int:
        pool = await self._require_pool()

        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM creator_chat_events WHERE user_id = $1",
                user_id,
            )
            return int(result.split()[-1]) if result else 0
