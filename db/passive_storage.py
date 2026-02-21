
from __future__ import annotations

from typing import List, Dict, Any, Optional, Sequence
import asyncpg
import logging

logger = logging.getLogger(__name__)


class PassiveStorage:

    def __init__(self, dsn:str) -> None:
        self._dsn: str = dsn
    
    async def _require_pool(self) -> asyncpg.Pool:
        from db.shared_pool import SharedPostgresPool
        return await SharedPostgresPool.get_pool(self._dsn)
    
    
    async def get(self, limit: int = 100) -> List[Dict[str, Any]]:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, user_id, conversation_id, message_id, message, language, timestamp_iso
                FROM passive_observation
                WHERE deleted='false'
                ORDER BY conversation_id, timestamp_iso
                LIMIT $1;
                """,
                limit,
                )
        return[
            {
                "id": r["id"],
                "user_id": r["user_id"],
                "conversation_id": r["conversation_id"],
                "message_id": r["message_id"],
                "message": r["message"],
                "language": r["language"],
                "timestamp_iso": r["timestamp_iso"],
            }
            for r in rows
        ]
    

    async def counts(self, *, user_id: str, conversation_id: str) -> int:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            n = await conn.fetchval(
                """
                SELECT COUNT(*)
                FROM passive_observation
                WHERE deleted='false' AND user_id=$1  AND conversation_id=$2                
                """,
                user_id,
                conversation_id,
            )
        return int(n or 0)


    async def delete_by_ids(self, ids: Sequence[int]) -> int:
        if ids is None or len(ids) == 0:
            logger.info("There is no record id to be deleted ")
            return 0
        
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                DELETE FROM passive_observation WHERE id = ANY($1::bigint[])
                """,
                list(ids),
            )
        return int(result.split()[-1])
    

    async def add_last_message_id(self, user_id: str, message: str, message_id: str, conversation_id: str) -> None:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            result = conn.execute("""INSERT INTO passive_last_message (user_id, message, message_id, conversation_id)
            VALUES ($1, $2, $3, $4)
            """,
            user_id,
            message,
            message_id,
            conversation_id,
            )


    async def insert_to_table(self, *, user_id: str, conversation_id: str, message_id: str, message: str, language: str, timestamp_iso: str) -> int:
        pool = await self._require_pool()
        result = []
        async with pool.acquire() as conn:
            result = await conn.fetchrow(
                """
                INSERT INTO passive_observation (user_id, conversation_id, message_id, message, language, timestamp_iso)
                VALUES ($1, $2, $3, $4, $5, $6)
                RETURNING user_id, message, message_id, conversation_id
                """,
                user_id,
                conversation_id,
                message_id,
                message,
                language,
                timestamp_iso,
            )
        if result is None:
            logger.error("Failed to insert record into passive_observation table")
            return 0

        await self.add_last_message_id(
            result["user_id"],
            result["message"],
            result["message_id"],
            result["conversation_id"],
            )

        return int(result.split()[-1])

    async def clear(self) -> int:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE passive_observation
                SET deleted = 'true'
                WHERE deleted = 'false'
                """
            )
        deleted_count = int(result.split()[-1]) if result else 0
        logger.info(f"passive_storage:clear:deleted={deleted_count}")
        return deleted_count
