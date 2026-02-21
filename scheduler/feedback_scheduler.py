
from __future__ import annotations

import asyncio
import logging
from datetime import datetime, timedelta
from typing import Any, Dict, List, Optional

from config.settings import Settings
from service.relationship_feedback_service import (
    RelationshipFeedbackService,
    MAX_QUESTIONS_PER_DAY,
)
from db.postgres_relationship_cluster_personas import (
    RelationshipClusterPersonas,
)
from db.passive_archive_storage import (
    PassiveArchiveStorage,
)

logger = logging.getLogger(__name__)

DEFAULT_CONFIDENCE_THRESHOLD = 0.6


class FeedbackScheduler:

    DEFAULT_INTERVAL_SECONDS = 8 * 60 * 60

    def __init__(
        self,
        feedback_service: RelationshipFeedbackService,
        relationship_cluster: RelationshipClusterPersonas,
        archive_storage: PassiveArchiveStorage,
        settings: Optional[Settings] = None,
    ) -> None:
        self._feedback = feedback_service
        self._rel_cluster = relationship_cluster
        self._archive = archive_storage
        self._settings = settings or Settings()
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        self._interval = getattr(
            self._settings, 
            "FEEDBACK_SCHEDULER_INTERVAL_SECONDS", 
            self.DEFAULT_INTERVAL_SECONDS
        )
        
        self._min_confidence_threshold = getattr(
            self._settings,
            "FEEDBACK_MIN_CONFIDENCE_THRESHOLD",
            DEFAULT_CONFIDENCE_THRESHOLD
        )

    async def start(self) -> None:
        if self._running:
            logger.warning("feedback_scheduler:already_running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"feedback_scheduler:started:interval={self._interval}s")

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("feedback_scheduler:stopped")

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._interval)
                logger.info("feedback_scheduler:scheduled_run:start")
                stats = await self.run_once()
                logger.info(
                    f"feedback_scheduler:scheduled_run:complete:"
                    f"created={stats.get('questions_created', 0)},"
                    f"retried={stats.get('questions_retried', 0)},"
                    f"expired={stats.get('questions_expired', 0)}"
                )
            except asyncio.CancelledError:
                logger.info("feedback_scheduler:scheduled_run:cancelled")
                break
            except Exception as e:
                logger.error(f"feedback_scheduler:scheduled_run:error:{e}", exc_info=True)

    async def run_once(self) -> Dict[str, int]:
        stats = {
            "questions_created": 0,
            "questions_retried": 0,
            "questions_expired": 0,
            "users_checked": 0,
            "users_processed": 0,
            "skipped_high_confidence": 0,
            "errors": 0,
        }
        
        logger.info(
            f"feedback_scheduler:run_once:start:threshold={self._min_confidence_threshold}"
        )
        
        try:
            users_with_low_confidence = await self._get_users_with_low_confidence()
            
            for user_id in users_with_low_confidence:
                try:
                    stats["users_checked"] += 1
                    questions_before = stats["questions_created"]
                    await self._process_user(user_id, stats)
                    if stats["questions_created"] > questions_before:
                        stats["users_processed"] += 1
                except Exception as e:
                    logger.error(f"feedback_scheduler:user_error:{user_id}:{e}")
                    stats["errors"] += 1
            
            await self._retry_pending_questions(stats)
            
            expired = await self._feedback.expire_old_questions()
            stats["questions_expired"] = expired
            
        except Exception as e:
            logger.error(f"feedback_scheduler:run_once:error:{e}", exc_info=True)
            stats["errors"] += 1
        
        logger.info(f"feedback_scheduler:run_once:done:{stats}")
        return stats

    async def _get_users_with_low_confidence(self) -> List[str]:
        return await self._rel_cluster.get_users_with_low_confidence_members(
            threshold=self._min_confidence_threshold
        )

    async def _process_user(
        self,
        user_id: str,
        stats: Dict[str, int],
    ) -> None:
        
        if not await self._feedback.can_ask_today(user_id):
            logger.debug(f"feedback_scheduler:skip_user:daily_limit:{user_id}")
            return
        
        low_confidence_members = await self._rel_cluster.get_all_members_below_confidence(
            user_id, threshold=self._min_confidence_threshold
        )
        
        for member_data in low_confidence_members:
            member_user_id = member_data["member_user_id"]
            cluster_name = member_data["cluster_name"]
            confidence = member_data["confidence"]
            
            if await self._feedback.should_never_ask(user_id, member_user_id):
                continue
            
            if await self._feedback.is_relationship_confirmed(user_id, member_user_id):
                continue
            
            if not await self._feedback.can_ask_today(user_id):
                break
            
            summary, sample_messages = await self._create_conversation_summary(
                user_id, member_user_id
            )
            
            if not summary:
                continue
            
            question = await self._feedback.create_question(
                asking_user_id=user_id,
                about_user_id=member_user_id,
                conversation_summary=summary,
                sample_messages=sample_messages,
            )
            
            if question:
                stats["questions_created"] += 1
                logger.info(
                    f"feedback_scheduler:question_created:{user_id}->{member_user_id}:"
                    f"cluster={cluster_name},confidence={confidence:.2f}"
                )

    async def _create_conversation_summary(
        self,
        user_a: str,
        user_b: str,
    ) -> tuple[str, List[str]]:
        messages = await self._archive.get_messages_for_pair(user_a, user_b, limit=50)
        
        if not messages:
            return "", []
        
        sample_messages = []
        for msg in messages[:14]:
            sender = "شما" if msg.user_id == user_a else msg.user_id
            sample_messages.append(f"{sender}: {msg.message[:300]}...")
        
        total_count = len(messages)
        summary = f"شما {total_count} پیام با این کاربر رد و بدل کرده‌اید."
        
        if sample_messages:
            summary += "\n\nنمونه پیام‌ها:\n" + "\n".join(sample_messages)
        
        return summary, sample_messages

    async def _retry_pending_questions(self, stats: Dict[str, int]) -> None:
        questions = await self._feedback.get_questions_needing_retry(limit=20)
        
        for question in questions:
            try:
                if not await self._feedback.can_ask_today(question.asking_user_id):
                    continue
                
                await self._feedback.mark_retry_sent(question.id)
                stats["questions_retried"] += 1
                
                logger.info(
                    f"feedback_scheduler:retry_sent:{question.asking_user_id}->"
                    f"{question.about_user_id}, count={question.sent_count + 1}"
                )
                
            except Exception as e:
                logger.error(f"feedback_scheduler:retry_error:{question.id}:{e}")
                stats["errors"] += 1


async def run_feedback_scheduler_standalone() -> None:
    from config.settings import Settings
    
    settings = Settings()
    
    feedback = RelationshipFeedbackService(dsn=settings.postgres_url)
    rel_cluster = RelationshipClusterPersonas(dsn=settings.postgres_url)
    archive = PassiveArchiveStorage(dsn=settings.postgres_url)
    
    scheduler = FeedbackScheduler(
        feedback_service=feedback,
        relationship_cluster=rel_cluster,
        archive_storage=archive,
        settings=settings,
    )
    
    stats = await scheduler.run_once()
    print(f"Stats: {stats}")
    
    await feedback.close()
    await rel_cluster.close()
    await archive.close()


if __name__ == "__main__":
    asyncio.run(run_feedback_scheduler_standalone())
