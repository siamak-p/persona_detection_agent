
from __future__ import annotations

import logging
from dataclasses import dataclass
from datetime import datetime
from enum import Enum
from typing import List, Optional, TYPE_CHECKING

import asyncpg

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class FutureRequestStatus(str, Enum):
    PENDING = "pending"
    ANSWERED = "answered"
    DELIVERED = "delivered"
    EXPIRED = "expired"
    CANCELLED = "cancelled"


@dataclass
class FutureRequest:
    id: int
    sender_id: str
    recipient_id: str
    conversation_id: str
    original_message: str
    detected_plan: str
    detected_datetime: Optional[str]
    status: FutureRequestStatus
    creator_response: Optional[str]
    responded_at: Optional[datetime]
    delivered_at: Optional[datetime]
    created_at: datetime
    updated_at: datetime


CREATE_TABLE_SQL = """
CREATE TABLE IF NOT EXISTS future_requests (
    id SERIAL PRIMARY KEY,
    sender_id VARCHAR(255) NOT NULL,
    recipient_id VARCHAR(255) NOT NULL,
    conversation_id VARCHAR(255) NOT NULL,
    original_message TEXT NOT NULL,
    detected_plan TEXT NOT NULL,
    detected_datetime VARCHAR(255),
    status VARCHAR(50) NOT NULL DEFAULT 'pending',
    creator_response TEXT,
    responded_at TIMESTAMPTZ,
    delivered_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
    updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_future_requests_recipient_status 
    ON future_requests(recipient_id, status);
CREATE INDEX IF NOT EXISTS idx_future_requests_sender_status 
    ON future_requests(sender_id, status);
CREATE INDEX IF NOT EXISTS idx_future_requests_status 
    ON future_requests(status);
CREATE INDEX IF NOT EXISTS idx_future_requests_conversation_id 
    ON future_requests(conversation_id);
"""


class PostgresFutureRequests:

    def __init__(self, dsn: str):
        self._dsn = dsn
        logger.info("future_requests:init:success")

    async def _get_pool(self) -> asyncpg.Pool:
        from db.shared_pool import SharedPostgresPool
        return await SharedPostgresPool.get_pool(self._dsn)

    async def ensure_table(self) -> None:
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                await conn.execute(CREATE_TABLE_SQL)
            logger.info("future_requests:ensure_table:success")
        except Exception as e:
            logger.error(
                "future_requests:ensure_table:error",
                extra={"error": str(e)},
                exc_info=True,
            )
            raise


    async def create_request(
        self,
        sender_id: str,
        recipient_id: str,
        conversation_id: str,
        original_message: str,
        detected_plan: str,
        detected_datetime: Optional[str] = None,
    ) -> int:
        sql = """
        INSERT INTO future_requests 
            (sender_id, recipient_id, conversation_id, original_message, detected_plan, detected_datetime, status)
        VALUES ($1, $2, $3, $4, $5, $6, $7)
        RETURNING id
        """
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                request_id = await conn.fetchval(
                    sql,
                    sender_id,
                    recipient_id,
                    conversation_id,
                    original_message,
                    detected_plan,
                    detected_datetime,
                    FutureRequestStatus.PENDING.value,
                )
            
            logger.info(
                "future_requests:create:success",
                extra={
                    "request_id": request_id,
                    "sender_id": sender_id,
                    "recipient_id": recipient_id,
                    "conversation_id": conversation_id,
                    "detected_plan": detected_plan[:100],
                },
            )
            return request_id
            
        except Exception as e:
            logger.error(
                "future_requests:create:error",
                extra={
                    "sender_id": sender_id,
                    "recipient_id": recipient_id,
                    "error": str(e),
                },
                exc_info=True,
            )
            raise

    async def get_pending_for_creator(self, recipient_id: str) -> List[FutureRequest]:
        sql = """
        SELECT id, sender_id, recipient_id, conversation_id, original_message, detected_plan,
               detected_datetime, status, creator_response, responded_at,
               delivered_at, created_at, updated_at
        FROM future_requests
        WHERE recipient_id = $1 AND status = $2
        ORDER BY created_at DESC
        """
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(sql, recipient_id, FutureRequestStatus.PENDING.value)
            
            requests = [self._row_to_request(row) for row in rows]
            
            logger.info(
                "future_requests:get_pending:success",
                extra={
                    "recipient_id": recipient_id,
                    "count": len(requests),
                },
            )
            return requests
            
        except Exception as e:
            logger.error(
                "future_requests:get_pending:error",
                extra={"recipient_id": recipient_id, "error": str(e)},
                exc_info=True,
            )
            raise

    async def get_request_by_id(self, request_id: int) -> Optional[FutureRequest]:
        sql = """
        SELECT id, sender_id, recipient_id, conversation_id, original_message, detected_plan,
               detected_datetime, status, creator_response, responded_at,
               delivered_at, created_at, updated_at
        FROM future_requests
        WHERE id = $1
        """
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                row = await conn.fetchrow(sql, request_id)
            
            if row:
                return self._row_to_request(row)
            return None
            
        except Exception as e:
            logger.error(
                "future_requests:get_by_id:error",
                extra={"request_id": request_id, "error": str(e)},
                exc_info=True,
            )
            raise


    async def submit_creator_response(
        self,
        request_id: int,
        creator_response: str,
    ) -> bool:
        sql = """
        UPDATE future_requests
        SET creator_response = $2,
            responded_at = NOW(),
            status = $3,
            updated_at = NOW()
        WHERE id = $1 AND status = $4
        RETURNING id
        """
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                result = await conn.fetchval(
                    sql,
                    request_id,
                    creator_response,
                    FutureRequestStatus.ANSWERED.value,
                    FutureRequestStatus.PENDING.value,
                )
            
            success = result is not None
            
            if success:
                logger.info(
                    "future_requests:submit_response:success",
                    extra={
                        "request_id": request_id,
                        "response_preview": creator_response[:100],
                    },
                )
            else:
                logger.warning(
                    "future_requests:submit_response:not_found_or_not_pending",
                    extra={"request_id": request_id},
                )
            
            return success
            
        except Exception as e:
            logger.error(
                "future_requests:submit_response:error",
                extra={"request_id": request_id, "error": str(e)},
                exc_info=True,
            )
            raise


    async def get_undelivered_responses_for_sender(
        self,
        sender_id: str,
        recipient_id: str,
    ) -> List[FutureRequest]:
        sql = """
        SELECT id, sender_id, recipient_id, conversation_id, original_message, detected_plan,
               detected_datetime, status, creator_response, responded_at,
               delivered_at, created_at, updated_at
        FROM future_requests
        WHERE sender_id = $1 
          AND recipient_id = $2 
          AND status = $3
        ORDER BY responded_at ASC
        """
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(
                    sql,
                    sender_id,
                    recipient_id,
                    FutureRequestStatus.ANSWERED.value,
                )
            
            requests = [self._row_to_request(row) for row in rows]
            
            if requests:
                logger.info(
                    "future_requests:get_undelivered:found",
                    extra={
                        "sender_id": sender_id,
                        "recipient_id": recipient_id,
                        "count": len(requests),
                    },
                )
            
            return requests
            
        except Exception as e:
            logger.error(
                "future_requests:get_undelivered:error",
                extra={
                    "sender_id": sender_id,
                    "recipient_id": recipient_id,
                    "error": str(e),
                },
                exc_info=True,
            )
            raise

    async def mark_as_delivered(self, request_id: int) -> bool:
        sql = """
        UPDATE future_requests
        SET status = $2,
            delivered_at = NOW(),
            updated_at = NOW()
        WHERE id = $1 AND status = $3
        RETURNING id
        """
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                result = await conn.fetchval(
                    sql,
                    request_id,
                    FutureRequestStatus.DELIVERED.value,
                    FutureRequestStatus.ANSWERED.value,
                )
            
            success = result is not None
            
            if success:
                logger.info(
                    "future_requests:mark_delivered:success",
                    extra={"request_id": request_id},
                )
            else:
                logger.warning(
                    "future_requests:mark_delivered:not_found_or_not_answered",
                    extra={"request_id": request_id},
                )
            
            return success
            
        except Exception as e:
            logger.error(
                "future_requests:mark_delivered:error",
                extra={"request_id": request_id, "error": str(e)},
                exc_info=True,
            )
            raise

    async def mark_as_expired(self, request_id: int) -> bool:
        sql = """
        UPDATE future_requests
        SET status = $2,
            updated_at = NOW()
        WHERE id = $1 AND status = $3
        RETURNING id
        """
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                result = await conn.fetchval(
                    sql,
                    request_id,
                    FutureRequestStatus.EXPIRED.value,
                    FutureRequestStatus.PENDING.value,
                )
            
            success = result is not None
            
            if success:
                logger.info(
                    "future_requests:mark_expired:success",
                    extra={"request_id": request_id},
                )
            
            return success
            
        except Exception as e:
            logger.error(
                "future_requests:mark_expired:error",
                extra={"request_id": request_id, "error": str(e)},
                exc_info=True,
            )
            raise


    async def get_pending_count_for_creator(self, recipient_id: str) -> int:
        sql = """
        SELECT COUNT(*) FROM future_requests
        WHERE recipient_id = $1 AND status = $2
        """
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                count = await conn.fetchval(
                    sql,
                    recipient_id,
                    FutureRequestStatus.PENDING.value,
                )
            return count or 0
        except Exception as e:
            logger.error(
                "future_requests:get_pending_count:error",
                extra={"recipient_id": recipient_id, "error": str(e)},
                exc_info=True,
            )
            return 0

    async def get_requests_by_sender(
        self,
        sender_id: str,
        include_statuses: Optional[List[FutureRequestStatus]] = None,
    ) -> List[FutureRequest]:
        if include_statuses:
            status_values = [s.value for s in include_statuses]
            sql = """
            SELECT id, sender_id, recipient_id, conversation_id, original_message, detected_plan,
                   detected_datetime, status, creator_response, responded_at,
                   delivered_at, created_at, updated_at
            FROM future_requests
            WHERE sender_id = $1 AND status = ANY($2)
            ORDER BY created_at DESC
            """
            params = [sender_id, status_values]
        else:
            sql = """
            SELECT id, sender_id, recipient_id, conversation_id, original_message, detected_plan,
                   detected_datetime, status, creator_response, responded_at,
                   delivered_at, created_at, updated_at
            FROM future_requests
            WHERE sender_id = $1
            ORDER BY created_at DESC
            """
            params = [sender_id]
        
        try:
            pool = await self._get_pool()
            async with pool.acquire() as conn:
                rows = await conn.fetch(sql, *params)
            
            requests = [self._row_to_request(row) for row in rows]
            
            logger.info(
                "future_requests:get_by_sender:success",
                extra={
                    "sender_id": sender_id,
                    "count": len(requests),
                },
            )
            return requests
            
        except Exception as e:
            logger.error(
                "future_requests:get_by_sender:error",
                extra={"sender_id": sender_id, "error": str(e)},
                exc_info=True,
            )
            raise


    def _row_to_request(self, row: asyncpg.Record) -> FutureRequest:
        return FutureRequest(
            id=row["id"],
            sender_id=row["sender_id"],
            recipient_id=row["recipient_id"],
            conversation_id=row["conversation_id"],
            original_message=row["original_message"],
            detected_plan=row["detected_plan"],
            detected_datetime=row["detected_datetime"],
            status=FutureRequestStatus(row["status"]),
            creator_response=row["creator_response"],
            responded_at=row["responded_at"],
            delivered_at=row["delivered_at"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )
