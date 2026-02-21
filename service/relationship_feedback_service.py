
from __future__ import annotations

import hashlib
import logging
from dataclasses import dataclass
from datetime import datetime, timedelta
from typing import List, Optional, Dict, Any, Tuple, TYPE_CHECKING

import asyncpg

if TYPE_CHECKING:
    from config.settings import Settings

logger = logging.getLogger(__name__)

VALID_RELATIONSHIP_CLASSES = {"spouse", "family", "boss", "subordinate", "colleague", "friend", "stranger"}

DEFAULT_MAX_QUESTIONS_PER_WINDOW = 3
DEFAULT_QUESTION_WINDOW_SECONDS = 86400
DEFAULT_RETRY_AFTER_SECONDS = 172800
DEFAULT_MAX_RETRIES = 2

MAX_QUESTIONS_PER_DAY = DEFAULT_MAX_QUESTIONS_PER_WINDOW
MAX_QUESTIONS_PER_WINDOW = DEFAULT_MAX_QUESTIONS_PER_WINDOW
QUESTION_WINDOW_SECONDS = DEFAULT_QUESTION_WINDOW_SECONDS
RETRY_AFTER_SECONDS = DEFAULT_RETRY_AFTER_SECONDS
MAX_RETRIES = DEFAULT_MAX_RETRIES


def compute_pair_id(user_a: str, user_b: str) -> str:
    lo, hi = sorted([(user_a or "").strip(), (user_b or "").strip()])
    digest = hashlib.sha256(f"{lo}::{hi}".encode("utf-8")).hexdigest()
    return digest[:16]


@dataclass
class FeedbackQuestion:
    id: int
    asking_user_id: str
    about_user_id: str
    pair_id: str
    conversation_summary: str
    sample_messages: List[str]
    status: str
    question_text: str
    answer_relationship_class: Optional[str]
    answer_text: Optional[str]
    answered_at: Optional[datetime]
    sent_count: int
    last_sent_at: datetime
    next_retry_at: Optional[datetime]
    never_ask_again: bool
    created_at: datetime
    updated_at: datetime


@dataclass
class ConfirmedRelationship:
    id: int
    user_id: str
    related_user_id: str
    relationship_class: str
    confirmed_by: str
    confirmed_at: datetime
    is_locked: bool


class RelationshipFeedbackService:

    QUESTION_TEMPLATE = """سلام! 👋

می‌خواستم بپرسم که رابطه‌تان با «{about_user}» چیست؟

برای کمک به یادآوری، خلاصه‌ای از صحبت‌هایتان:
{summary}

لطفاً یکی از گزینه‌های زیر را انتخاب کنید:
• همسر 💑
• خانواده 👨‍👩‍👧‍👦
• رئیس/معلم 👔
• کارمند/شاگرد 👨‍🎓
• همکار 💼
• دوست 🤝
• غریبه 😶

با تشکر از همکاری شما! 🙏"""

    def __init__(self, dsn: str, settings: Optional["Settings"] = None) -> None:
        self._dsn = dsn
        self._pool: Optional[asyncpg.Pool] = None
        
        if settings:
            self._max_questions_per_window = getattr(
                settings, "FEEDBACK_MAX_QUESTIONS_PER_WINDOW", DEFAULT_MAX_QUESTIONS_PER_WINDOW
            )
            self._question_window_seconds = getattr(
                settings, "FEEDBACK_QUESTION_WINDOW_SECONDS", DEFAULT_QUESTION_WINDOW_SECONDS
            )
            self._retry_after_seconds = getattr(
                settings, "FEEDBACK_RETRY_AFTER_SECONDS", DEFAULT_RETRY_AFTER_SECONDS
            )
            self._max_retries = getattr(
                settings, "FEEDBACK_MAX_RETRIES", DEFAULT_MAX_RETRIES
            )
        else:
            self._max_questions_per_window = DEFAULT_MAX_QUESTIONS_PER_WINDOW
            self._question_window_seconds = DEFAULT_QUESTION_WINDOW_SECONDS
            self._retry_after_seconds = DEFAULT_RETRY_AFTER_SECONDS
            self._max_retries = DEFAULT_MAX_RETRIES

    async def close(self) -> None:
        if self._pool is not None:
            await self._pool.close()
            self._pool = None

    async def _require_pool(self) -> asyncpg.Pool:
        if self._pool is None:
            pool = await asyncpg.create_pool(self._dsn, min_size=1, max_size=5)
            if pool is None:
                raise RuntimeError("Failed to create connection pool")
            self._pool = pool
        return self._pool


    async def can_ask_in_window(self, user_id: str) -> bool:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS count
                FROM relationship_feedback_questions
                WHERE asking_user_id = $1
                  AND status = 'pending'
                  AND created_at > NOW() - INTERVAL '1 second' * $2
                """,
                user_id,
                self._question_window_seconds,
            )
        
        if not row:
            return True
        
        return row["count"] < self._max_questions_per_window

    async def can_ask_today(self, user_id: str) -> bool:
        return await self.can_ask_in_window(user_id)

    async def get_questions_count_in_window(self, user_id: str) -> int:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT COUNT(*) AS count
                FROM relationship_feedback_questions
                WHERE asking_user_id = $1
                  AND status = 'pending'
                  AND created_at > NOW() - INTERVAL '1 second' * $2
                """,
                user_id,
                self._question_window_seconds,
            )
        
        return row["count"] if row else 0

    async def get_remaining_questions_in_window(self, user_id: str) -> int:
        count = await self.get_questions_count_in_window(user_id)
        return max(0, self._max_questions_per_window - count)

    async def _increment_daily_count(self, user_id: str) -> None:
        pass

    async def is_relationship_confirmed(self, user_id: str, related_user_id: str) -> bool:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT id FROM confirmed_relationships
                WHERE user_id = $1 AND related_user_id = $2
                """,
                user_id,
                related_user_id,
            )
        
        return row is not None

    async def should_never_ask(self, asking_user_id: str, about_user_id: str) -> bool:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT never_ask_again
                FROM relationship_feedback_questions
                WHERE asking_user_id = $1 AND about_user_id = $2
                """,
                asking_user_id,
                about_user_id,
            )
        
        if not row:
            return False
        
        return row["never_ask_again"]


    async def create_question(
        self,
        asking_user_id: str,
        about_user_id: str,
        conversation_summary: str,
        sample_messages: Optional[List[str]] = None,
    ) -> Optional[FeedbackQuestion]:
        if not await self.can_ask_today(asking_user_id):
            logger.info(f"feedback:create:daily_limit_reached:{asking_user_id}")
            return None
        
        if await self.is_relationship_confirmed(asking_user_id, about_user_id):
            logger.info(f"feedback:create:already_confirmed:{asking_user_id}->{about_user_id}")
            return None
        
        if await self.should_never_ask(asking_user_id, about_user_id):
            logger.info(f"feedback:create:never_ask_again:{asking_user_id}->{about_user_id}")
            return None
        
        pool = await self._require_pool()
        pair_id = compute_pair_id(asking_user_id, about_user_id)
        
        question_text = self.QUESTION_TEMPLATE.format(
            about_user=about_user_id,
            summary=conversation_summary,
        )
        
        next_retry = datetime.utcnow() + timedelta(seconds=self._retry_after_seconds)
        
        async with pool.acquire() as conn:
            try:
                row = await conn.fetchrow(
                    """
                    INSERT INTO relationship_feedback_questions
                        (asking_user_id, about_user_id, pair_id,
                         conversation_summary, sample_messages,
                         question_text, next_retry_at)
                    VALUES ($1, $2, $3, $4, $5, $6, $7)
                    ON CONFLICT (asking_user_id, about_user_id) DO UPDATE
                        SET conversation_summary = EXCLUDED.conversation_summary,
                            sample_messages = EXCLUDED.sample_messages,
                            question_text = EXCLUDED.question_text,
                            sent_count = relationship_feedback_questions.sent_count + 1,
                            last_sent_at = NOW(),
                            next_retry_at = EXCLUDED.next_retry_at,
                            updated_at = NOW()
                    RETURNING *
                    """,
                    asking_user_id,
                    about_user_id,
                    pair_id,
                    conversation_summary,
                    sample_messages or [],
                    question_text,
                    next_retry,
                )
                
                if not row:
                    return None
                
                await self._increment_daily_count(asking_user_id)
                
                logger.info(
                    f"feedback:create:success:{asking_user_id}->{about_user_id}, "
                    f"sent_count={row['sent_count']}"
                )
                
                return self._row_to_question(row)
                
            except Exception as e:
                logger.error(f"feedback:create:error:{e}", exc_info=True)
                return None


    async def get_pending_questions(
        self,
        user_id: str,
        include_unread_only: bool = False,
    ) -> List[FeedbackQuestion]:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM relationship_feedback_questions
                WHERE asking_user_id = $1
                  AND status = 'pending'
                ORDER BY created_at DESC
                """,
                user_id,
            )
        
        return [self._row_to_question(row) for row in rows]

    async def get_question_by_id(self, question_id: int) -> Optional[FeedbackQuestion]:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM relationship_feedback_questions
                WHERE id = $1
                """,
                question_id,
            )
        
        if not row:
            return None
        
        return self._row_to_question(row)

    async def has_unread_questions(self, user_id: str) -> bool:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            count = await conn.fetchval(
                """
                SELECT COUNT(*) FROM relationship_feedback_questions
                WHERE asking_user_id = $1
                  AND status = 'pending'
                """,
                user_id,
            )
        
        return int(count or 0) > 0


    async def submit_answer(
        self,
        question_id: int,
        relationship_class: str,
        answer_text: Optional[str] = None,
    ) -> Tuple[bool, str]:
        relationship_class = relationship_class.lower().strip()
        if relationship_class not in VALID_RELATIONSHIP_CLASSES:
            return False, f"کلاس رابطه نامعتبر: {relationship_class}"
        
        question = await self.get_question_by_id(question_id)
        if not question:
            return False, "سوال یافت نشد"
        
        if question.status != "pending":
            return False, "این سوال قبلاً پاسخ داده شده"
        
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            async with conn.transaction():
                if relationship_class == "stranger":
                    await conn.execute(
                        """
                        UPDATE relationship_feedback_questions
                        SET status = 'answered',
                            answer_relationship_class = $2,
                            answer_text = $3,
                            answered_at = NOW(),
                            updated_at = NOW()
                        WHERE id = $1
                        """,
                        question_id,
                        relationship_class,
                        answer_text,
                    )
                    
                    await conn.execute(
                        """
                        UPDATE relationship_feedback_questions
                        SET never_ask_again = TRUE, updated_at = NOW()
                        WHERE asking_user_id = $1 AND about_user_id = $2
                        """,
                        question.asking_user_id,
                        question.about_user_id,
                    )
                    
                    await conn.execute(
                        """
                        INSERT INTO confirmed_relationships
                            (user_id, related_user_id, relationship_class, confirmed_by)
                        VALUES ($1, $2, 'stranger', $3)
                        ON CONFLICT (user_id, related_user_id) DO UPDATE
                            SET relationship_class = 'stranger',
                                confirmed_at = NOW()
                        """,
                        question.about_user_id,
                        question.asking_user_id,
                        question.asking_user_id,
                    )
                    
                    logger.info(
                        f"feedback:answer:confirmed_stranger:{question.asking_user_id}->"
                        f"{question.about_user_id}"
                    )
                    
                    return True, "رابطه غریبه تأیید شد. دیگر سوالی پرسیده نمی‌شود. ✅"
                
                await conn.execute(
                    """
                    UPDATE relationship_feedback_questions
                    SET status = 'answered',
                        answer_relationship_class = $2,
                        answer_text = $3,
                        answered_at = NOW(),
                        updated_at = NOW()
                    WHERE id = $1
                    """,
                    question_id,
                    relationship_class,
                    answer_text,
                )
                
                await conn.execute(
                    """
                    INSERT INTO confirmed_relationships
                        (user_id, related_user_id, relationship_class, confirmed_by)
                    VALUES ($1, $2, $3, $1)
                    ON CONFLICT (user_id, related_user_id) DO UPDATE
                        SET relationship_class = EXCLUDED.relationship_class,
                            confirmed_at = NOW()
                    """,
                    question.asking_user_id,
                    question.about_user_id,
                    relationship_class,
                )
                
                await conn.execute(
                    """
                    INSERT INTO confirmed_relationships
                        (user_id, related_user_id, relationship_class, confirmed_by)
                    VALUES ($1, $2, $3, $4)
                    ON CONFLICT (user_id, related_user_id) DO UPDATE
                        SET relationship_class = EXCLUDED.relationship_class,
                            confirmed_at = NOW()
                    """,
                    question.about_user_id,
                    question.asking_user_id,
                    relationship_class,
                    question.asking_user_id,
                )
        
        logger.info(
            f"feedback:answer:success:{question.asking_user_id}->{question.about_user_id}="
            f"{relationship_class}"
        )
        
        return True, "رابطه با موفقیت ثبت شد! 🎉"

    async def skip_question(self, question_id: int) -> Tuple[bool, str]:
        question = await self.get_question_by_id(question_id)
        if not question:
            return False, "سوال یافت نشد"
        
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE relationship_feedback_questions
                SET never_ask_again = TRUE, status = 'skipped', updated_at = NOW()
                WHERE id = $1
                """,
                question_id,
            )
        
        logger.info(
            f"feedback:skip:{question.asking_user_id}->{question.about_user_id}"
        )
        
        return True, "سوال رد شد و دیگر پرسیده نمی‌شود"


    async def get_questions_needing_retry(self, limit: int = 50) -> List[FeedbackQuestion]:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            rows = await conn.fetch(
                """
                SELECT * FROM relationship_feedback_questions
                WHERE status = 'pending'
                  AND next_retry_at <= NOW()
                  AND sent_count < $1
                  AND never_ask_again = FALSE
                ORDER BY next_retry_at ASC
                LIMIT $2
                """,
                self._max_retries,
                limit,
            )
        
        return [self._row_to_question(row) for row in rows]

    async def mark_retry_sent(self, question_id: int) -> None:
        pool = await self._require_pool()
        next_retry = datetime.utcnow() + timedelta(seconds=self._retry_after_seconds)
        
        async with pool.acquire() as conn:
            await conn.execute(
                """
                UPDATE relationship_feedback_questions
                SET sent_count = sent_count + 1,
                    last_sent_at = NOW(),
                    next_retry_at = $2,
                    updated_at = NOW()
                WHERE id = $1
                """,
                question_id,
                next_retry,
            )

    async def expire_old_questions(self) -> int:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            result = await conn.execute(
                """
                UPDATE relationship_feedback_questions
                SET status = 'expired', updated_at = NOW()
                WHERE status = 'pending'
                  AND sent_count >= $1
                  AND next_retry_at < NOW()
                """,
                self._max_retries,
            )
        
        count = int(result.split()[-1]) if result else 0
        
        if count > 0:
            logger.info(f"feedback:expire:expired {count} questions")
        
        return count


    async def apply_to_cluster_and_dyadic(
        self,
        user_id: str,
        related_user_id: str,
        relationship_class: str,
        rel_cluster: Any,
        dyadic: Any,
    ) -> None:
        await rel_cluster.add_member_to_cluster(
            user_id=user_id,
            cluster_name=relationship_class,
            member_user_id=related_user_id,
            confidence=1.0,
        )
        
        await dyadic.update_relationship_class(
            source_user_id=user_id,
            target_user_id=related_user_id,
            relationship_class=relationship_class,
        )
        
        logger.info(
            f"feedback:apply_cluster_dyadic:asymmetric:{user_id}→{related_user_id}={relationship_class}:confidence=1.0"
        )


    def _row_to_question(self, row: asyncpg.Record) -> FeedbackQuestion:
        return FeedbackQuestion(
            id=row["id"],
            asking_user_id=row["asking_user_id"],
            about_user_id=row["about_user_id"],
            pair_id=row["pair_id"],
            conversation_summary=row["conversation_summary"],
            sample_messages=list(row["sample_messages"] or []),
            status=row["status"],
            question_text=row["question_text"],
            answer_relationship_class=row["answer_relationship_class"],
            answer_text=row["answer_text"],
            answered_at=row["answered_at"],
            sent_count=row["sent_count"],
            last_sent_at=row["last_sent_at"],
            next_retry_at=row["next_retry_at"],
            never_ask_again=row["never_ask_again"],
            created_at=row["created_at"],
            updated_at=row["updated_at"],
        )

    async def get_confirmed_relationship(
        self,
        user_id: str,
        related_user_id: str,
    ) -> Optional[ConfirmedRelationship]:
        pool = await self._require_pool()
        
        async with pool.acquire() as conn:
            row = await conn.fetchrow(
                """
                SELECT * FROM confirmed_relationships
                WHERE user_id = $1 AND related_user_id = $2
                """,
                user_id,
                related_user_id,
            )
        
        if not row:
            return None
        
        return ConfirmedRelationship(
            id=row["id"],
            user_id=row["user_id"],
            related_user_id=row["related_user_id"],
            relationship_class=row["relationship_class"],
            confirmed_by=row["confirmed_by"],
            confirmed_at=row["confirmed_at"],
            is_locked=row["is_locked"],
        )
