
import asyncio
import logging
from datetime import datetime, timedelta
from typing import Optional, Any, Dict, List

logger = logging.getLogger(__name__)


class RetryWorker:

    DEFAULT_RETRY_DELAYS = [300, 3600, 14400]
    DEFAULT_MAX_ATTEMPTS = 3

    def __init__(
        self,
        *,
        chat_store: Any,
        listener_agent: Any,
        interval_seconds: int = 300,
        settings: Any = None,
    ):
        self._chat_store = chat_store
        self._listener = listener_agent
        self._interval = interval_seconds
        self._settings = settings
        self._running = False
        self._task: Optional[asyncio.Task] = None
        
        if settings:
            self._max_attempts = getattr(settings, "SUMMARY_RETRY_MAX_ATTEMPTS", self.DEFAULT_MAX_ATTEMPTS)
            delays_str = getattr(settings, "SUMMARY_RETRY_DELAYS_SECONDS", "300,3600,14400")
            self._retry_delays = [int(x) for x in delays_str.split(",")]
        else:
            self._max_attempts = self.DEFAULT_MAX_ATTEMPTS
            self._retry_delays = self.DEFAULT_RETRY_DELAYS

    async def start(self) -> None:
        if self._running:
            logger.warning("retry_worker:already_running")
            return

        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            "retry_worker:started",
            extra={
                "interval_seconds": self._interval,
                "max_attempts": self._max_attempts,
                "retry_delays": self._retry_delays,
            },
        )

    async def stop(self) -> None:
        self._running = False
        if self._task:
            self._task.cancel()
            try:
                await self._task
            except asyncio.CancelledError:
                pass
        logger.info("retry_worker:stopped")

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._interval)
                logger.info("summary_retry_worker:scheduled_run:start")
                stats = await self._process_pending_retries()
                logger.info(
                    f"summary_retry_worker:scheduled_run:complete:"
                    f"processed={stats.get('processed', 0)},"
                    f"succeeded={stats.get('succeeded', 0)},"
                    f"moved_to_failed={stats.get('moved_to_failed', 0)}"
                )
            except asyncio.CancelledError:
                logger.info("summary_retry_worker:scheduled_run:cancelled")
                break
            except Exception as e:
                logger.error(
                    f"summary_retry_worker:scheduled_run:error:{e}",
                    exc_info=True,
                )

    async def _process_pending_retries(self) -> Dict[str, Any]:
        stats = {
            "processed": 0,
            "succeeded": 0,
            "failed_again": 0,
            "moved_to_failed": 0,
            "errors": 0,
        }
        
        try:
            pending = await self._chat_store.get_pending_retries(limit=10)
            if not pending:
                return stats

            logger.info(
                "retry_worker:processing_retries",
                extra={"count": len(pending)},
            )

            for job in pending:
                try:
                    await self._process_single_retry(job, stats)
                    stats["processed"] += 1
                except Exception as e:
                    logger.error(
                        "retry_worker:job_failed",
                        extra={"job_id": job["id"], "error": str(e)},
                        exc_info=True,
                    )
                    stats["errors"] += 1
            
            logger.info(f"retry_worker:batch_done:{stats}")
            return stats
            
        except Exception as e:
            logger.error(
                "retry_worker:get_pending_failed",
                extra={"error": str(e)},
                exc_info=True,
            )
            stats["errors"] += 1
            return stats

    async def _process_single_retry(self, job: dict, stats: Dict[str, int]) -> None:
        job_id = job["id"]
        user_a = job["user_a"]
        user_b = job["user_b"]
        conversation_id = job["conversation_id"]
        attempt_count = job["attempt_count"]

        logger.info(
            "retry_worker:processing_job",
            extra={
                "job_id": job_id,
                "user_a": user_a,
                "user_b": user_b,
                "conversation_id": conversation_id,
                "attempt": attempt_count + 1,
            },
        )

        try:
            count = await self._chat_store.count_active(
                user_a=user_a, user_b=user_b, conversation_id=conversation_id
            )
            
            if count == 0:
                logger.info(
                    "retry_worker:no_messages_to_summarize",
                    extra={"job_id": job_id},
                )
                await self._chat_store.remove_retry(job_id)
                stats["succeeded"] += 1
                return

            await self._listener.check_and_trigger_summarization(
                memory_owner_id=user_a,
                partner_user_id=user_b,
                conversation_id=conversation_id,
            )
            
            await self._chat_store.remove_retry(job_id)
            stats["succeeded"] += 1
            logger.info(
                "retry_worker:job_completed",
                extra={"job_id": job_id},
            )

        except Exception as e:
            logger.error(
                "retry_worker:retry_failed",
                extra={"job_id": job_id, "error": str(e)},
                exc_info=True,
            )

            new_attempt = attempt_count + 1
            
            if new_attempt >= self._max_attempts:
                await self._chat_store.move_retry_to_failed(
                    retry_id=job_id,
                    last_error=str(e)[:500],
                )
                stats["moved_to_failed"] += 1
                logger.warning(
                    "retry_worker:max_attempts_reached:moved_to_failed",
                    extra={
                        "job_id": job_id,
                        "attempts": new_attempt,
                    },
                )
            else:
                delay_index = min(new_attempt, len(self._retry_delays) - 1)
                next_retry = datetime.utcnow() + timedelta(seconds=self._retry_delays[delay_index])
                
                await self._chat_store.update_retry_attempt(
                    retry_id=job_id,
                    next_retry_at=next_retry,
                    last_error=str(e)[:500],
                )
                stats["failed_again"] += 1
                logger.info(
                    "retry_worker:scheduled_next_retry",
                    extra={
                        "job_id": job_id,
                        "attempt": new_attempt,
                        "next_retry": next_retry.isoformat(),
                        "delay_seconds": self._retry_delays[delay_index],
                    },
                )
