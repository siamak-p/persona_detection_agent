
from __future__ import annotations

import asyncio
import logging
import traceback
from collections import defaultdict
from datetime import datetime
from typing import Any, Dict, List, Optional, Tuple

from config.settings import Settings
from db.passive_storage import PassiveStorage
from db.postgres_dyadic_overrides import DyadicOverrides, ToneMetrics
from db.postgres_relationship_cluster_personas import RelationshipClusterPersonas
from db.passive_archive_storage import PassiveArchiveStorage, PassivePairCounter
from db.tone_retry_storage import ToneRetryStorage
from tone_and_personality_traits_detection.tone_detection_agent import ToneDetectionAgent

logger = logging.getLogger(__name__)


class ToneScheduler:

    DEFAULT_INTERVAL_SECONDS = 3600
    DEFAULT_MAX_CONVERSATIONS = 1000
    DEFAULT_BATCH_SIZE = 10

    def __init__(
        self,
        settings: Settings,
        passive_storage: PassiveStorage,
        relationship_cluster: RelationshipClusterPersonas,
        dyadic_overrides: DyadicOverrides,
        archive_storage: PassiveArchiveStorage,
        pair_counter: PassivePairCounter,
        tone_agent: ToneDetectionAgent,
        retry_storage: ToneRetryStorage,
        interval_seconds: Optional[int] = None,
    ) -> None:
        self._settings = settings
        self._passive = passive_storage
        self._rel_cluster = relationship_cluster
        self._dyadic = dyadic_overrides
        self._archive = archive_storage
        self._pair_counter = pair_counter
        self._tone_agent = tone_agent
        self._retry_storage = retry_storage
        
        self._interval = (
            interval_seconds 
            or getattr(settings, "TONE_SCHEDULER_INTERVAL_SECONDS", self.DEFAULT_INTERVAL_SECONDS)
        )
        self._max_conversations = getattr(
            settings, "TONE_SCHEDULER_MAX_CONVERSATIONS", self.DEFAULT_MAX_CONVERSATIONS
        )
        self._batch_size = getattr(
            settings, "TONE_SCHEDULER_BATCH_SIZE", self.DEFAULT_BATCH_SIZE
        )
        
        self._task: Optional[asyncio.Task] = None
        self._running = False

    async def start(self) -> None:
        if self._running:
            logger.warning("tone_scheduler:already_running")
            return
        
        self._running = True
        self._task = asyncio.create_task(self._run_loop())
        logger.info(
            f"tone_scheduler:started:interval={self._interval}s,"
            f"max_conv={self._max_conversations},batch_size={self._batch_size}"
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
        
        logger.info("tone_scheduler:stopped")

    async def _run_loop(self) -> None:
        while self._running:
            try:
                await asyncio.sleep(self._interval)
                logger.info("tone_scheduler:scheduled_run:start")
                stats = await self.process_passive_batch()
                logger.info(
                    f"tone_scheduler:scheduled_run:complete:"
                    f"processed={stats.get('conversations_processed', 0)},"
                    f"failed={stats.get('conversations_failed', 0)},"
                    f"archived={stats.get('messages_archived', 0)}"
                )
            except asyncio.CancelledError:
                logger.info("tone_scheduler:scheduled_run:cancelled")
                break
            except Exception as e:
                logger.error(f"tone_scheduler:scheduled_run:error:{e}", exc_info=True)

    async def process_passive_batch(self) -> Dict[str, Any]:
        logger.info("tone_scheduler:process_batch:start")
        stats = {
            "conversations_processed": 0,
            "conversations_failed": 0,
            "messages_archived": 0,
            "messages_sent_to_retry": 0,
            "clusters_updated": 0,
            "dyadic_calculated": 0,
            "errors": 0,
            "batches_processed": 0,
        }
        
        try:
            max_messages = self._max_conversations * 5
            raw_messages = await self._passive.get(limit=max_messages)
            
            if not raw_messages:
                logger.info("tone_scheduler:no_passive_messages")
                return stats
            
            logger.info(f"tone_scheduler:fetched:{len(raw_messages)} messages")
            
            conversations = self._group_by_conversation(raw_messages)
            total_conversations = len(conversations)
            
            conv_ids = list(conversations.keys())[:self._max_conversations]
            logger.info(
                f"tone_scheduler:grouped:{total_conversations} conversations, "
                f"processing:{len(conv_ids)}"
            )
            
            for batch_start in range(0, len(conv_ids), self._batch_size):
                batch_end = min(batch_start + self._batch_size, len(conv_ids))
                batch_conv_ids = conv_ids[batch_start:batch_end]
                
                logger.info(
                    f"tone_scheduler:batch:{batch_start // self._batch_size + 1},"
                    f"conversations:{len(batch_conv_ids)}"
                )
                
                await self._process_batch(
                    batch_conv_ids, 
                    conversations, 
                    stats,
                )
                stats["batches_processed"] += 1
            
            await self._process_dyadic_calculations(stats)
            
            logger.info(f"tone_scheduler:process_batch:done:{stats}")
            return stats
            
        except Exception as e:
            logger.error(f"tone_scheduler:process_batch:error:{e}", exc_info=True)
            stats["errors"] += 1
            return stats

    async def _process_batch(
        self,
        conv_ids: List[str],
        all_conversations: Dict[str, Dict[str, Any]],
        stats: Dict[str, int],
    ) -> None:
        for conv_id in conv_ids:
            conv_data = all_conversations[conv_id]
            try:
                success = await self._process_conversation(conv_data, stats)
                
                if success:
                    await self._delete_from_passive(conv_data["messages"])
                    stats["conversations_processed"] += 1
                else:
                    await self._send_to_retry(conv_data)
                    await self._delete_from_passive(conv_data["messages"])
                    stats["conversations_failed"] += 1
                    stats["messages_sent_to_retry"] += len(conv_data["messages"])
                    
            except Exception as e:
                logger.error(f"tone_scheduler:conv_error:{conv_id}:{e}")
                try:
                    await self._send_to_retry(conv_data, error=str(e))
                    await self._delete_from_passive(conv_data["messages"])
                except Exception as retry_err:
                    logger.error(f"tone_scheduler:retry_enqueue_failed:{conv_id}:{retry_err}")
                stats["conversations_failed"] += 1
                stats["errors"] += 1

    def _group_by_conversation(
        self, messages: List[Dict[str, Any]]
    ) -> Dict[str, Dict[str, Any]]:
        grouped: Dict[str, Dict[str, Any]] = {}
        
        for msg in messages:
            conv_id = msg.get("conversation_id", "")
            if not conv_id:
                continue
            
            if conv_id not in grouped:
                grouped[conv_id] = {
                    "conversation_id": conv_id,
                    "users": set(),
                    "messages": [],
                    "message_ids": [],
                    "turns": [],
                }
            
            conv_data = grouped[conv_id]
            users_set: set = conv_data["users"]
            users_set.add(msg.get("user_id", ""))
            conv_data["messages"].append(msg)
            conv_data["message_ids"].append(msg.get("id"))
            conv_data["turns"].append({
                "speaker": msg.get("user_id", ""),
                "text": msg.get("message", ""),
            })
        
        for conv_data in grouped.values():
            conv_data["users"] = list(conv_data["users"])
        
        return grouped

    async def _process_conversation(
        self,
        conv_data: Dict[str, Any],
        stats: Dict[str, int],
    ) -> bool:
        conv_id = conv_data["conversation_id"]
        users = conv_data["users"]
        messages = conv_data["messages"]
        turns = conv_data["turns"]
        
        if len(users) < 2:
            logger.warning(f"tone_scheduler:skip_conv:single_user:{conv_id}")
            return await self._archive_without_analysis(conv_data, stats)
        
        user_a, user_b = users[0], users[1]
        
        analysis = await self._tone_agent.analyze_conversation(
            conversation_id=conv_id,
            user_a_id=user_a,
            user_b_id=user_b,
            messages=turns,
        )
        
        if not analysis:
            logger.warning(f"tone_scheduler:analysis_failed:{conv_id}")
            return False
        
        rel_class = analysis.relationship_class
        
        if not self._tone_agent.should_update_cluster(analysis):
            logger.info(
                f"tone_scheduler:skip_cluster_update:low_confidence:{conv_id}, "
                f"confidence={analysis.confidence:.2f}, class={rel_class}"
            )
        else:
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
                    message_count=len([m for m in messages if m.get("user_id") == profile.user_id]),
                )
                
            stats["clusters_updated"] += 2
        
        enriched_messages = []
        for msg in messages:
            sender = msg.get("user_id", "")
            receiver = user_b if sender == user_a else user_a
            enriched_messages.append({
                **msg,
                "to_user_id": receiver,
            })
        
        archived_count = await self._archive.archive_messages(enriched_messages)
        stats["messages_archived"] += archived_count
        
        await self._pair_counter.increment(user_a, user_b, len(messages))
        
        return True

    async def _archive_without_analysis(
        self,
        conv_data: Dict[str, Any],
        stats: Dict[str, int],
    ) -> bool:
        messages = conv_data["messages"]
        
        enriched_messages = []
        for msg in messages:
            enriched_messages.append({
                **msg,
                "to_user_id": "",
            })
        
        archived_count = await self._archive.archive_messages(enriched_messages)
        stats["messages_archived"] += archived_count
        return True

    async def _send_to_retry(
        self,
        conv_data: Dict[str, Any],
        error: str | None = None,
    ) -> None:
        users = list(conv_data["users"])
        user_a = users[0] if len(users) > 0 else ""
        user_b = users[1] if len(users) > 1 else ""
        
        await self._retry_storage.enqueue_retry(
            conversation_id=conv_data["conversation_id"],
            user_a=user_a,
            user_b=user_b,
            message_ids=conv_data["message_ids"],
            last_error=error,
        )
        
        logger.info(
            f"tone_scheduler:sent_to_retry:{conv_data['conversation_id']},"
            f"messages={len(conv_data['messages'])}"
        )

    async def _delete_from_passive(self, messages: List[Dict[str, Any]]) -> None:
        ids: List[int] = []
        for msg in messages:
            msg_id = msg.get("id")
            if msg_id is not None and isinstance(msg_id, int):
                ids.append(msg_id)
        if ids:
            try:
                await self._passive.delete_by_ids(ids)
                logger.debug(f"tone_scheduler:deleted_from_passive:{len(ids)}")
            except Exception as e:
                logger.error(f"tone_scheduler:delete_from_passive_error:{e}")

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

    async def _process_dyadic_calculations(self, stats: Dict[str, int]) -> None:
        pairs = await self._pair_counter.get_pairs_needing_dyadic()
        
        for pair in pairs:
            try:
                await self._calculate_dyadic_for_pair(pair.user_a, pair.user_b)
                stats["dyadic_calculated"] += 1
            except Exception as e:
                logger.error(f"tone_scheduler:dyadic_error:{pair.user_a}:{pair.user_b}:{e}")
                stats["errors"] += 1

    async def _calculate_dyadic_for_pair(self, user_a: str, user_b: str) -> None:
        logger.info(f"tone_scheduler:dyadic:start:{user_a}↔{user_b}")
        
        archived = await self._archive.get_messages_for_pair(user_a, user_b, limit=500)
        
        if len(archived) < 50:
            logger.warning(f"tone_scheduler:dyadic:insufficient_data:{user_a}↔{user_b}")
            return
        
        messages = [
            {"speaker": m.user_id, "text": m.message}
            for m in archived
        ]
        
        metrics_a, metrics_b, rel_class = await self._tone_agent.analyze_for_dyadic(
            user_a, user_b, messages
        )
        
        if not metrics_a or not metrics_b:
            logger.warning(f"tone_scheduler:dyadic:analysis_failed:{user_a}↔{user_b}")
            return
        
        msg_count = len(archived)
        
        await self._dyadic.upsert_pair(
            user_a_id=user_a,
            user_b_id=user_b,
            user_a_metrics=metrics_a,
            user_b_metrics=metrics_b,
            relationship_class=rel_class,
            message_count=msg_count,
        )
        
        await self._rel_cluster.update_relationship_for_pair(
            user_a_id=user_a,
            user_b_id=user_b,
            relationship_class=rel_class,
            confidence=1.0,
        )
        
        await self._pair_counter.mark_dyadic_calculated(user_a, user_b, rel_class)
        
        logger.info(f"tone_scheduler:dyadic:done:{user_a}↔{user_b}:class={rel_class}")


def create_tone_scheduler(
    settings: Settings,
    passive_storage: PassiveStorage,
    relationship_cluster: RelationshipClusterPersonas,
    dyadic_overrides: DyadicOverrides,
    archive_storage: PassiveArchiveStorage,
    pair_counter: PassivePairCounter,
    tone_agent: ToneDetectionAgent,
    retry_storage: ToneRetryStorage,
) -> ToneScheduler:
    return ToneScheduler(
        settings=settings,
        passive_storage=passive_storage,
        relationship_cluster=relationship_cluster,
        dyadic_overrides=dyadic_overrides,
        archive_storage=archive_storage,
        pair_counter=pair_counter,
        tone_agent=tone_agent,
        retry_storage=retry_storage,
    )
