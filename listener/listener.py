
from __future__ import annotations

import asyncio
import logging
from datetime import datetime
from typing import Any, Optional, Iterable, Protocol, List, TYPE_CHECKING

from listener.exceptions import ListenerError
from memory.mem0_adapter import Mem0Adapter
from db.postgres_chat_store import PostgresChatStore

if TYPE_CHECKING:
    from summarizer.summarizer_agent import SummaryWithFacts


class Summarizer(Protocol):
    async def summarize(self, messages: list[str], max_words: int = 120) -> str: ...
    async def summarize_per_user(
        self,
        *,
        previous_summary: Optional[str],
        messages_with_authors: List[tuple[str, str]],
        user_a_id: str,
        user_b_id: str,
    ) -> str: ...
    async def summarize_with_facts(
        self,
        *,
        previous_summary: Optional[str],
        messages_with_authors: List[tuple[str, str]],
        user_a_id: str,
        user_b_id: str,
    ) -> "SummaryWithFacts": ...


logger = logging.getLogger(__name__)


class ListenerAgent:

    def __init__(
        self,
        mem0_adapter: Mem0Adapter,
        summarizer_agent: Optional[Summarizer] = None,
        summarize_threshold: int = 20,
        min_chars_for_summary: int = 0,
        settings: Optional[Any] = None,
        chat_store: Optional[PostgresChatStore] = None,
        summarize_every_n_messages: Optional[int] = None,
        **kwargs,
    ) -> None:
        self._mem0 = mem0_adapter
        self._summarizer = summarizer_agent
        self._summarize_threshold = int(
            summarize_every_n_messages
            if summarize_every_n_messages is not None
            else (summarize_threshold or 0)
        )
        self._min_chars_for_summary = min_chars_for_summary or 0
        self._settings = settings
        self._chat_store = chat_store

        if kwargs:
            logger.info("listener:init:extra_kwargs_ignored", extra={"keys": list(kwargs.keys())})

        logger.info(
            "listener:init",
            extra={
                "summarize_threshold": self._summarize_threshold,
                "has_chat_store": bool(self._chat_store),
                "has_summarizer": bool(self._summarizer),
            },
        )

    async def process(
        self,
        memory_owner_id: str,
        partner_user_id: str,
        conversation_id: str,
        message: dict[str, Any],
        mode: str = "chat",
    ) -> dict[str, Any]:
        logger.info(
            "listener:process:start",
            extra={"owner": memory_owner_id, "partner": partner_user_id, "mode": mode},
        )
        try:
            message_text = message.get("text", "") or ""
            message_id = message.get("message_id", "") or ""
            author_id = message.get("author_id", partner_user_id)
            role = message.get("role", "human")

            if not message_text.strip():
                logger.warning("listener:process:empty_message")
                return {"success": False, "error": "Empty message"}

            if self._chat_store is not None and mode != "creator":
                try:
                    await self._chat_store.log_event(
                        author_id=author_id,
                        user_a=memory_owner_id,
                        user_b=partner_user_id,
                        conversation_id=conversation_id,
                        text=message_text,
                        role=role,
                        message_id=message_id or None,
                    )
                except Exception as pg_e:
                    logger.error(
                        "listener:process:chat_store_log_failed",
                        extra={"owner": memory_owner_id, "error": str(pg_e)},
                        exc_info=True,
                    )

            if role == "human" and mode == "creator":
                result = await self._mem0.add_user_message(
                    owner_user_id=memory_owner_id,
                    partner_user_id=partner_user_id,
                    conversation_id=conversation_id,
                    text=message_text,
                    message_id=message_id,
                    mode=mode,
                )
            else:
                result = {
                    "success": True,
                    "skipped_mem0": True,
                    "reason": f"mode={mode}, role={role}",
                }

            logger.info(
                "listener:process:done",
                extra={"owner": memory_owner_id},
            )
            return {
                "success": True,
                "mem0_result": result,
            }

        except Exception as e:
            logger.error(
                "listener:process:error",
                extra={"owner": memory_owner_id, "error": str(e)},
                exc_info=True,
            )
            raise ListenerError(f"Failed to process message: {str(e)}")

    async def check_and_trigger_summarization(
        self,
        memory_owner_id: str,
        partner_user_id: str,
        conversation_id: str,
    ) -> None:
        logger.info(
            "listener:summarization:check_start",
            extra={
                "owner": memory_owner_id,
                "partner": partner_user_id,
                "conversation_id": conversation_id,
                "has_summarizer": self._summarizer is not None,
                "has_chat_store": self._chat_store is not None,
            },
        )

        if not self._summarizer or self._summarize_threshold <= 0:
            logger.info("listener:summarization:disabled_or_no_summarizer")
            return

        try:
            if self._chat_store is not None:
                count = await self._chat_store.count_active(
                    user_a=memory_owner_id, user_b=partner_user_id, conversation_id=conversation_id
                )
                token_sum = await self._chat_store.sum_active_tokens(
                    user_a=memory_owner_id, user_b=partner_user_id, conversation_id=conversation_id
                )
                MIN_TOKEN_THRESHOLD = 300

                needs = (count >= self._summarize_threshold) or (token_sum >= MIN_TOKEN_THRESHOLD)
                logger.info(
                    "listener:summarization:status_check_pg",
                    extra={
                        "owner": memory_owner_id,
                        "count": count,
                        "token_sum": token_sum,
                        "threshold_count": self._summarize_threshold,
                        "threshold_token": MIN_TOKEN_THRESHOLD,
                        "needs": needs,
                    },
                )
                if not needs:
                    return

                events = await self._chat_store.get_recent_events(
                    user_a=memory_owner_id,
                    user_b=partner_user_id,
                    conversation_id=conversation_id,
                    limit=100,
                    include_deleted=False,
                )
                events = [e for e in events if e.get("role") in ("human", "ai")]

                messages_with_authors = [
                    (e["author"], e["text"])
                    for e in events
                    if (e.get("text") or "").strip() and "author" in e
                ]
                ids = [e["id"] for e in events if "id" in e]

                task = asyncio.create_task(
                    self._background_summarization_with_lock(
                        memory_owner_id=memory_owner_id,
                        partner_user_id=partner_user_id,
                        conversation_id=conversation_id,
                        memories=None,
                        messages_with_authors=messages_with_authors,
                        event_ids_to_delete=ids,
                    )
                )
                task.add_done_callback(lambda _: None)
                return

            metadata_filter = {"conversation_id": conversation_id, "to_user_id": partner_user_id}
            memories = await self._mem0.get_memories(
                memory_owner_id,
                limit=max(5, self._summarize_threshold + 5),
                metadata=metadata_filter,
            )

            message_memories = [
                m for m in memories if m.get("metadata", {}).get("type") != "summary"
            ]
            current_count = len(message_memories)

            needs = current_count >= self._summarize_threshold
            logger.info(
                "listener:summarization:status_check_mem0",
                extra={
                    "owner": memory_owner_id,
                    "count": current_count,
                    "threshold": self._summarize_threshold,
                    "needs": needs,
                },
            )

            if not needs:
                return

            task = asyncio.create_task(
                self._background_summarization(
                    memory_owner_id=memory_owner_id,
                    partner_user_id=partner_user_id,
                    conversation_id=conversation_id,
                    memories=message_memories[: self._summarize_threshold],
                )
            )
            task.add_done_callback(lambda _: None)

        except Exception as e:
            logger.error(
                "listener:summarization:check_error",
                extra={"owner": memory_owner_id, "error": str(e)},
                exc_info=True,
            )

    async def _background_summarization_with_lock(
        self,
        memory_owner_id: str,
        partner_user_id: str,
        conversation_id: str,
        memories: Optional[list[dict[str, Any]]] = None,
        *,
        messages_with_authors: Optional[List[tuple[str, str]]] = None,
        event_ids_to_delete: Optional[List[int]] = None,
    ) -> None:
        if self._chat_store is None:
            await self._background_summarization(
                memory_owner_id=memory_owner_id,
                partner_user_id=partner_user_id,
                conversation_id=conversation_id,
                memories=memories,
                messages_with_authors=messages_with_authors,
                event_ids_to_delete=event_ids_to_delete,
            )
            return

        try:
            async with self._chat_store.acquire_summarization_lock(
                user_a=memory_owner_id,
                user_b=partner_user_id,
                conversation_id=conversation_id,
            ):
                logger.info(
                    "listener:summarization:lock_acquired",
                    extra={"owner": memory_owner_id, "conversation_id": conversation_id},
                )
                
                await self._background_summarization(
                    memory_owner_id=memory_owner_id,
                    partner_user_id=partner_user_id,
                    conversation_id=conversation_id,
                    memories=memories,
                    messages_with_authors=messages_with_authors,
                    event_ids_to_delete=event_ids_to_delete,
                )
                
        except RuntimeError as e:
            logger.warning(
                "listener:summarization:lock_unavailable",
                extra={
                    "owner": memory_owner_id,
                    "conversation_id": conversation_id,
                    "error": str(e),
                },
            )
            raise RuntimeError(
                f"Lock acquisition failed for {memory_owner_id}/{conversation_id} - another summarization in progress"
            )
        except Exception as e:
            logger.error(
                "listener:summarization:lock_error",
                extra={"owner": memory_owner_id, "error": str(e)},
                exc_info=True,
            )
            raise

    async def _background_summarization(
        self,
        memory_owner_id: str,
        partner_user_id: str,
        conversation_id: str,
        memories: Optional[list[dict[str, Any]]] = None,
        *,
        messages_with_authors: Optional[List[tuple[str, str]]] = None,
        event_ids_to_delete: Optional[List[int]] = None,
    ) -> None:
        try:
            logger.info(
                "listener:summarization:start_background_task",
                extra={
                    "owner": memory_owner_id,
                    "has_authors": bool(messages_with_authors),
                    "msg_count": 0 if messages_with_authors is None else len(messages_with_authors),
                },
            )

            previous_summary = None
            try:
                previous_summary = await self._mem0.get_summary(
                    owner_user_id=memory_owner_id,
                    partner_user_id=partner_user_id,
                    conversation_id=conversation_id,
                )
            except Exception as e:
                logger.error(
                    "listener:summarization:failed_to_get_prev_summary",
                    extra={"error": str(e)},
                    exc_info=True,
                )

            summary_text: str = ""
            clean_summary: str = ""
            high_priority_facts: list = []
            medium_priority_facts: list = []
            low_priority_facts: list = []

            if messages_with_authors and hasattr(self._summarizer, "summarize_with_facts"):
                summary_with_facts = await self._summarizer.summarize_with_facts(
                    previous_summary=previous_summary,
                    messages_with_authors=messages_with_authors,
                    user_a_id=memory_owner_id,
                    user_b_id=partner_user_id,
                )
                summary_text = summary_with_facts.summary_text
                clean_summary = summary_with_facts.clean_summary
                high_priority_facts = summary_with_facts.high_priority_facts
                medium_priority_facts = summary_with_facts.medium_priority_facts
                low_priority_facts = summary_with_facts.low_priority_facts
                
                logger.info(
                    "listener:summarization:facts_extracted",
                    extra={
                        "owner": memory_owner_id,
                        "high_count": len(high_priority_facts),
                        "medium_count": len(medium_priority_facts),
                        "low_count_discarded": len(low_priority_facts),
                    },
                )
            elif messages_with_authors and hasattr(self._summarizer, "summarize_per_user"):
                summary_text = await self._summarizer.summarize_per_user(
                    previous_summary=previous_summary,
                    messages_with_authors=messages_with_authors,
                    user_a_id=memory_owner_id,
                    user_b_id=partner_user_id,
                )
                clean_summary = summary_text
            elif memories and hasattr(self._summarizer, "summarize"):
                texts = [
                    (memory.get("memory", "") or "").strip()
                    for memory in memories
                    if (memory.get("memory", "") or "").strip()
                ]
                summary_text = await self._summarizer.summarize(messages=texts, max_words=80)
                clean_summary = summary_text
            else:
                logger.info("listener:summarization:skipped_no_valid_input")
                return

            if not summary_text or not str(summary_text).strip():
                logger.info("listener:summarization:empty_summary")
                return

            await self._mem0.add_summary(
                owner_user_id=memory_owner_id,
                partner_user_id=partner_user_id,
                conversation_id=conversation_id,
                summary=str(clean_summary).strip(),
                extra_metadata={
                    "high_priority_facts": high_priority_facts,
                    "medium_priority_facts": medium_priority_facts,
                    "low_priority_discarded": len(low_priority_facts),
                    "full_summary_length": len(summary_text),
                    "clean_summary_length": len(clean_summary),
                },
            )

            if self._chat_store is not None and event_ids_to_delete:
                try:
                    deleted_count = await self._chat_store.delete_by_ids(event_ids_to_delete)
                    logger.info(
                        "listener:summarization:deleted_events",
                        extra={"owner": memory_owner_id, "deleted": deleted_count},
                    )
                except Exception as pg_e:
                    logger.error(
                        "listener:summarization:delete_failed",
                        extra={"owner": memory_owner_id, "error": str(pg_e)},
                        exc_info=True,
                    )

            logger.info(
                "listener:summarization:complete",
                extra={
                    "owner": memory_owner_id,
                    "msg_count": len(messages_with_authors) if messages_with_authors else 0,
                    "high_facts": len(high_priority_facts),
                    "medium_facts": len(medium_priority_facts),
                },
            )

        except Exception as e:
            logger.error(
                "listener:summarization:error",
                extra={"owner": memory_owner_id, "error": str(e)},
                exc_info=True,
            )

            if self._chat_store is not None:
                try:
                    from datetime import datetime, timedelta

                    first_delay = 300
                    if self._settings:
                        delays_str = getattr(self._settings, "SUMMARY_RETRY_DELAYS_SECONDS", "300,3600,14400")
                        delays = [int(x) for x in delays_str.split(",")]
                        first_delay = delays[0] if delays else 300
                    
                    next_retry = datetime.utcnow() + timedelta(seconds=first_delay)
                    await self._chat_store.enqueue_retry(
                        user_a=memory_owner_id,
                        user_b=partner_user_id,
                        conversation_id=conversation_id,
                        next_retry_at=next_retry,
                        last_error=str(e)[:500],
                    )
                    logger.info(
                        "listener:summarization:enqueued_retry",
                        extra={
                            "owner": memory_owner_id,
                            "next_retry": next_retry.isoformat(),
                            "delay_seconds": first_delay,
                        },
                    )
                except Exception as retry_e:
                    logger.error(
                        "listener:summarization:failed_to_enqueue_retry",
                        extra={"error": str(retry_e)},
                        exc_info=True,
                    )
