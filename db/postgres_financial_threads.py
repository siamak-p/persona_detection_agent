
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

import asyncpg

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class FinancialThreadStatus(str, Enum):
    OPEN = "open"
    RESOLVED = "resolved"
    EXPIRED = "expired"


class WaitingFor(str, Enum):
    CREATOR = "creator"
    SENDER = "sender"


@dataclass
class FinancialThread:
    id: int
    sender_id: str
    creator_id: str
    conversation_id: str
    status: FinancialThreadStatus
    waiting_for: WaitingFor
    topic_summary: str
    last_sender_message: Optional[str]
    last_creator_response: Optional[str]
    created_at: datetime
    last_activity_at: datetime


@dataclass
class FinancialThreadMessage:
    id: int
    thread_id: int
    author_type: str
    message: str
    delivered: bool
    created_at: datetime


CREATE_TABLES_SQL = """
-- جدول اصلی thread های مالی
CREATE TABLE IF NOT EXISTS financial_threads (
    id SERIAL PRIMARY KEY,
    sender_id VARCHAR(255) NOT NULL,
    creator_id VARCHAR(255) NOT NULL,
    conversation_id VARCHAR(255) NOT NULL,
    status VARCHAR(50) NOT NULL DEFAULT 'open',
    waiting_for VARCHAR(50) NOT NULL DEFAULT 'creator',
    topic_summary TEXT NOT NULL,
    last_sender_message TEXT,
    last_creator_response TEXT,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    last_activity_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- جدول پیام‌های هر thread
CREATE TABLE IF NOT EXISTS financial_thread_messages (
    id SERIAL PRIMARY KEY,
    thread_id INTEGER REFERENCES financial_threads(id) ON DELETE CASCADE,
    author_type VARCHAR(50) NOT NULL,
    message TEXT NOT NULL,
    delivered BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

-- Index ها
CREATE INDEX IF NOT EXISTS idx_fin_threads_sender_creator_status 
    ON financial_threads(sender_id, creator_id, status);
CREATE INDEX IF NOT EXISTS idx_fin_threads_status_activity 
    ON financial_threads(status, last_activity_at);
CREATE INDEX IF NOT EXISTS idx_fin_thread_msgs_thread_delivered 
    ON financial_thread_messages(thread_id, delivered);
"""


class PostgresFinancialThreads:

    def __init__(self, dsn: str):
        self._dsn = dsn
        logger.info("financial_threads:init:success")

    async def _get_pool(self) -> asyncpg.Pool:
        from db.shared_pool import SharedPostgresPool
        return await SharedPostgresPool.get_pool(self._dsn)

    async def ensure_table(self) -> None:
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                await conn.execute(CREATE_TABLES_SQL)
            logger.info("financial_threads:ensure_table:success")
        except Exception as e:
            logger.error(
                "financial_threads:ensure_table:error",
                extra={"error": str(e)},
                exc_info=True,
            )
            raise


    async def create_thread(
        self,
        sender_id: str,
        creator_id: str,
        conversation_id: str,
        topic_summary: str,
        initial_message: str,
    ) -> int:
        sql_thread = """
        INSERT INTO financial_threads 
            (sender_id, creator_id, conversation_id, topic_summary, 
             last_sender_message, status, waiting_for)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING id
        """
        sql_message = """
        INSERT INTO financial_thread_messages 
            (thread_id, author_type, message, delivered)
        VALUES ($1, 'sender', $2, FALSE)
        """
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    thread_id = await conn.fetchval(
                        sql_thread,
                        sender_id,
                        creator_id,
                        conversation_id,
                        topic_summary,
                        initial_message,
                        FinancialThreadStatus.OPEN.value,
                        WaitingFor.CREATOR.value,
                    )
                    
                    await conn.execute(sql_message, thread_id, initial_message)
            
            logger.info(
                "financial_threads:create:success",
                extra={
                    "thread_id": thread_id,
                    "sender_id": sender_id,
                    "creator_id": creator_id,
                    "topic_summary": topic_summary[:100],
                },
            )
            return thread_id
            
        except Exception as e:
            logger.error(
                "financial_threads:create:error",
                extra={
                    "sender_id": sender_id,
                    "creator_id": creator_id,
                    "error": str(e),
                },
                exc_info=True,
            )
            raise

    async def get_active_thread(
        self,
        sender_id: str,
        creator_id: str,
    ) -> Optional[FinancialThread]:
        sql = """
        SELECT id, sender_id, creator_id, conversation_id, status, waiting_for,
               topic_summary, last_sender_message, last_creator_response,
               created_at, last_activity_at
        FROM financial_threads
        WHERE sender_id = $1 AND creator_id = $2 AND status = $3
        ORDER BY created_at DESC
        LIMIT 1
        """
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(
                    sql, sender_id, creator_id, FinancialThreadStatus.OPEN.value
                )
            
            if row:
                return self._row_to_thread(row)
            return None
            
        except Exception as e:
            logger.error(
                "financial_threads:get_active:error",
                extra={"sender_id": sender_id, "creator_id": creator_id, "error": str(e)},
                exc_info=True,
            )
            raise

    async def get_thread_by_id(self, thread_id: int) -> Optional[FinancialThread]:
        sql = """
        SELECT id, sender_id, creator_id, conversation_id, status, waiting_for,
               topic_summary, last_sender_message, last_creator_response,
               created_at, last_activity_at
        FROM financial_threads
        WHERE id = $1
        """
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(sql, thread_id)
            
            if row:
                return self._row_to_thread(row)
            return None
            
        except Exception as e:
            logger.error(
                "financial_threads:get_by_id:error",
                extra={"thread_id": thread_id, "error": str(e)},
                exc_info=True,
            )
            raise

    async def get_open_threads_for_creator(self, creator_id: str) -> List[FinancialThread]:
        sql = """
        SELECT id, sender_id, creator_id, conversation_id, status, waiting_for,
               topic_summary, last_sender_message, last_creator_response,
               created_at, last_activity_at
        FROM financial_threads
        WHERE creator_id = $1 AND status = $2
        ORDER BY last_activity_at DESC
        """
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(sql, creator_id, FinancialThreadStatus.OPEN.value)
            
            return [self._row_to_thread(row) for row in rows]
            
        except Exception as e:
            logger.error(
                "financial_threads:get_for_creator:error",
                extra={"creator_id": creator_id, "error": str(e)},
                exc_info=True,
            )
            raise


    async def add_message(
        self,
        thread_id: int,
        author_type: str,
        message: str,
    ) -> int:
        sql_message = """
        INSERT INTO financial_thread_messages 
            (thread_id, author_type, message, delivered)
        VALUES ($1, $2, $3, FALSE)
        RETURNING id
        """
        
        if author_type == "sender":
            update_field = "last_sender_message"
            new_waiting_for = WaitingFor.CREATOR.value
        else:
            update_field = "last_creator_response"
            new_waiting_for = WaitingFor.SENDER.value
        
        sql_update = f"""
        UPDATE financial_threads
        SET {update_field} = $2,
            waiting_for = $3,
            last_activity_at = NOW()
        WHERE id = $1
        """
        
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                async with conn.transaction():
                    message_id = await conn.fetchval(sql_message, thread_id, author_type, message)
                    
                    await conn.execute(sql_update, thread_id, message, new_waiting_for)
            
            logger.info(
                "financial_threads:add_message:success",
                extra={
                    "thread_id": thread_id,
                    "message_id": message_id,
                    "author_type": author_type,
                },
            )
            return message_id
            
        except Exception as e:
            logger.error(
                "financial_threads:add_message:error",
                extra={"thread_id": thread_id, "error": str(e)},
                exc_info=True,
            )
            raise

    async def get_undelivered_messages(
        self,
        thread_id: int,
        for_author_type: str,
    ) -> List[FinancialThreadMessage]:
        opposite_author = "creator" if for_author_type == "sender" else "sender"
        
        sql = """
        SELECT id, thread_id, author_type, message, delivered, created_at
        FROM financial_thread_messages
        WHERE thread_id = $1 AND author_type = $2 AND delivered = FALSE
        ORDER BY created_at ASC
        """
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(sql, thread_id, opposite_author)
            
            return [self._row_to_message(row) for row in rows]
            
        except Exception as e:
            logger.error(
                "financial_threads:get_undelivered:error",
                extra={"thread_id": thread_id, "error": str(e)},
                exc_info=True,
            )
            raise

    async def mark_message_delivered(self, message_id: int) -> bool:
        sql = """
        UPDATE financial_thread_messages
        SET delivered = TRUE
        WHERE id = $1
        RETURNING id
        """
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                result = await conn.fetchval(sql, message_id)
            
            success = result is not None
            if success:
                logger.info(
                    "financial_threads:mark_delivered:success",
                    extra={"message_id": message_id},
                )
            return success
            
        except Exception as e:
            logger.error(
                "financial_threads:mark_delivered:error",
                extra={"message_id": message_id, "error": str(e)},
                exc_info=True,
            )
            raise

    async def get_recent_messages(
        self,
        thread_id: int,
        limit: int = 10,
    ) -> List[FinancialThreadMessage]:
        sql = """
        SELECT id, thread_id, author_type, message, delivered, created_at
        FROM financial_thread_messages
        WHERE thread_id = $1
        ORDER BY created_at DESC
        LIMIT $2
        """
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(sql, thread_id, limit)
            
            return [self._row_to_message(row) for row in reversed(rows)]
            
        except Exception as e:
            logger.error(
                "financial_threads:get_recent:error",
                extra={"thread_id": thread_id, "error": str(e)},
                exc_info=True,
            )
            raise


    async def update_thread_status(
        self,
        thread_id: int,
        new_status: FinancialThreadStatus,
    ) -> bool:
        sql = """
        UPDATE financial_threads
        SET status = $2, last_activity_at = NOW()
        WHERE id = $1
        RETURNING id
        """
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                result = await conn.fetchval(sql, thread_id, new_status.value)
            
            success = result is not None
            if success:
                logger.info(
                    "financial_threads:update_status:success",
                    extra={"thread_id": thread_id, "new_status": new_status.value},
                )
            return success
            
        except Exception as e:
            logger.error(
                "financial_threads:update_status:error",
                extra={"thread_id": thread_id, "error": str(e)},
                exc_info=True,
            )
            raise

    async def expire_old_threads(self, hours: int = 48) -> int:
        cutoff = datetime.utcnow() - timedelta(hours=hours)
        
        sql = """
        UPDATE financial_threads
        SET status = $1
        WHERE status = $2 AND last_activity_at < $3
        """
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                result = await conn.execute(
                    sql,
                    FinancialThreadStatus.EXPIRED.value,
                    FinancialThreadStatus.OPEN.value,
                    cutoff,
                )
            
            count = int(result.split()[-1]) if result else 0
            
            if count > 0:
                logger.info(
                    "financial_threads:expire:success",
                    extra={"count": count, "hours": hours},
                )
            
            return count
            
        except Exception as e:
            logger.error(
                "financial_threads:expire:error",
                extra={"hours": hours, "error": str(e)},
                exc_info=True,
            )
            raise


    async def get_open_count_for_creator(self, creator_id: str) -> int:
        sql = """
        SELECT COUNT(*) FROM financial_threads
        WHERE creator_id = $1 AND status = $2
        """
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                count = await conn.fetchval(
                    sql, creator_id, FinancialThreadStatus.OPEN.value
                )
            return count or 0
        except Exception as e:
            logger.error(
                "financial_threads:get_open_count:error",
                extra={"creator_id": creator_id, "error": str(e)},
                exc_info=True,
            )
            return 0

    async def get_waiting_for_creator_count(self, creator_id: str) -> int:
        sql = """
        SELECT COUNT(*) FROM financial_threads
        WHERE creator_id = $1 AND status = $2 AND waiting_for = $3
        """
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                count = await conn.fetchval(
                    sql,
                    creator_id,
                    FinancialThreadStatus.OPEN.value,
                    WaitingFor.CREATOR.value,
                )
            return count or 0
        except Exception as e:
            logger.error(
                "financial_threads:get_waiting_count:error",
                extra={"creator_id": creator_id, "error": str(e)},
                exc_info=True,
            )
            return 0


    def _row_to_thread(self, row: asyncpg.Record) -> FinancialThread:
        return FinancialThread(
            id=row["id"],
            sender_id=row["sender_id"],
            creator_id=row["creator_id"],
            conversation_id=row["conversation_id"],
            status=FinancialThreadStatus(row["status"]),
            waiting_for=WaitingFor(row["waiting_for"]),
            topic_summary=row["topic_summary"],
            last_sender_message=row["last_sender_message"],
            last_creator_response=row["last_creator_response"],
            created_at=row["created_at"],
            last_activity_at=row["last_activity_at"],
        )

    def _row_to_message(self, row: asyncpg.Record) -> FinancialThreadMessage:
        return FinancialThreadMessage(
            id=row["id"],
            thread_id=row["thread_id"],
            author_type=row["author_type"],
            message=row["message"],
            delivered=row["delivered"],
            created_at=row["created_at"],
        )
