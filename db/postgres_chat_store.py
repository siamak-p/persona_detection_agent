
from __future__ import annotations

import hashlib
import logging
from typing import Any, Dict, List, Optional, Sequence
from contextlib import asynccontextmanager

import asyncpg

logger = logging.getLogger(__name__)


def compute_pair_id(user_a: str, user_b: str) -> str:
    lo, hi = sorted([(user_a or "").strip(), (user_b or "").strip()])
    digest = hashlib.sha256(f"{lo}::{hi}".encode("utf-8")).hexdigest()
    return digest[:16]


class PostgresChatStore:

    def __init__(self, dsn: str, tenant_id: str = "default") -> None:
        self._dsn = dsn
        self._tenant_id = tenant_id

    async def _require_pool(self) -> asyncpg.Pool:
        from db.shared_pool import SharedPostgresPool
        return await SharedPostgresPool.get_pool(self._dsn)

    async def _init_connection(self, conn: asyncpg.Connection) -> None:
        await conn.execute(f"SET app.tenant_id = '{self._tenant_id}';")

    async def log_event(
        self,
        *,
        author_id: str,
        user_a: str,
        user_b: str,
        conversation_id: str,
        text: str,
        role: str = "human",
        token_count: int | None = None,
        message_id: str | None = None,
    ) -> int:
        pool = await self._require_pool()
        pair_id = compute_pair_id(user_a, user_b)

        if token_count is None:
            token_count = max(1, len(text) // 4)

        async with pool.acquire() as conn:
            rec_id = await conn.fetchval(
                """
                INSERT INTO chat_events (tenant_id, pair_id, conversation_id, author_id, role, text, token_count, message_id)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (tenant_id, pair_id, conversation_id, message_id) 
                WHERE message_id IS NOT NULL
                DO UPDATE SET id = chat_events.id
                RETURNING id
                """,
                self._tenant_id,
                pair_id,
                conversation_id,
                author_id,
                role,
                text,
                token_count,
                message_id,
            )
        return int(rec_id)

    async def get_recent_events(
        self,
        *,
        user_a: str,
        user_b: str,
        conversation_id: str,
        limit: int = 10,
        include_deleted: bool = False,
    ) -> List[Dict[str, Any]]:
        pool = await self._require_pool()
        pair_id = compute_pair_id(user_a, user_b)
        deleted_clause = "" if include_deleted else "AND deleted=false"
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                f"""
                SELECT id, author_id, role, text, token_count, ts, message_id
                FROM chat_events
                WHERE tenant_id=$1 AND pair_id=$2 AND conversation_id=$3
                {deleted_clause}
                ORDER BY ts DESC
                LIMIT $4
                """,
                self._tenant_id,
                pair_id,
                conversation_id,
                limit,
            )
        return [
            {
                "id": r["id"],
                "author": r["author_id"],
                "role": r["role"],
                "text": r["text"],
                "token_count": r["token_count"],
                "ts": r["ts"].isoformat() if r["ts"] else None,
                "message_id": r["message_id"],
            }
            for r in reversed(rows)
        ]

    async def count_active(self, *, user_a: str, user_b: str, conversation_id: str) -> int:
        pool = await self._require_pool()
        pair_id = compute_pair_id(user_a, user_b)
        async with pool.acquire() as conn:
            n = await conn.fetchval(
                """
                SELECT COUNT(*) FROM chat_events
                WHERE tenant_id=$1 AND pair_id=$2 AND conversation_id=$3 AND deleted=false
                  AND role IN ('human', 'ai')
                """,
                self._tenant_id,
                pair_id,
                conversation_id,
            )
        return int(n or 0)

    async def sum_active_tokens(self, *, user_a: str, user_b: str, conversation_id: str) -> int:
        pool = await self._require_pool()
        pair_id = compute_pair_id(user_a, user_b)
        async with pool.acquire() as conn:
            total = await conn.fetchval(
                """
                SELECT COALESCE(SUM(token_count), 0) FROM chat_events
                WHERE tenant_id=$1 AND pair_id=$2 AND conversation_id=$3 AND deleted=false
                  AND role IN ('human', 'ai')
                """,
                self._tenant_id,
                pair_id,
                conversation_id,
            )
        return int(total or 0)

    async def get_last_ai_message(
        self,
        *,
        user_a: str,
        user_b: str,
        conversation_id: str,
    ) -> Optional[str]:
        pool = await self._require_pool()
        pair_id = compute_pair_id(user_a, user_b)
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT text FROM chat_events
                WHERE tenant_id=$1 AND pair_id=$2 AND conversation_id=$3 
                  AND deleted=false AND role='ai'
                ORDER BY ts DESC
                LIMIT 1
                """,
                self._tenant_id,
                pair_id,
                conversation_id,
            )
        return row["text"] if row else None

    async def delete_by_ids(self, ids: Sequence[int]) -> int:
        if not ids:
            return 0
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            result = await conn.execute(
                "DELETE FROM chat_events WHERE id = ANY($1::bigint[])",
                list(ids),
            )
            return int(result.split()[-1]) if result else 0

    async def delete_oldest_n(
        self,
        *,
        user_a: str,
        user_b: str,
        conversation_id: str,
        n: int,
    ) -> int:
        if n <= 0:
            return 0
        pool = await self._require_pool()
        pair_id = compute_pair_id(user_a, user_b)
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id
                FROM chat_events
                WHERE tenant_id=$1 AND pair_id=$2 AND conversation_id=$3 AND deleted=false
                  AND role IN ('human', 'ai')
                ORDER BY ts ASC
                LIMIT $4
                """,
                self._tenant_id,
                pair_id,
                conversation_id,
                n,
            )
            ids = [r["id"] for r in rows]
            if not ids:
                return 0
            result = await conn.execute(
                "DELETE FROM chat_events WHERE id = ANY($1::bigint[])",
                ids,
            )
            return int(result.split()[-1]) if result else 0

    async def enqueue_retry(
        self,
        *,
        user_a: str,
        user_b: str,
        conversation_id: str,
        next_retry_at: Any,
        last_error: str | None = None,
    ) -> int:
        pool = await self._require_pool()
        pair_id = compute_pair_id(user_a, user_b)
        async with pool.acquire() as conn:
            rec_id = await conn.fetchval(
                """
                INSERT INTO summarization_retry_queue 
                    (tenant_id, pair_id, user_a, user_b, conversation_id, next_retry_at, last_error)
                VALUES ($1, $2, $3, $4, $5, $6, $7)
                RETURNING id
                """,
                self._tenant_id,
                pair_id,
                user_a,
                user_b,
                conversation_id,
                next_retry_at,
                last_error or "",
            )
        return int(rec_id)

    async def update_retry_attempt(
        self,
        *,
        retry_id: int,
        next_retry_at: str,
        last_error: str | None = None,
    ) -> None:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE summarization_retry_queue
                SET attempt_count = attempt_count + 1,
                    next_retry_at = $2,
                    last_error = $3,
                    updated_at = NOW()
                WHERE id = $1
                """,
                retry_id,
                next_retry_at,
                last_error or "",
            )

    async def remove_retry(self, retry_id: int) -> None:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            await conn.execute(
                "DELETE FROM summarization_retry_queue WHERE id = $1",
                retry_id,
            )

    async def get_pending_retries(self, limit: int = 10) -> List[Dict[str, Any]]:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, tenant_id, pair_id, user_a, user_b, conversation_id, attempt_count, last_error
                FROM summarization_retry_queue
                WHERE tenant_id = $1 AND next_retry_at <= NOW() AND attempt_count < 10
                ORDER BY next_retry_at ASC
                LIMIT $2
                """,
                self._tenant_id,
                limit,
            )
        return [dict(r) for r in rows]

    async def move_retry_to_failed(
        self,
        *,
        retry_id: int,
        last_error: str | None = None,
    ) -> int | None:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, tenant_id, pair_id, user_a, user_b, conversation_id, 
                       attempt_count, last_error, created_at
                FROM summarization_retry_queue
                WHERE id = $1
                """,
                retry_id,
            )
            
            if not row:
                logger.warning(f"summary_retry:not_found:{retry_id}")
                return None
            
            failed_id = await conn.fetchval(
                """
                INSERT INTO summarization_failed 
                    (tenant_id, pair_id, user_a, user_b, conversation_id, 
                     attempt_count, last_error, created_at)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                RETURNING id
                """,
                row["tenant_id"],
                row["pair_id"],
                row["user_a"],
                row["user_b"],
                row["conversation_id"],
                row["attempt_count"] + 1,
                last_error or row["last_error"],
                row["created_at"],
            )
            
            await conn.execute(
                "DELETE FROM summarization_retry_queue WHERE id = $1",
                retry_id,
            )
            
            logger.warning(
                "summary_retry:moved_to_failed",
                extra={
                    "retry_id": retry_id,
                    "failed_id": failed_id,
                    "pair_id": row["pair_id"],
                    "attempts": row["attempt_count"] + 1,
                },
            )
            return int(failed_id)

    async def get_failed_summaries(self, limit: int = 100, offset: int = 0) -> List[Dict[str, Any]]:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, pair_id, user_a, user_b, conversation_id,
                       attempt_count, last_error, created_at, failed_at
                FROM summarization_failed
                WHERE tenant_id = $1
                ORDER BY failed_at DESC
                LIMIT $2 OFFSET $3
                """,
                self._tenant_id,
                limit,
                offset,
            )
        return [dict(r) for r in rows]

    async def get_retry_queue_stats(self) -> Dict[str, int]:
        pool = await self._require_pool()
        async with pool.acquire() as conn:
            retry_total = await conn.fetchval(
                "SELECT COUNT(*) FROM summarization_retry_queue WHERE tenant_id = $1",
                self._tenant_id,
            )
            retry_pending = await conn.fetchval(
                """
                SELECT COUNT(*) FROM summarization_retry_queue 
                WHERE tenant_id = $1 AND next_retry_at <= NOW() AND attempt_count < 10
                """,
                self._tenant_id,
            )
            failed_total = await conn.fetchval(
                "SELECT COUNT(*) FROM summarization_failed WHERE tenant_id = $1",
                self._tenant_id,
            )
        
        return {
            "retry_total": retry_total or 0,
            "retry_pending": retry_pending or 0,
            "failed_total": failed_total or 0,
        }

    def _lock_key(self, pair_id: str, conversation_id: str) -> int:
        combined = f"{self._tenant_id}::{pair_id}::{conversation_id}"
        h = hashlib.sha256(combined.encode("utf-8")).digest()
        return int.from_bytes(h[:8], byteorder="big", signed=True)

    @asynccontextmanager
    async def acquire_summarization_lock(
        self,
        *,
        user_a: str,
        user_b: str,
        conversation_id: str,
        timeout_seconds: float = 5.0,
    ):
        pool = await self._require_pool()
        pair_id = compute_pair_id(user_a, user_b)
        lock_key = self._lock_key(pair_id, conversation_id)

        conn = await pool.acquire()
        acquired = False
        try:
            logger.debug(f"Attempting to acquire advisory lock: {lock_key}")
            acquired = await conn.fetchval(
                "SELECT pg_try_advisory_lock($1)",
                lock_key,
            )
            if not acquired:
                logger.warning(f"Failed to acquire lock for {pair_id}/{conversation_id}")
                raise RuntimeError(
                    f"Could not acquire summarization lock for {pair_id}/{conversation_id}"
                )

            logger.debug(f"Advisory lock acquired: {lock_key}")
            yield
        finally:
            if acquired:
                await conn.fetchval("SELECT pg_advisory_unlock($1)", lock_key)
                logger.debug(f"Advisory lock released: {lock_key}")
            await pool.release(conn)
