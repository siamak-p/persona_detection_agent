
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Dict, List, Optional

from config.settings import Settings
from db.passive_archive_storage import PassiveArchiveStorage, PassivePairCounter
from db.postgres_dyadic_overrides import DyadicOverrides, ToneMetrics
from db.postgres_relationship_cluster_personas import RelationshipClusterPersonas
from db.tone_retry_storage import ToneRetryStorage
from tone_and_personality_traits_detection.tone_detection_agent import ToneDetectionAgent

logger = logging.getLogger(__name__)


class ToneRetryWorker:

    DEFAULT_INTERVAL_SECONDS = 300
    DEFAULT_BATCH_SIZE = 10

    def __init__(
        self,
        settings: Settings,
        retry_storage: ToneRetryStorage,
        archive_storage: PassiveArchiveStorage,
        pair_counter: PassivePairCounter,
        relationship_cluster: RelationshipClusterPersonas,
        tone_agent: ToneDetectionAgent,
        interval_seconds: Optional[int] = None,
    ) -> None:
        self._settings = settings
        self._retry_storage = retry_storage
        self._archive = archive_storage
        self._pair_counter = pair_counter
        self._rel_cluster = relationship_cluster
        self._tone_agent = tone_agent
        
        self._interval = (
            interval_seconds 
            or getattr(settings, "TONE_RETRY_WORKER_INTERVAL_SECONDS", self.DEFAULT_INTERVAL_SECONDS)
        )
        self._batch_size = getattr(
            settings, "TONE_SCHEDULER_BATCH_SIZE", self.DEFAULT_BATCH_SIZE
        )
        
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            logger.warning("tone_retry_worker:already_running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(f"tone_retry_worker:started:interval={self._interval}s")

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
        
        logger.info("tone_retry_worker:stopped")

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._interval)
                logger.info("tone_retry_worker:scheduled_run:start")
                stats = await self.process_retries()
                logger.info(
                    f"tone_retry_worker:scheduled_run:complete:"
                    f"processed={stats.get('processed', 0)},"
                    f"succeeded={stats.get('succeeded', 0)},"
                    f"moved_to_failed={stats.get('moved_to_failed', 0)}"
                )
            except asyncio.CancelledError:
                logger.info("tone_retry_worker:scheduled_run:cancelled")
                break
            except Exception as e:
                logger.error(f"tone_retry_worker:scheduled_run:error:{e}", exc_info=True)

    async def process_retries(self) -> Dict[str, Any]:
        logger.info("tone_retry_worker:process:start")
        stats = {
            "processed": 0,
            "succeeded": 0,
            "failed_again": 0,
            "moved_to_failed": 0,
            "errors": 0,
        }
        
        try:
            pending = await self._retry_storage.get_pending_retries(limit=self._batch_size)
            
            if not pending:
                logger.debug("tone_retry_worker:no_pending_retries")
                return stats
            
            logger.info(f"tone_retry_worker:found:{len(pending)} pending retries")
            
            for retry_job in pending:
                try:
                    success = await self._process_single_retry(retry_job, stats)
                    stats["processed"] += 1
                    
                    if success:
                        await self._retry_storage.remove_retry(retry_job["id"])
                        stats["succeeded"] += 1
                    else:
                        still_retryable = await self._retry_storage.update_retry_attempt(
                            retry_id=retry_job["id"],
                            last_error="Analysis failed",
                        )
                        if still_retryable:
                            stats["failed_again"] += 1
                        else:
                            stats["moved_to_failed"] += 1
                            
                except Exception as e:
                    logger.error(f"tone_retry_worker:retry_error:{retry_job['id']}:{e}")
                    still_retryable = await self._retry_storage.update_retry_attempt(
                        retry_id=retry_job["id"],
                        last_error=str(e),
                    )
                    if still_retryable:
                        stats["failed_again"] += 1
                    else:
                        stats["moved_to_failed"] += 1
                    stats["errors"] += 1
            
            logger.info(f"tone_retry_worker:process:done:{stats}")
            return stats
            
        except Exception as e:
            logger.error(f"tone_retry_worker:process:error:{e}", exc_info=True)
            stats["errors"] += 1
            return stats

    async def _process_single_retry(
        self,
        retry_job: Dict[str, Any],
        stats: Dict[str, int],
    ) -> bool:
        conv_id = retry_job["conversation_id"]
        user_a = retry_job["user_a"]
        user_b = retry_job["user_b"]
        message_ids = retry_job.get("message_ids", [])
        
        logger.info(
            f"tone_retry_worker:processing:{conv_id},"
            f"attempt={retry_job['attempt_count'] + 1},"
            f"messages={len(message_ids)}"
        )
        
        if not user_a or not user_b:
            logger.warning(f"tone_retry_worker:skip:missing_users:{conv_id}")
            return True
        
        archived_messages = await self._archive.get_messages_for_pair(
            user_a, user_b, limit=100
        )
        
        conv_messages = [
            m for m in archived_messages 
            if m.conversation_id == conv_id
        ]
        
        if not conv_messages:
            logger.warning(f"tone_retry_worker:no_messages_found:{conv_id}")
            return False
        
        turns = [
            {"speaker": m.user_id, "text": m.message}
            for m in conv_messages
        ]
        
        analysis = await self._tone_agent.analyze_conversation(
            conversation_id=conv_id,
            user_a_id=user_a,
            user_b_id=user_b,
            messages=turns,
        )
        
        if not analysis:
            logger.warning(f"tone_retry_worker:analysis_failed:{conv_id}")
            return False
        
        rel_class = analysis.relationship_class
        
        if self._tone_agent.should_update_cluster(analysis):
            await self._rel_cluster.update_relationship_for_pair(
                user_a_id=user_a,
                user_b_id=user_b,
                relationship_class=rel_class,
                confidence=analysis.confidence,
            )
            
            for profile in analysis.user_profiles:
                other_user = user_b if profile.user_id == user_a else user_a
                
                if rel_class in ("boss", "subordinate"):
                    from db.postgres_dyadic_overrides import ASYMMETRIC_RELATIONSHIP_INVERSE
                    if profile.user_id == user_a:
                        metrics_cluster = ASYMMETRIC_RELATIONSHIP_INVERSE.get(rel_class, rel_class)
                    else:
                        metrics_cluster = rel_class
                else:
                    metrics_cluster = rel_class
                
                await self._update_cluster_metrics(
                    user_id=profile.user_id,
                    cluster_name=metrics_cluster,
                    new_metrics=profile.to_tone_metrics(),
                    message_count=len([m for m in conv_messages if m.user_id == profile.user_id]),
                )
        
        logger.info(f"tone_retry_worker:success:{conv_id}:class={rel_class}")
        return True

    async def _update_cluster_metrics(
        self,
        user_id: str,
        cluster_name: str,
        new_metrics: ToneMetrics,
        message_count: int,
    ) -> None:
        current = await self._rel_cluster.get(user_id, cluster_name)
        
        if not current or current.total_message_count == 0:
            existing_members = current.members if current else []
            await self._rel_cluster.upsert(
                user_id=user_id,
                cluster_name=cluster_name,
                metrics=new_metrics,
                members=existing_members,
                message_count=message_count,
            )
            return
        
        old_weight = current.total_message_count
        new_weight = message_count
        total_weight = old_weight + new_weight
        
        def weighted_avg(old_val: float, new_val: float) -> float:
            return (old_val * old_weight + new_val * new_weight) / total_weight
        
        merged_metrics = ToneMetrics(
            avg_formality=weighted_avg(current.metrics.avg_formality, new_metrics.avg_formality),
            avg_humor=weighted_avg(current.metrics.avg_humor, new_metrics.avg_humor),
            profanity_rate=0.0,
            directness=weighted_avg(current.metrics.directness, new_metrics.directness),
            optimistic_rate=weighted_avg(current.metrics.optimistic_rate, new_metrics.optimistic_rate),
            pessimistic_rate=weighted_avg(current.metrics.pessimistic_rate, new_metrics.pessimistic_rate),
            submissive_rate=weighted_avg(current.metrics.submissive_rate, new_metrics.submissive_rate),
            dominance=weighted_avg(current.metrics.dominance, new_metrics.dominance),
            emotional_dependence_rate=weighted_avg(
                current.metrics.emotional_dependence_rate, 
                new_metrics.emotional_dependence_rate
            ),
            style_summary=new_metrics.style_summary or current.metrics.style_summary,
        )
        
        await self._rel_cluster.upsert(
            user_id=user_id,
            cluster_name=cluster_name,
            metrics=merged_metrics,
            members=current.members,
            message_count=total_weight,
        )


def create_tone_retry_worker(
    settings: Settings,
    retry_storage: ToneRetryStorage,
    archive_storage: PassiveArchiveStorage,
    pair_counter: PassivePairCounter,
    relationship_cluster: RelationshipClusterPersonas,
    tone_agent: ToneDetectionAgent,
) -> ToneRetryWorker:
    return ToneRetryWorker(
        settings=settings,
        retry_storage=retry_storage,
        archive_storage=archive_storage,
        pair_counter=pair_counter,
        relationship_cluster=relationship_cluster,
        tone_agent=tone_agent,
    )
