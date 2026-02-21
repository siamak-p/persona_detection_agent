
from __future__ import annotations

import hashlib
import logging
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Dict, List, Optional, Any, Tuple, TYPE_CHECKING
from datetime import datetime

import asyncpg

if TYPE_CHECKING:
    from config.settings import Settings

logger = logging.getLogger(__name__)

DEFAULT_DYADIC_THRESHOLD = 500


def compute_pair_id(user_a: str, user_b: str) -> str:
    lo, hi = sorted([(user_a or "").strip(), (user_b or "").strip()])
    digest = hashlib.sha256(f"{lo}::{hi}".encode("utf-8")).hexdigest()
    return digest[:16]


def sort_user_pair(user_a: str, user_b: str) -> Tuple[str, str]:
    return tuple(sorted([user_a, user_b]))


@dataclass
class ArchivedMessage:
    id: int
    user_id: str
    to_user_id: str
    conversation_id: str
    message_id: str
    message: str
    language: str
    timestamp_iso: str
    archived_at: datetime
    deleted: bool = False


@dataclass 
class PairCounterRecord:
    id: int
    user_a: str
    user_b: str
    pair_id: str
    total_archived_count: int
    last_dyadic_calc_at_count: int
    last_relationship_class: Optional[str]
    created_at: datetime
    last_updated_at: datetime


class PassiveArchiveStorage:

    def __init__(self, dsn: str) -> None:
        self._dsn = dsn
    
    async def close(self) -> None:
        pass
    
    async def _require_pool(self) -> asyncpg.Pool:
        from db.shared_pool import SharedPostgresPool
        return await SharedPostgresPool.get_pool(self._dsn)

    async def archive_messages(
        self,
        messages: List[Dict[str, Any]],
    ) -> int:
        if not messages:
            return 0
        
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            values = [
                (
                    msg.get("user_id", ""),
                    msg.get("to_user_id", ""),
                    msg.get("conversation_id", ""),
                    msg.get("message_id", ""),
                    msg.get("message", ""),
                    msg.get("language", "fa"),
                    msg.get("timestamp_iso", ""),
                    False,
                )
                for msg in messages
            ]
            
            result = await conn.executemany(
                """
                INSERT INTO passive_archive 
                    (user_id, to_user_id, conversation_id, message_id, message, language, timestamp_iso, deleted)
                VALUES ($1, $2, $3, $4, $5, $6, $7, $8)
                ON CONFLICT (conversation_id, message_id) DO NOTHING
                """,
                values,
            )
        
        logger.info(f"passive_archive:archived:{len(messages)} messages")
        return len(messages)

    async def get_messages_for_pair(
        self,
        user_a: str,
        user_b: str,
        limit: int = 500,
        latest_first: bool = True,
    ) -> List[ArchivedMessage]:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            order = "DESC" if latest_first else "ASC"
            rows = await conn.fetch(
                f"""
                SELECT id, user_id, to_user_id, conversation_id, message_id,
                       message, language, timestamp_iso, archived_at, deleted
                FROM passive_archive
                WHERE ((user_id = $1 AND to_user_id = $2)
                   OR (user_id = $2 AND to_user_id = $1))
                   AND deleted = FALSE
                ORDER BY timestamp_iso {order}
                LIMIT $3
                """,
                user_a,
                user_b,
                limit,
            )
        
        messages = [
            ArchivedMessage(
                id=row["id"],
                user_id=row["user_id"],
                to_user_id=row["to_user_id"],
                conversation_id=row["conversation_id"],
                message_id=row["message_id"],
                message=row["message"],
                language=row["language"],
                timestamp_iso=row["timestamp_iso"],
                archived_at=row["archived_at"],
                deleted=row["deleted"],
            )
            for row in rows
        ]
        
        if latest_first:
            messages.reverse()
        
        return messages

    async def count_messages_for_pair(self, user_a: str, user_b: str) -> int:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM passive_archive
                WHERE ((user_id = $1 AND to_user_id = $2)
                   OR (user_id = $2 AND to_user_id = $1))
                   AND deleted = FALSE
                """,
                user_a,
                user_b,
            )
        
        return int(count or 0)

    async def mark_as_deleted(
        self,
        user_a: str,
        user_b: str,
        message_ids: Optional[List[int]] = None,
    ) -> int:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            if message_ids:
                result = await conn.execute(
                    """
                    UPDATE passive_archive
                    SET deleted = TRUE
                    WHERE id = ANY($1) AND deleted = FALSE
                    """,
                    message_ids,
                )
            else:
                result = await conn.execute(
                    """
                    UPDATE passive_archive
                    SET deleted = TRUE
                    WHERE ((user_id = $1 AND to_user_id = $2)
                       OR (user_id = $2 AND to_user_id = $1))
                       AND deleted = FALSE
                    """,
                    user_a,
                    user_b,
                )
        
        count = int(result.split()[-1]) if result else 0
        
        logger.info(
            f"passive_archive:soft_delete:{count} messages marked as deleted",
            extra={"user_a": user_a, "user_b": user_b},
        )
        
        return count

    def _lock_key(self, pair_id: str, conversation_id: str) -> int:
        combined = f"passive_summ::{pair_id}::{conversation_id}"
        h = hashlib.sha256(combined.encode("utf-8")).digest()
        return int.from_bytes(h[:8], byteorder="big", signed=True)

    @asynccontextmanager
    async def acquire_summarization_lock(
        self,
        user_a: str,
        user_b: str,
        conversation_id: str,
    ):
        pool = await self._require_pool()
        pair_id = compute_pair_id(user_a, user_b)
        lock_key = self._lock_key(pair_id, conversation_id)

        conn = await pool.acquire()
        acquired = False
        try:
            logger.debug(f"passive_archive:lock:attempting:{lock_key} for {pair_id}")
            acquired = await conn.fetchval(
                "SELECT pg_try_advisory_lock($1)",
                lock_key,
            )
            if not acquired:
                logger.warning(f"passive_archive:lock:failed:{pair_id}")
                raise RuntimeError(
                    f"Could not acquire passive summarization lock for {pair_id}"
                )

            logger.debug(f"passive_archive:lock:acquired:{lock_key}")
            yield
        finally:
            if acquired:
                await conn.fetchval("SELECT pg_advisory_unlock($1)", lock_key)
                logger.debug(f"passive_archive:lock:released:{lock_key}")
            await pool.release(conn)


class PassivePairCounter:

    DYADIC_THRESHOLD = DEFAULT_DYADIC_THRESHOLD

    def __init__(self, dsn: str, settings: Optional["Settings"] = None) -> None:
        self._dsn = dsn
        
        if settings:
            self._dyadic_threshold = getattr(
                settings, "DYADIC_THRESHOLD", DEFAULT_DYADIC_THRESHOLD
            )
        else:
            self._dyadic_threshold = DEFAULT_DYADIC_THRESHOLD
    
    async def close(self) -> None:
        pass
    
    async def _require_pool(self) -> asyncpg.Pool:
        from db.shared_pool import SharedPostgresPool
        return await SharedPostgresPool.get_pool(self._dsn)

    async def increment(
        self,
        user_a: str,
        user_b: str,
        count: int = 1,
    ) -> PairCounterRecord:
        pool = await self._require_pool()
        
        sorted_a, sorted_b = sort_user_pair(user_a, user_b)
        pair_id = compute_pair_id(user_a, user_b)
        
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                INSERT INTO passive_pair_counter 
                    (user_a, user_b, pair_id, total_archived_count)
                VALUES ($1, $2, $3, $4)
                ON CONFLICT (pair_id) DO UPDATE SET
                    total_archived_count = passive_pair_counter.total_archived_count + $4,
                    last_updated_at = NOW()
                RETURNING id, user_a, user_b, pair_id, total_archived_count,
                          last_dyadic_calc_at_count, last_relationship_class,
                          created_at, last_updated_at
                """,
                sorted_a,
                sorted_b,
                pair_id,
                count,
            )
        
        return PairCounterRecord(
            id=row["id"],
            user_a=row["user_a"],
            user_b=row["user_b"],
            pair_id=row["pair_id"],
            total_archived_count=row["total_archived_count"],
            last_dyadic_calc_at_count=row["last_dyadic_calc_at_count"],
            last_relationship_class=row["last_relationship_class"],
            created_at=row["created_at"],
            last_updated_at=row["last_updated_at"],
        )

    async def needs_dyadic_calculation(self, user_a: str, user_b: str) -> bool:
        pool = await self._require_pool()
        pair_id = compute_pair_id(user_a, user_b)
        
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT total_archived_count, last_dyadic_calc_at_count
                FROM passive_pair_counter
                WHERE pair_id = $1
                """,
                pair_id,
            )
        
        if not row:
            return False
        
        total = row["total_archived_count"]
        last_calc = row["last_dyadic_calc_at_count"]
        
        return (total - last_calc) >= self._dyadic_threshold

    async def mark_dyadic_calculated(
        self,
        user_a: str,
        user_b: str,
        relationship_class: Optional[str] = None,
    ) -> None:
        pool = await self._require_pool()
        pair_id = compute_pair_id(user_a, user_b)
        
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE passive_pair_counter
                SET last_dyadic_calc_at_count = total_archived_count,
                    last_relationship_class = $2,
                    last_updated_at = NOW()
                WHERE pair_id = $1
                """,
                pair_id,
                relationship_class,
            )

    async def get(self, user_a: str, user_b: str) -> Optional[PairCounterRecord]:
        pool = await self._require_pool()
        pair_id = compute_pair_id(user_a, user_b)
        
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id, user_a, user_b, pair_id, total_archived_count,
                       last_dyadic_calc_at_count, last_relationship_class,
                       created_at, last_updated_at
                FROM passive_pair_counter
                WHERE pair_id = $1
                """,
                pair_id,
            )
        
        if not row:
            return None
        
        return PairCounterRecord(
            id=row["id"],
            user_a=row["user_a"],
            user_b=row["user_b"],
            pair_id=row["pair_id"],
            total_archived_count=row["total_archived_count"],
            last_dyadic_calc_at_count=row["last_dyadic_calc_at_count"],
            last_relationship_class=row["last_relationship_class"],
            created_at=row["created_at"],
            last_updated_at=row["last_updated_at"],
        )

    async def get_pairs_needing_dyadic(self, limit: int = 50) -> List[PairCounterRecord]:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, user_a, user_b, pair_id, total_archived_count,
                       last_dyadic_calc_at_count, last_relationship_class,
                       created_at, last_updated_at
                FROM passive_pair_counter
                WHERE (total_archived_count - last_dyadic_calc_at_count) >= $1
                ORDER BY (total_archived_count - last_dyadic_calc_at_count) DESC
                LIMIT $2
                """,
                self._dyadic_threshold,
                limit,
            )
        
        return [
            PairCounterRecord(
                id=row["id"],
                user_a=row["user_a"],
                user_b=row["user_b"],
                pair_id=row["pair_id"],
                total_archived_count=row["total_archived_count"],
                last_dyadic_calc_at_count=row["last_dyadic_calc_at_count"],
                last_relationship_class=row["last_relationship_class"],
                created_at=row["created_at"],
                last_updated_at=row["last_updated_at"],
            )
            for row in rows
        ]

    async def get_all_pairs(
        self, 
        min_messages: int = 0, 
        limit: int = 100,
    ) -> List[PairCounterRecord]:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT id, user_a, user_b, pair_id, total_archived_count,
                       last_dyadic_calc_at_count, last_relationship_class,
                       created_at, last_updated_at
                FROM passive_pair_counter
                WHERE total_archived_count >= $1
                ORDER BY total_archived_count DESC
                LIMIT $2
                """,
                min_messages,
                limit,
            )
        
        return [
            PairCounterRecord(
                id=row["id"],
                user_a=row["user_a"],
                user_b=row["user_b"],
                pair_id=row["pair_id"],
                total_archived_count=row["total_archived_count"],
                last_dyadic_calc_at_count=row["last_dyadic_calc_at_count"],
                last_relationship_class=row["last_relationship_class"],
                created_at=row["created_at"],
                last_updated_at=row["last_updated_at"],
            )
            for row in rows
        ]
