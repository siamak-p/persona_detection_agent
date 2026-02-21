
from __future__ import annotations

import logging
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional, Tuple

from config.settings import Settings
from db.passive_archive_storage import PassiveArchiveStorage, compute_pair_id
from memory.mem0_adapter import Mem0Adapter
from summarizer.summarizer_agent import SummarizerAgent, SummaryWithFacts

logger = logging.getLogger(__name__)


@dataclass
class SummarizationResult:
    success: bool
    conversation_id: str
    pair_id: str
    user_a: str
    user_b: str
    summary_id: str | None = None
    summary_text: str | None = None
    clean_summary: str | None = None
    message_count: int = 0
    high_priority_facts: List[Dict] = field(default_factory=list)
    medium_priority_facts: List[Dict] = field(default_factory=list)
    low_priority_facts: List[Dict] = field(default_factory=list)
    error: str | None = None


class PassiveSummarizerAgent:

    DEFAULT_MIN_MESSAGES = 40
    DEFAULT_MIN_TOKENS = 300
    DEFAULT_MAX_MESSAGES = 100

    def __init__(
        self,
        settings: Settings,
        summarizer_agent: SummarizerAgent,
        archive_storage: PassiveArchiveStorage,
        mem0_adapter: Mem0Adapter,
        min_messages: int | None = None,
        min_tokens: int | None = None,
        max_messages: int | None = None,
    ) -> None:
        self._settings = settings
        self._summarizer = summarizer_agent
        self._archive = archive_storage
        self._mem0 = mem0_adapter
        
        self._min_messages = min_messages or self.DEFAULT_MIN_MESSAGES
        self._min_tokens = min_tokens or self.DEFAULT_MIN_TOKENS
        self._max_messages = max_messages or self.DEFAULT_MAX_MESSAGES
        
        logger.info(
            "passive_summarizer_agent:init",
            extra={
                "min_messages": self._min_messages,
                "min_tokens": self._min_tokens,
                "max_messages": self._max_messages,
            },
        )

    async def summarize_conversation(
        self,
        conversation_id: str,
        user_a: str,
        user_b: str,
        *,
        delete_after_success: bool = False,
    ) -> SummarizationResult:
        pair_id = compute_pair_id(user_a, user_b)
        
        logger.info(
            "passive_summarizer_agent:summarize_conversation:start",
            extra={
                "conversation_id": conversation_id,
                "pair_id": pair_id,
                "user_a": user_a,
                "user_b": user_b,
            },
        )
        
        try:
            async with self._archive.acquire_summarization_lock(user_a, user_b, conversation_id):
                return await self._do_summarize(
                    conversation_id=conversation_id,
                    user_a=user_a,
                    user_b=user_b,
                    pair_id=pair_id,
                    delete_after_success=delete_after_success,
                )
        except RuntimeError as e:
            logger.warning(
                "passive_summarizer_agent:lock_failed",
                extra={
                    "conversation_id": conversation_id,
                    "pair_id": pair_id,
                    "error": str(e),
                },
            )
            return SummarizationResult(
                success=False,
                conversation_id=conversation_id,
                pair_id=pair_id,
                user_a=user_a,
                user_b=user_b,
                error="Lock acquisition failed - another summarization in progress",
            )
        except Exception as e:
            logger.error(
                "passive_summarizer_agent:error",
                extra={
                    "conversation_id": conversation_id,
                    "pair_id": pair_id,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
                exc_info=True,
            )
            return SummarizationResult(
                success=False,
                conversation_id=conversation_id,
                pair_id=pair_id,
                user_a=user_a,
                user_b=user_b,
                error=str(e),
            )

    async def _do_summarize(
        self,
        conversation_id: str,
        user_a: str,
        user_b: str,
        pair_id: str,
        delete_after_success: bool,
    ) -> SummarizationResult:
        try:
            messages = await self._archive.get_messages_for_pair(
                user_a, user_b, 
                limit=self._max_messages,
                latest_first=True,
            )
            
            total_tokens = sum(
                len(msg.message.split()) for msg in messages
            )
            estimated_tokens = int(total_tokens * 1.3)
            
            meets_message_threshold = len(messages) >= self._min_messages
            meets_token_threshold = estimated_tokens >= self._min_tokens
            
            if not meets_message_threshold and not meets_token_threshold:
                logger.info(
                    "passive_summarizer_agent:skip:below_threshold",
                    extra={
                        "conversation_id": conversation_id,
                        "pair_id": pair_id,
                        "message_count": len(messages),
                        "min_messages": self._min_messages,
                        "estimated_tokens": estimated_tokens,
                        "min_tokens": self._min_tokens,
                    },
                )
                return SummarizationResult(
                    success=False,
                    conversation_id=conversation_id,
                    pair_id=pair_id,
                    user_a=user_a,
                    user_b=user_b,
                    error=f"Below threshold (messages={len(messages)}/{self._min_messages}, tokens≈{estimated_tokens}/{self._min_tokens})",
                )
            
            logger.info(
                "passive_summarizer_agent:threshold_met",
                extra={
                    "conversation_id": conversation_id,
                    "pair_id": pair_id,
                    "message_count": len(messages),
                    "estimated_tokens": estimated_tokens,
                    "triggered_by": "messages" if meets_message_threshold else "tokens",
                },
            )
            
            messages_with_authors: List[Tuple[str, str]] = [
                (msg.user_id, msg.message)
                for msg in messages
            ]
            
            previous_summary = await self._mem0.get_summary(
                owner_user_id=user_a,
                partner_user_id=user_b,
                conversation_id=conversation_id,
            )
            
            logger.info(
                "passive_summarizer_agent:calling_summarizer",
                extra={
                    "conversation_id": conversation_id,
                    "message_count": len(messages),
                    "has_previous_summary": bool(previous_summary),
                },
            )
            
            summary_with_facts = await self._summarizer.summarize_with_facts(
                previous_summary=previous_summary,
                messages_with_authors=messages_with_authors,
                user_a_id=user_a,
                user_b_id=user_b,
            )
            
            if not summary_with_facts.summary_text or not summary_with_facts.summary_text.strip():
                logger.warning(
                    "passive_summarizer_agent:empty_summary",
                    extra={"conversation_id": conversation_id, "pair_id": pair_id},
                )
                return SummarizationResult(
                    success=False,
                    conversation_id=conversation_id,
                    pair_id=pair_id,
                    user_a=user_a,
                    user_b=user_b,
                    error="Empty summary generated",
                )
            
            topics = self._extract_topics(messages_with_authors)
            
            result = await self._mem0.add_summary(
                owner_user_id=user_a,
                partner_user_id=user_b,
                conversation_id=conversation_id,
                summary=summary_with_facts.clean_summary,
                extra_metadata={
                    "source": "passive",
                    "message_count": len(messages),
                    "topics": topics,
                    "high_priority_facts": summary_with_facts.high_priority_facts,
                    "medium_priority_facts": summary_with_facts.medium_priority_facts,
                    "high_priority_count": len(summary_with_facts.high_priority_facts),
                    "medium_priority_count": len(summary_with_facts.medium_priority_facts),
                    "low_priority_count": len(summary_with_facts.low_priority_facts),
                    "full_summary_length": len(summary_with_facts.summary_text),
                    "clean_summary_length": len(summary_with_facts.clean_summary),
                },
            )
            summary_id = result.get("id") if result.get("success") else None
            
            logger.info(
                "passive_summarizer_agent:success",
                extra={
                    "conversation_id": conversation_id,
                    "pair_id": pair_id,
                    "summary_id": summary_id,
                    "message_count": len(messages),
                    "high_priority_facts": len(summary_with_facts.high_priority_facts),
                    "medium_priority_facts": len(summary_with_facts.medium_priority_facts),
                    "low_priority_facts_discarded": len(summary_with_facts.low_priority_facts),
                    "topics": topics,
                },
            )
            
            message_ids = [msg.id for msg in messages]
            deleted_count = await self._archive.mark_as_deleted(
                user_a=user_a,
                user_b=user_b,
                message_ids=message_ids,
            )
            logger.info(
                "passive_summarizer_agent:soft_deleted",
                extra={
                    "pair_id": pair_id,
                    "deleted_count": deleted_count,
                },
            )
            
            return SummarizationResult(
                success=True,
                conversation_id=conversation_id,
                pair_id=pair_id,
                user_a=user_a,
                user_b=user_b,
                summary_id=summary_id,
                summary_text=summary_with_facts.summary_text,
                clean_summary=summary_with_facts.clean_summary,
                message_count=len(messages),
                high_priority_facts=summary_with_facts.high_priority_facts,
                medium_priority_facts=summary_with_facts.medium_priority_facts,
                low_priority_facts=summary_with_facts.low_priority_facts,
            )
            
        except Exception as e:
            logger.error(
                "passive_summarizer_agent:error",
                extra={
                    "conversation_id": conversation_id,
                    "pair_id": pair_id,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
                exc_info=True,
            )
            return SummarizationResult(
                success=False,
                conversation_id=conversation_id,
                pair_id=pair_id,
                user_a=user_a,
                user_b=user_b,
                error=str(e),
            )

    async def summarize_pair(
        self,
        user_a: str,
        user_b: str,
        *,
        delete_after_success: bool = False,
    ) -> SummarizationResult:
        pair_id = compute_pair_id(user_a, user_b)
        conversation_id = f"pair_{pair_id}"
        
        logger.info(
            "passive_summarizer_agent:summarize_pair:start",
            extra={
                "user_a": user_a,
                "user_b": user_b,
                "pair_id": pair_id,
            },
        )
        
        return await self.summarize_conversation(
            conversation_id=conversation_id,
            user_a=user_a,
            user_b=user_b,
            delete_after_success=delete_after_success,
        )

    def _extract_topics(
        self,
        messages_with_authors: List[Tuple[str, str]],
    ) -> List[str]:
        topic_keywords = {
            "خانواده": ["بچه", "فرزند", "مادر", "پدر", "خواهر", "برادر", "همسر", "عروسی"],
            "کار": ["شرکت", "جلسه", "پروژه", "رئیس", "کارمند", "دفتر", "اداره"],
            "خرید": ["خرید", "فروشگاه", "بازار", "قیمت", "پول"],
            "سلامت": ["دکتر", "بیمارستان", "دارو", "مریض", "سلامت"],
            "تفریح": ["فیلم", "سینما", "پارک", "سفر", "تعطیلات", "مهمانی"],
            "غذا": ["غذا", "ناهار", "شام", "صبحانه", "رستوران", "آشپزی"],
        }
        
        topic_counts: Dict[str, int] = {}
        all_text = " ".join(text for _, text in messages_with_authors)
        
        for topic, keywords in topic_keywords.items():
            count = sum(1 for kw in keywords if kw in all_text)
            if count > 0:
                topic_counts[topic] = count
        
        sorted_topics = sorted(topic_counts.items(), key=lambda x: x[1], reverse=True)
        return [topic for topic, _ in sorted_topics[:5]]


def create_passive_summarizer_agent(
    settings: Settings,
    summarizer_agent: SummarizerAgent,
    archive_storage: PassiveArchiveStorage,
    mem0_adapter: Mem0Adapter,
) -> PassiveSummarizerAgent:
    return PassiveSummarizerAgent(
        settings=settings,
        summarizer_agent=summarizer_agent,
        archive_storage=archive_storage,
        mem0_adapter=mem0_adapter,
    )
