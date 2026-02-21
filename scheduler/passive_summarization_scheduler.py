
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional, TYPE_CHECKING

from config.settings import Settings
from db.passive_archive_storage import PassiveArchiveStorage, PassivePairCounter, compute_pair_id
from db.passive_summarization_storage import PassiveSummarizationStorage
from summarizer.passive_summarizer_agent import PassiveSummarizerAgent

if TYPE_CHECKING:
    from summarizer.summarizer_agent import SummarizerAgent

logger = logging.getLogger(__name__)


class PassiveSummarizationScheduler:

    DEFAULT_INTERVAL_SECONDS = 3600
    DEFAULT_FETCH_LIMIT = 50
    DEFAULT_BATCH_SIZE = 10
    DEFAULT_MIN_MESSAGES_FOR_SUMMARY = 40

    def __init__(
        self,
        settings: Settings,
        summarizer_service: PassiveSummarizerAgent,
        pair_counter: PassivePairCounter,
        archive_storage: PassiveArchiveStorage,
        retry_storage: PassiveSummarizationStorage,
        interval_seconds: int | None = None,
    ) -> None:
        self._settings = settings
        self._summarizer = summarizer_service
        self._pair_counter = pair_counter
        self._archive = archive_storage
        self._retry_storage = retry_storage
        
        self._interval = (
            interval_seconds 
            or getattr(settings, "PASSIVE_SUMMARIZATION_INTERVAL_SECONDS", self.DEFAULT_INTERVAL_SECONDS)
        )
        self._fetch_limit = getattr(
            settings, "PASSIVE_SUMMARIZATION_FETCH_LIMIT", self.DEFAULT_FETCH_LIMIT
        )
        self._batch_size = getattr(
            settings, "PASSIVE_SUMMARIZATION_BATCH_SIZE", self.DEFAULT_BATCH_SIZE
        )
        self._min_messages = getattr(
            settings, "PASSIVE_SUMMARIZATION_MIN_MESSAGES", self.DEFAULT_MIN_MESSAGES_FOR_SUMMARY
        )
        
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            logger.warning("passive_summarization_scheduler:already_running")
            return
        
        await self._retry_storage.ensure_tables()
        
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            f"passive_summarization_scheduler:started:interval={self._interval}s,"
            f"fetch_limit={self._fetch_limit},batch_size={self._batch_size},"
            f"min_messages={self._min_messages}"
        )

    async def stop(self) -> None:
        if not self._running:
            return
        
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info("passive_summarization_scheduler:stopped")

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._interval)
                logger.info("passive_summarization_scheduler:scheduled_run:start")
                stats = await self.process_batch()
                logger.info(
                    f"passive_summarization_scheduler:scheduled_run:complete:"
                    f"processed={stats.get('pairs_processed', 0)},"
                    f"success={stats.get('success', 0)},"
                    f"failed={stats.get('failed', 0)},"
                    f"skipped={stats.get('skipped', 0)}"
                )
            except asyncio.CancelledError:
                logger.info("passive_summarization_scheduler:cancelled")
                break
            except Exception as e:
                logger.error(f"passive_summarization_scheduler:error:{e}", exc_info=True)

    async def process_batch(self) -> Dict[str, Any]:
        stats = {
            "pairs_fetched": 0,
            "pairs_processed": 0,
            "batches_processed": 0,
            "success": 0,
            "failed": 0,
            "skipped": 0,
            "sent_to_retry": 0,
            "errors": 0,
        }
        
        try:
            pairs = await self._get_pairs_needing_summarization()
            stats["pairs_fetched"] = len(pairs)
            
            if not pairs:
                logger.info("passive_summarization_scheduler:no_pairs_to_process")
                return stats
            
            logger.info(
                f"passive_summarization_scheduler:found:{len(pairs)} pairs, "
                f"processing in batches of {self._batch_size}"
            )
            
            for batch_idx in range(0, len(pairs), self._batch_size):
                batch = pairs[batch_idx:batch_idx + self._batch_size]
                stats["batches_processed"] += 1
                
                logger.info(
                    f"passive_summarization_scheduler:batch:{stats['batches_processed']}:"
                    f"processing {len(batch)} pairs"
                )
                
                for pair in batch:
                    try:
                        result = await self._process_pair(pair)
                        stats["pairs_processed"] += 1
                        
                        if result["success"]:
                            stats["success"] += 1
                        elif result.get("skipped"):
                            stats["skipped"] += 1
                        else:
                            stats["failed"] += 1
                            stats["sent_to_retry"] += 1
                            
                    except Exception as e:
                        logger.error(
                            f"passive_summarization_scheduler:pair_error:{pair}:{e}",
                            exc_info=True,
                        )
                        stats["errors"] += 1
                
                logger.info(
                    f"passive_summarization_scheduler:batch:{stats['batches_processed']}:done:"
                    f"success={stats['success']},failed={stats['failed']}"
                )
            
            return stats
            
        except Exception as e:
            logger.error(f"passive_summarization_scheduler:batch_error:{e}", exc_info=True)
            stats["errors"] += 1
            return stats

    async def _get_pairs_needing_summarization(self) -> List[Dict[str, Any]]:
        pairs = await self._pair_counter.get_all_pairs(
            min_messages=self._min_messages,
            limit=self._fetch_limit,
        )
        
        return [
            {
                "user_a": p.user_a,
                "user_b": p.user_b,
                "pair_id": p.pair_id,
                "message_count": p.total_archived_count,
            }
            for p in pairs
        ]

    async def _process_pair(self, pair: Dict[str, Any]) -> Dict[str, Any]:
        user_a = pair["user_a"]
        user_b = pair["user_b"]
        pair_id = pair["pair_id"]
        
        logger.info(f"passive_summarization_scheduler:processing:{pair_id}")
        
        result = await self._summarizer.summarize_pair(
            user_a=user_a,
            user_b=user_b,
            delete_after_success=False,
        )
        
        if result.success:
            logger.info(
                f"passive_summarization_scheduler:success:{pair_id}",
                extra={
                    "summary_id": result.summary_id,
                    "message_count": result.message_count,
                },
            )
            return {"success": True}
        
        if result.error and "Insufficient messages" in result.error:
            logger.info(f"passive_summarization_scheduler:skip:{pair_id}:{result.error}")
            return {"success": False, "skipped": True}
        
        await self._retry_storage.enqueue_retry(
            conversation_id=result.conversation_id,
            pair_id=pair_id,
            user_a=user_a,
            user_b=user_b,
            message_ids=[],
            last_error=result.error,
        )
        
        logger.warning(
            f"passive_summarization_scheduler:sent_to_retry:{pair_id}",
            extra={"error": result.error},
        )
        return {"success": False}

    async def trigger_manual(
        self,
        user_a: str | None = None,
        user_b: str | None = None,
    ) -> Dict[str, Any]:
        if user_a and user_b:
            result = await self._summarizer.summarize_pair(
                user_a=user_a,
                user_b=user_b,
                delete_after_success=False,
            )
            return {
                "success": result.success,
                "pair_id": result.pair_id,
                "summary_id": result.summary_id,
                "message_count": result.message_count,
                "error": result.error,
            }
        else:
            return await self.process_batch()


class PassiveSummarizationRetryWorker:

    DEFAULT_INTERVAL_SECONDS = 300

    def __init__(
        self,
        settings: Settings,
        summarizer_service: PassiveSummarizerAgent,
        retry_storage: PassiveSummarizationStorage,
        archive_storage: PassiveArchiveStorage,
        interval_seconds: int | None = None,
    ) -> None:
        self._settings = settings
        self._summarizer = summarizer_service
        self._retry_storage = retry_storage
        self._archive = archive_storage
        
        self._interval = (
            interval_seconds
            or getattr(settings, "PASSIVE_SUMMARIZATION_RETRY_INTERVAL_SECONDS", self.DEFAULT_INTERVAL_SECONDS)
        )
        
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            logger.warning("passive_summarization_retry_worker:already_running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"passive_summarization_retry_worker:started:interval={self._interval}s")

    async def stop(self) -> None:
        if not self._running:
            return
        
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        
        logger.info("passive_summarization_retry_worker:stopped")

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._interval)
                logger.info("passive_summarization_retry_worker:run:start")
                stats = await self.process_retries()
                logger.info(
                    f"passive_summarization_retry_worker:run:complete:"
                    f"processed={stats.get('processed', 0)},"
                    f"success={stats.get('success', 0)},"
                    f"failed={stats.get('failed', 0)},"
                    f"moved_to_failed={stats.get('moved_to_failed', 0)}"
                )
            except asyncio.CancelledError:
                logger.info("passive_summarization_retry_worker:cancelled")
                break
            except Exception as e:
                logger.error(f"passive_summarization_retry_worker:error:{e}", exc_info=True)

    async def process_retries(self) -> Dict[str, Any]:
        stats = {
            "processed": 0,
            "success": 0,
            "failed": 0,
            "moved_to_failed": 0,
            "errors": 0,
        }
        
        try:
            jobs = await self._retry_storage.get_pending_retries(limit=10)
            
            if not jobs:
                logger.debug("passive_summarization_retry_worker:no_pending_jobs")
                return stats
            
            logger.info(f"passive_summarization_retry_worker:found:{len(jobs)} jobs")
            
            for job in jobs:
                try:
                    stats["processed"] += 1
                    success = await self._process_retry_job(job)
                    
                    if success:
                        stats["success"] += 1
                    else:
                        can_retry = await self._retry_storage.update_retry_attempt(
                            retry_id=job.id,
                            last_error="Retry failed",
                        )
                        if not can_retry:
                            stats["moved_to_failed"] += 1
                            await self._mark_messages_as_deleted(job.user_a, job.user_b)
                        else:
                            stats["failed"] += 1
                            
                except Exception as e:
                    logger.error(
                        f"passive_summarization_retry_worker:job_error:{job.id}:{e}",
                        exc_info=True,
                    )
                    stats["errors"] += 1
            
            return stats
            
        except Exception as e:
            logger.error(f"passive_summarization_retry_worker:batch_error:{e}", exc_info=True)
            stats["errors"] += 1
            return stats

    async def _process_retry_job(self, job) -> bool:
        logger.info(
            f"passive_summarization_retry_worker:processing:{job.id}",
            extra={
                "pair_id": job.pair_id,
                "attempt": job.attempt_count + 1,
            },
        )
        
        result = await self._summarizer.summarize_pair(
            user_a=job.user_a,
            user_b=job.user_b,
            delete_after_success=False,
        )
        
        if result.success:
            await self._retry_storage.remove_retry(job.id)
            
            logger.info(
                f"passive_summarization_retry_worker:success:{job.id}",
                extra={"summary_id": result.summary_id},
            )
            return True
        
        logger.warning(
            f"passive_summarization_retry_worker:failed:{job.id}",
            extra={"error": result.error},
        )
        return False

    async def _mark_messages_as_deleted(self, user_a: str, user_b: str) -> int:
        deleted_count = await self._archive.mark_as_deleted(user_a, user_b)
        logger.info(
            f"passive_summarization_retry_worker:soft_deleted:{user_a}↔{user_b}",
            extra={"deleted_count": deleted_count},
        )
        return deleted_count


def create_passive_summarization_scheduler(
    settings: Settings,
    summarizer_service: PassiveSummarizerAgent,
    pair_counter: PassivePairCounter,
    archive_storage: PassiveArchiveStorage,
    retry_storage: PassiveSummarizationStorage,
) -> PassiveSummarizationScheduler:
    return PassiveSummarizationScheduler(
        settings=settings,
        summarizer_service=summarizer_service,
        pair_counter=pair_counter,
        archive_storage=archive_storage,
        retry_storage=retry_storage,
    )


def create_passive_summarization_retry_worker(
    settings: Settings,
    summarizer_service: PassiveSummarizerAgent,
    retry_storage: PassiveSummarizationStorage,
    archive_storage: PassiveArchiveStorage,
) -> PassiveSummarizationRetryWorker:
    return PassiveSummarizationRetryWorker(
        settings=settings,
        summarizer_service=summarizer_service,
        retry_storage=retry_storage,
        archive_storage=archive_storage,
    )
