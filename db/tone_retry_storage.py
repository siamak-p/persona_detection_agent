
from __future__ import annotations

import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional, Sequence

import asyncpg

logger = logging.getLogger(__name__)


class ToneRetryStorage:

    def __init__(
        self,
        dsn: str,
        tenant_id: str = "default",
        max_attempts: int = 3,
        retry_delays: List[int] | None = None,
    ) -> None:
        self._dsn = dsn
        self._tenant_id = tenant_id
        self._max_attempts = max_attempts
        self._retry_delays = retry_delays or [300, 3600, 14400]

    async def _require_pool(self) -> asyncpg.Pool:
        from db.shared_pool import SharedPostgresPool
        return await SharedPostgresPool.get_pool(self._dsn)

    async def close(self) -> None:
        pass


    async def enqueue_retry(
        self,
        *,
        conversation_id: str,
        user_a: str,
        user_b: str,
        message_ids: Sequence[int],
        last_error: str | None = None,
    ) -> int:
        pool = await self._require_pool()
        
        next_retry = datetime.utcnow() + timedelta(seconds=self._retry_delays[0])
        
        async with pool.acquire() as conn:
            rec_id = await conn.fetchval(
                """
                INSERT INTO tone_retry_queue
                    (tenant_id, conversation_id, user_a, user_b,
                     message_ids, next_retry_at, last_error)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
                """,
                self._tenant_id,
                conversation_id,
                user_a,
                user_b,
                list(message_ids),
                next_retry,
                last_error or "",
            )
        
        logger.info(
            "tone_retry:enqueued",
            extra={
                "conversation_id": conversation_id,
                "message_count": len(message_ids),
                "next_retry": next_retry.isoformat(),
            },
        )
        return int(rec_id)

    async def get_pending_retries(self, limit: int = 10) -> List[Dict[str, Any]]:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM tone_retry_queue
                WHERE tenant_id = $1
                  AND attempt_count < $2
                  AND next_retry_at <= NOW()
                ORDER BY next_retry_at ASC
                LIMIT $3
                """,
                self._tenant_id,
                self._max_attempts,
                limit,
            )
        return [dict(r) for r in rows]

    async def update_retry_attempt(
        self,
        *,
        retry_id: int,
        last_error: str | None = None,
    ) -> bool:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM tone_retry_queue WHERE id = $1",
                retry_id,
            )
            
            if not row:
                logger.warning(f"tone_retry:not_found:{retry_id}")
                return False
            
            new_attempt = row["attempt_count"] + 1
            
            if new_attempt >= self._max_attempts:
                await self._move_to_failed(conn, row, last_error)
                return False
            
            delay_index = min(new_attempt, len(self._retry_delays) - 1)
            next_retry = datetime.utcnow() + timedelta(seconds=self._retry_delays[delay_index])
            
            await conn.execute(
                """
                UPDATE tone_retry_queue
                SET attempt_count = $2,
                    next_retry_at = $3,
                    last_error = $4,
                    updated_at = NOW()
                WHERE id = $1
                """,
                retry_id,
                new_attempt,
                next_retry,
                last_error or "",
            )
            
            logger.info(
                "tone_retry:updated",
                extra={
                    "retry_id": retry_id,
                    "attempt": new_attempt,
                    "next_retry": next_retry.isoformat(),
                },
            )
            return True

    async def remove_retry(self, retry_id: int) -> None:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM tone_retry_queue WHERE id = $1",
                retry_id,
            )
        logger.info(f"tone_retry:removed:{retry_id}")

    async def _move_to_failed(
        self,
        conn: asyncpg.Connection,
        row: asyncpg.Record,
        last_error: str | None,
    ) -> None:
        await conn.execute(
            """
            INSERT INTO tone_failed
                (tenant_id, conversation_id, user_a, user_b,
                 message_ids, attempt_count, last_error, created_at)
            VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
            """,
            row["tenant_id"],
            row["conversation_id"],
            row["user_a"],
            row["user_b"],
            row["message_ids"],
            row["attempt_count"] + 1,
            last_error or row["last_error"],
            row["created_at"],
        )
        
        await conn.execute(
            "DELETE FROM tone_retry_queue WHERE id = $1",
            row["id"],
        )
        
        logger.warning(
            "tone_retry:moved_to_failed",
            extra={
                "conversation_id": row["conversation_id"],
                "attempts": row["attempt_count"] + 1,
            },
        )


    async def get_failed_conversations(
        self,
        limit: int = 100,
        offset: int = 0,
    ) -> List[Dict[str, Any]]:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM tone_failed
                WHERE tenant_id = $1
                ORDER BY failed_at DESC
                LIMIT $2 OFFSET $3
                """,
                self._tenant_id,
                limit,
                offset,
            )
        return [dict(r) for r in rows]

    async def retry_failed(self, failed_id: int) -> int | None:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                "SELECT * FROM tone_failed WHERE id = $1 AND tenant_id = $2",
                failed_id,
                self._tenant_id,
            )
            
            if not row:
                return None
            
            next_retry = datetime.utcnow() + timedelta(seconds=self._retry_delays[0])
            rec_id = await conn.fetchval(
                """
                INSERT INTO tone_retry_queue
                    (tenant_id, conversation_id, user_a, user_b,
                     message_ids, next_retry_at, last_error)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
                """,
                self._tenant_id,
                row["conversation_id"],
                row["user_a"],
                row["user_b"],
                row["message_ids"],
                next_retry,
                "",
            )
            
            await conn.execute(
                "DELETE FROM tone_failed WHERE id = $1",
                failed_id,
            )
            
            logger.info(
                "tone_retry:moved_from_failed",
                extra={"failed_id": failed_id, "new_retry_id": rec_id},
            )
            return int(rec_id)

    async def delete_failed(self, failed_id: int) -> bool:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM tone_failed WHERE id = $1 AND tenant_id = $2",
                failed_id,
                self._tenant_id,
            )
        deleted = result == "DELETE 1"
        if deleted:
            logger.info(f"tone_failed:deleted:{failed_id}")
        return deleted


    async def get_stats(self) -> Dict[str, int]:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            retry_count = await conn.fetchval(
                "SELECT COUNT(*) FROM tone_retry_queue WHERE tenant_id = $1",
                self._tenant_id,
            )
            retry_pending = await conn.fetchval(
                """
                SELECT COUNT(*) FROM tone_retry_queue
                WHERE tenant_id = $1
                  AND attempt_count < $2
                  AND next_retry_at <= NOW()
                """,
                self._tenant_id,
                self._max_attempts,
            )
            failed_count = await conn.fetchval(
                "SELECT COUNT(*) FROM tone_failed WHERE tenant_id = $1",
                self._tenant_id,
            )
        
        return {
            "retry_total": retry_count or 0,
            "retry_pending": retry_pending or 0,
            "failed_total": failed_count or 0,
        }
