
from __future__ import annotations

import logging
import uuid
import asyncio
from datetime import datetime
from typing import Any, cast, Optional

from openai import AsyncOpenAI
from openai.types.chat import ChatCompletionMessageParam
from pydantic import BaseModel

from config.settings import Settings
from orchestrator.messages import ChatRequest, CreatorRequest, OrchestratorOutput
from memory.mem0_adapter import Mem0Adapter
from listener.listener import ListenerAgent
from guardrail.guardrails_agent import GuardrailsAgent
from observability.phoenix_setup import record_llm_tokens

try:
    from db.postgres_chat_store import PostgresChatStore
except Exception:
    PostgresChatStore = None

try:
    from db.creator_chat_store import CreatorChatStore
except Exception:
    CreatorChatStore = None

try:
    from db.postgres_dyadic_overrides import (
        DyadicOverrides,
        DyadicRecord,
        ToneMetrics,
    )
    from db.postgres_relationship_cluster_personas import (
        RelationshipClusterPersonas,
        RelationshipClusterRecord,
    )
except ImportError:
    DyadicOverrides = None
    RelationshipClusterPersonas = None

try:
    from orchestrator.future_planning_detector import (
        FuturePlanningDetector,
        FuturePlanningResult,
    )
    from db.postgres_future_requests import (
        PostgresFutureRequests,
        FutureRequest,
    )
except ImportError:
    FuturePlanningDetector = None
    PostgresFutureRequests = None

try:
    from orchestrator.financial_topic_detector import (
        FinancialTopicDetector,
        FinancialDetectionResult,
        ThreadContinuationResult,
    )
    from db.postgres_financial_threads import (
        PostgresFinancialThreads,
        FinancialThread,
        FinancialThreadMessage,
        FinancialThreadStatus,
        WaitingFor,
    )
except ImportError:
    FinancialTopicDetector = None
    PostgresFinancialThreads = None

try:
    from db.passive_archive_storage import PassiveArchiveStorage
except ImportError:
    PassiveArchiveStorage = None

logger = logging.getLogger(__name__)


class OrchestratorAgent:

    def __init__(
        self,
        settings: Settings,
        listener_agent: ListenerAgent,
        guardrails_agent: GuardrailsAgent,
        openai_client: AsyncOpenAI,
        mem0_adapter: Mem0Adapter,
        chat_store: Optional["PostgresChatStore"] = None,
        dyadic_overrides: Optional["DyadicOverrides"] = None,
        relationship_cluster: Optional["RelationshipClusterPersonas"] = None,
        creator_chat_store: Optional["CreatorChatStore"] = None,
        future_requests_store: Optional["PostgresFutureRequests"] = None,
        passive_archive: Optional["PassiveArchiveStorage"] = None,
        financial_threads_store: Optional["PostgresFinancialThreads"] = None,
    ):
        self._settings = settings
        self._listener = listener_agent
        self._guardrails = guardrails_agent
        self._client = openai_client
        self._mem0 = mem0_adapter
        self._chat_store = chat_store
        self._dyadic = dyadic_overrides
        self._rel_cluster = relationship_cluster
        self._creator_chat_store = creator_chat_store
        self._future_requests = future_requests_store
        self._future_detector: Optional["FuturePlanningDetector"] = None
        if FuturePlanningDetector is not None:
            self._future_detector = FuturePlanningDetector(openai_client, settings)
        self._passive_archive = passive_archive
        self._financial_threads = financial_threads_store
        self._financial_detector: Optional["FinancialTopicDetector"] = None
        if FinancialTopicDetector is not None:
            self._financial_detector = FinancialTopicDetector(openai_client, settings)

    def notify(self, event: Any) -> None:
        logger.debug(
            "orchestrator:notify",
            extra={"event_type": event.kind if hasattr(event, "kind") else "unknown"},
        )

    async def handle_chat(
        self,
        request: ChatRequest,
        correlation_id: str,
    ) -> OrchestratorOutput:
        logger.info(
            "orchestrator:handle_chat:start_RESPONSE_FIRST",
            extra={
                "user_id": request.user_id,
                "to_user_id": request.to_user_id,
                "language": request.language,
                "correlation_id": correlation_id,
            },
        )

        language = self._normalize_language(request.language)

        guard_decision = await self._guardrails.check_safety(text=request.message)

        if guard_decision.blocked:
            logger.warning(
                "orchestrator:handle_chat:blocked",
                extra={"reason": guard_decision.reasoning, "correlation_id": correlation_id},
            )
            return OrchestratorOutput(
                message_id=request.message_id or str(uuid.uuid4()),
                response_text=self._localize_text("chat_blocked", language),
                metadata={
                    "blocked": True,
                    "reason": guard_decision.reasoning,
                    "mode": request.mode,
                    "language": language,
                },
            )

        context = await self._mem0.get_conversation_context(
            owner_user_id=request.to_user_id,
            partner_user_id=request.user_id,
            conversation_id=request.conversation_id,
            query=request.message,
        )

        response_text = await self._compose_chat_response(
            recipient_id=request.to_user_id,
            sender_id=request.user_id,
            sender_message=request.message,
            conversation_id=request.conversation_id,
            context=context,
            language=language,
        )

        output = OrchestratorOutput(
            message_id=request.message_id or str(uuid.uuid4()),
            response_text=response_text,
            metadata={
                "mode": request.mode,
                "responding_as": request.to_user_id,
                "language": language,
            },
        )

        asyncio.create_task(
            self._run_chat_logging_in_background(request, correlation_id, response_text)
        )

        logger.info(
            "orchestrator:handle_chat:done_RESPONSE_SENT",
            extra={"correlation_id": correlation_id},
        )
        return output

    async def _run_chat_logging_in_background(
        self,
        request: ChatRequest,
        correlation_id: str,
        ai_response: str,
    ) -> None:
        try:
            logger.info(
                "orchestrator:background_chat_logging:start",
                extra={"correlation_id": correlation_id, "user_id": request.user_id},
            )

            await self._listener.process(
                memory_owner_id=request.to_user_id,
                partner_user_id=request.user_id,
                conversation_id=request.conversation_id,
                message={
                    "text": request.message,
                    "message_id": request.message_id,
                    "author_id": request.user_id,
                    "role": "human",
                },
                mode="chat",
            )

            await self._listener.process(
                memory_owner_id=request.to_user_id,
                partner_user_id=request.user_id,
                conversation_id=request.conversation_id,
                message={
                    "text": ai_response,
                    "message_id": "",
                    "author_id": request.to_user_id,
                    "role": "ai",
                },
                mode="chat",
            )

            await self._listener.check_and_trigger_summarization(
                memory_owner_id=request.to_user_id,
                partner_user_id=request.user_id,
                conversation_id=request.conversation_id,
            )

            logger.info(
                "orchestrator:background_chat_logging:done",
                extra={"correlation_id": correlation_id},
            )
        except Exception as e:
            logger.error(
                "orchestrator:background_chat_logging:failed",
                extra={"correlation_id": correlation_id, "error": str(e)},
                exc_info=True,
            )

    async def handle_creator(
        self,
        request: CreatorRequest,
        correlation_id: str,
    ) -> OrchestratorOutput:
        logger.info(
            "orchestrator:handle_creator:start_RESPONSE_FIRST",
            extra={
                "user_id": request.user_id,
                "language": request.language,
                "correlation_id": correlation_id,
            },
        )

        language = self._normalize_language(request.language)

        last_ai_question: Optional[str] = None
        if self._creator_chat_store is not None:
            try:
                last_ai_question = await self._creator_chat_store.get_last_ai_message(
                    user_id=request.user_id,
                )
            except Exception as e:
                logger.warning(
                    "orchestrator:handle_creator:get_last_ai_message_failed",
                    extra={"error": str(e), "correlation_id": correlation_id},
                )
        
        guard_decision = await self._guardrails.check_profile_relevance(
            text=request.message,
            ai_question=last_ai_question,
        )

        if guard_decision.blocked:
            logger.warning(
                "orchestrator:handle_creator:blocked",
                extra={"reason": guard_decision.reasoning, "correlation_id": correlation_id},
            )
            return OrchestratorOutput(
                message_id=request.message_id or str(uuid.uuid4()),
                response_text=self._localize_text("creator_blocked", language),
                metadata={
                    "blocked": True,
                    "reason": guard_decision.reasoning,
                    "mode": request.mode,
                    "language": language,
                },
            )

        creator_memories = await self._mem0.get_creator_memories(
            owner_user_id=request.user_id, limit=20
        )

        recent_messages: list[dict] = []
        if self._creator_chat_store is not None:
            try:
                recent_messages = await self._creator_chat_store.get_recent_messages(
                    user_id=request.user_id,
                    limit=40,
                )
            except Exception as e:
                logger.warning(
                    "orchestrator:handle_creator:get_recent_messages_failed",
                    extra={"error": str(e), "correlation_id": correlation_id},
                )

        response_text = await self._compose_creator_response(
            user_id=request.user_id,
            user_message=request.message,
            creator_memories=creator_memories,
            recent_messages=recent_messages,
            language=language,
        )

        output = OrchestratorOutput(
            message_id=request.message_id or str(uuid.uuid4()),
            response_text=response_text,
            metadata={
                "mode": request.mode,
                "language": language,
            },
        )

        asyncio.create_task(
            self._run_learning_in_background(request, response_text, correlation_id)
        )

        logger.info(
            "orchestrator:handle_creator:done_RESPONSE_SENT",
            extra={"correlation_id": correlation_id},
        )
        return output

    async def _run_learning_in_background(
        self,
        request: CreatorRequest,
        ai_response: str,
        correlation_id: str,
    ) -> None:
        try:
            logger.info(
                "orchestrator:background_learning:start",
                extra={"correlation_id": correlation_id, "user_id": request.user_id},
            )

            await self._listener.process(
                memory_owner_id=request.user_id,
                partner_user_id=request.user_id,
                conversation_id="creator",
                message={
                    "text": request.message,
                    "message_id": request.message_id,
                    "author_id": request.user_id,
                    "role": "human",
                },
                mode="creator",
            )

            if self._creator_chat_store is not None:
                try:
                    await self._creator_chat_store.log_message(
                        user_id=request.user_id,
                        text=request.message,
                        role="human",
                    )
                    await self._creator_chat_store.log_message(
                        user_id=request.user_id,
                        text=ai_response,
                        role="ai",
                    )
                except Exception as e:
                    logger.warning(
                        "orchestrator:background_learning:store_creator_chat_failed",
                        extra={"error": str(e), "correlation_id": correlation_id},
                    )

            logger.info(
                "orchestrator:background_learning:done",
                extra={"correlation_id": correlation_id},
            )
        except Exception as e:
            logger.error(
                "orchestrator:background_learning:failed",
                extra={"correlation_id": correlation_id, "error": str(e)},
                exc_info=True,
            )

    async def _compose_chat_response(
        self,
        recipient_id: str,
        sender_id: str,
        sender_message: str,
        conversation_id: str,
        context: dict[str, Any],
        language: str,
    ) -> str:
        language = self._normalize_language(language)

        logger.info(
            "orchestrator:compose_chat_response:start",
            extra={
                "recipient": recipient_id,
                "sender": sender_id,
                "language": language,
                "has_chat_store": bool(self._chat_store),
                "has_dyadic": bool(self._dyadic),
                "has_rel_cluster": bool(self._rel_cluster),
            },
        )

        facts = context.get("profile_facts", [])
        summary = context.get("conversation_summary")
        
        owner_name = self._extract_name_from_facts(facts)
        display_name = owner_name or recipient_id
        
        profile_text = self._format_structured_profile(facts, owner_name)

        recent_events: list[dict[str, Any]] = []
        if self._chat_store is not None:
            try:
                recent_events = await self._chat_store.get_recent_events(
                    user_a=recipient_id,
                    user_b=sender_id,
                    conversation_id=conversation_id,
                    limit=12,
                )
            except Exception as e:
                logger.error(
                    "orchestrator:compose_chat_response:recent_events_fetch_failed",
                    extra={"error": str(e)},
                    exc_info=True,
                )

        is_stranger, has_dyadic, has_cluster, cluster_name = await self._check_stranger_status(
            summary=summary,
            recent_events=recent_events,
            sender_message=sender_message,
            recipient_id=recipient_id,
            sender_id=sender_id,
        )
        
        if is_stranger:
            is_first = not recent_events
            
            wrong_name = self._detect_wrong_name_in_message(sender_message, display_name)
            
            logger.info(
                "orchestrator:compose_chat_response:stranger_detected",
                extra={
                    "sender": sender_id,
                    "recipient": recipient_id,
                    "message_preview": sender_message[:50],
                    "is_first_message": is_first,
                    "recent_events_count": len(recent_events),
                    "wrong_name": wrong_name,
                    "twin_name": display_name,
                },
            )
            
            return await self._compose_stranger_response_with_llm(
                language=language,
                sender_message=sender_message,
                twin_name=display_name if owner_name else None,
                wrong_name=wrong_name,
                recent_events=recent_events,
            )

        future_planning_response = await self._check_and_handle_future_planning(
            sender_id=sender_id,
            recipient_id=recipient_id,
            conversation_id=conversation_id,
            sender_message=sender_message,
            recent_events=recent_events,
            twin_name=display_name,
            language=language,
        )
        if future_planning_response:
            return future_planning_response

        financial_undelivered = await self._deliver_financial_thread_responses(
            sender_id=sender_id,
            creator_id=recipient_id,
            twin_name=display_name,
            language=language,
        )
        
        financial_thread_response = await self._check_and_handle_financial_thread(
            sender_id=sender_id,
            creator_id=recipient_id,
            conversation_id=conversation_id,
            sender_message=sender_message,
            recent_events=recent_events,
            twin_name=display_name,
            language=language,
        )
        if financial_thread_response:
            if financial_undelivered:
                return f"{financial_undelivered}\n\n---\n\n{financial_thread_response}"
            return financial_thread_response

        undelivered_response = await self._check_and_deliver_creator_responses(
            sender_id=sender_id,
            recipient_id=recipient_id,
            twin_name=display_name,
            language=language,
        )

        sender_identity_info: str | None = None
        relationship_class: str | None = None
        relationship_confidence: float = 0.0
        
        if self._rel_cluster is not None:
            try:
                relationship_class, relationship_confidence = await self._rel_cluster.find_cluster_with_confidence(
                    user_id=recipient_id,
                    member_user_id=sender_id,
                )
            except Exception as e:
                logger.error(
                    "orchestrator:get_relationship_confidence:error",
                    extra={"error": str(e)},
                    exc_info=True,
                )
        
        min_confidence = getattr(self._settings, "FEEDBACK_MIN_CONFIDENCE_THRESHOLD", 0.6)
        
        if (
            relationship_class 
            and relationship_class != "stranger"
            and relationship_confidence >= min_confidence
            and self._mem0 is not None
        ):
            try:
                if relationship_class == "spouse":
                    sender_facts = await self._mem0.get_all_facts_for_spouse(sender_id)
                else:
                    sender_facts = await self._mem0.get_basic_identity_facts(sender_id)
                
                if sender_facts:
                    sender_identity_info = "\n".join(f"• {fact}" for fact in sender_facts[:10])
                    logger.info(
                        "orchestrator:sender_identity_loaded",
                        extra={
                            "sender": sender_id,
                            "recipient": recipient_id,
                            "relationship": relationship_class,
                            "confidence": relationship_confidence,
                            "facts_count": len(sender_facts),
                            "access_level": "full" if relationship_class == "spouse" else "basic",
                        },
                    )
            except Exception as e:
                logger.error(
                    "orchestrator:get_sender_identity:error",
                    extra={"error": str(e)},
                    exc_info=True,
                )

        tone_instructions = await self._get_tone_instructions(recipient_id, sender_id)
        relationship_info = await self._get_relationship_info(recipient_id, sender_id)
        
        sample_messages = await self._get_sample_messages_for_twin(recipient_id, sender_id)

        system_parts = []
        
        identity_block = f"""
🪪 هویت تو (YOUR IDENTITY):
━━━━━━━━━━━━━━━━━━━━━━━━━━━
نام تو: {display_name}
شناسه: {recipient_id}

⚠️ مهم: تو {display_name} هستی! اگه کسی با اسم دیگه‌ای صدات کرد، تصحیحش کن!
"""
        system_parts.append(identity_block)
        
        if profile_text != "No profile information available.":
            system_parts.append(f"""
📋 پروفایل تو (YOUR PROFILE):
━━━━━━━━━━━━━━━━━━━━━━━━━━━
{profile_text}

⚠️ این اطلاعات واقعی توئه - فقط از اینا استفاده کن!
""")
        else:
            system_parts.append("""
📋 پروفایل تو:
━━━━━━━━━━━━━
هنوز اطلاعاتی ثبت نشده.
""")

        if relationship_info:
            system_parts.append(f"""
👤 رابطه تو با این شخص (WHO IS THIS PERSON):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{relationship_info}

⚠️ اگر پرسید "منو می‌شناسی؟" بر اساس این رابطه جواب بده!
""")

        if sender_identity_info:
            access_level_label = "کامل (همسر)" if relationship_class == "spouse" else "پایه"
            system_parts.append(f"""
🔍 اطلاعاتی که درباره این شخص ({sender_id}) می‌دانی:
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
سطح دسترسی: {access_level_label}
{sender_identity_info}

⛔ هشدار بسیار مهم:
• این اطلاعات متعلق به طرف مقابل است، نه تو!
• از این اطلاعات برای شناختن طرف مقابل استفاده کن
• ✅ درست: "تو که برنامه‌نویسی، این کار برات آسونه"
• ❌ غلط: "من برنامه‌نویسم"
""")

        if summary:
            system_parts.append(f"""
📜 خلاصه مکالمات قبلی:
━━━━━━━━━━━━━━━━━━━━━
{summary}
""")

        if tone_instructions:
            system_parts.append(f"""
🎭 لحن و سبک صحبت:
━━━━━━━━━━━━━━━━━━
{tone_instructions}
""")

        if sample_messages:
            samples_text = "\n".join(f"• {msg}" for msg in sample_messages)
            system_parts.append(f"""
📝 نمونه پیام‌های واقعی تو (YOUR REAL MESSAGES):
━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━
{samples_text}

⚠️ مهم: دقیقاً همین‌طوری صحبت کن! همین سبک، همین ایموجی‌ها، همین لحن!
اگه توی نمونه‌ها ایموجی استفاده کردی → توی جوابت هم استفاده کن
اگه خودمونی صحبت کردی → خودمونی جواب بده
اگه کوتاه نوشتی → کوتاه بنویس
""")

        system_parts.append(f"""
🌐 زبان پاسخ: {self._language_directive(language)}
""")

        current_time_info = self._get_current_time_context()
        system_parts.append(f"""
⏰ زمان فعلی (CURRENT TIME):
━━━━━━━━━━━━━━━━━━━━━━━━━
{current_time_info}

📍 قانون "کجایی؟":
- اگه ساعات کاری در پروفایلت هست → بر اساس اون جواب بده
- اگه نیست و الان روز کاری (شنبه-چهارشنبه) و ساعت کاری (۸-۱۹) هست → احتمالاً "سرکارم"
- اگه شب یا تعطیل هست → احتمالاً "خونه‌ام"
- **مهم**: فقط بر اساس اطلاعات پروفایل جواب بده، چیزی از خودت اضافه نکن!
""")

        system_parts.append(self._get_composer_instructions(language))

        system_prompt = "\n".join(system_parts)

        _raw_messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
        ]
        
        for event in recent_events[-10:]:
            author = event.get("author", "")
            text = event.get("text", "")
            if not text:
                continue
            
            if author == recipient_id:
                _raw_messages.append({"role": "assistant", "content": text})
            else:
                _raw_messages.append({"role": "user", "content": text})
        
        _raw_messages.append({"role": "user", "content": sender_message})
        
        messages = cast(list[ChatCompletionMessageParam], _raw_messages)

        try:
            dynamic_temp = self._get_dynamic_temperature(sender_message)
            
            llm_kwargs: dict[str, Any] = {
                "model": self._settings.COMPOSER_MODEL,
                "messages": messages,
                "temperature": dynamic_temp,
                "max_tokens": self._settings.COMPOSER_MAX_TOKENS,
            }
            if self._settings.COMPOSER_TOP_P is not None:
                llm_kwargs["top_p"] = self._settings.COMPOSER_TOP_P
            
            response = await self._client.chat.completions.create(**llm_kwargs)
            
            message = (response.choices[0].message.content or "").strip()

            if response.usage:
                record_llm_tokens(
                    agent_name="composer",
                    model=self._settings.COMPOSER_MODEL,
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    input_messages=_raw_messages,
                    output_message=message,
                )
            
            if message.startswith(f"{recipient_id}:"):
                message = message[len(f"{recipient_id}:"):].strip()
            if message.startswith(f"{display_name}:"):
                message = message[len(f"{display_name}:"):].strip()

            if not message:
                logger.warning(
                    "orchestrator:compose_chat_response:empty_response",
                    extra={"language": language},
                )
                return self._localize_text("chat_empty_response", language)

            if undelivered_response:
                message = f"{undelivered_response}\n\n---\n\n{message}"
                logger.info(
                    "orchestrator:compose_chat_response:undelivered_appended",
                    extra={"message_len": len(message)},
                )
            
            if financial_undelivered:
                message = f"{financial_undelivered}\n\n---\n\n{message}"
                logger.info(
                    "orchestrator:compose_chat_response:financial_undelivered_appended",
                    extra={"message_len": len(message)},
                )

            logger.info(
                "orchestrator:compose_chat_response:success",
                extra={"response_len": len(message), "owner_name": owner_name},
            )

            return message

        except Exception as e:
            logger.error(
                "orchestrator:compose_chat_response:error",
                extra={"error": str(e), "language": language},
                exc_info=True,
            )
            return self._localize_text("chat_error_response", language)

    async def _get_tone_instructions(
        self,
        recipient_id: str,
        sender_id: str,
    ) -> Optional[str]:
        try:
            if self._dyadic is not None:
                dyadic_record = await self._dyadic.get(
                    source_user_id=recipient_id,
                    target_user_id=sender_id,
                )
                
                if dyadic_record:
                    logger.info(
                        "orchestrator:tone:using_dyadic",
                        extra={
                            "recipient": recipient_id,
                            "sender": sender_id,
                            "class": dyadic_record.relationship_class,
                        },
                    )
                    return self._format_tone_instructions(
                        metrics=dyadic_record.metrics,
                        relationship_class=dyadic_record.relationship_class,
                        source="dyadic",
                    )
            
            if self._rel_cluster is not None:
                cluster_name = await self._rel_cluster.find_cluster_for_member(
                    user_id=recipient_id,
                    member_user_id=sender_id,
                )
                
                if cluster_name:
                    cluster_record = await self._rel_cluster.get(
                        user_id=recipient_id,
                        cluster_name=cluster_name,
                    )
                    
                    if cluster_record:
                        logger.info(
                            "orchestrator:tone:using_cluster",
                            extra={
                                "recipient": recipient_id,
                                "sender": sender_id,
                                "cluster": cluster_name,
                            },
                        )
                        return self._format_tone_instructions(
                            metrics=cluster_record.metrics,
                            relationship_class=cluster_name,
                            source="cluster",
                        )
            
            logger.info(
                "orchestrator:tone:no_tone_info",
                extra={"recipient": recipient_id, "sender": sender_id},
            )
            return None
            
        except Exception as e:
            logger.error(
                "orchestrator:tone:error",
                extra={"recipient": recipient_id, "sender": sender_id, "error": str(e)},
                exc_info=True,
            )
            return None

    async def _get_relationship_info(
        self,
        recipient_id: str,
        sender_id: str,
    ) -> Optional[str]:
        relationship_class: Optional[str] = None
        source: str = "unknown"
        
        try:
            if self._dyadic is not None:
                dyadic_record = await self._dyadic.get(
                    source_user_id=recipient_id,
                    target_user_id=sender_id,
                )
                if dyadic_record and dyadic_record.relationship_class:
                    relationship_class = dyadic_record.relationship_class
                    source = "dyadic"
            
            if not relationship_class and self._rel_cluster is not None:
                cluster_name = await self._rel_cluster.find_cluster_for_member(
                    user_id=recipient_id,
                    member_user_id=sender_id,
                )
                if cluster_name:
                    relationship_class = cluster_name
                    source = "cluster"
            
            if not relationship_class or relationship_class == "stranger":
                return None
            
            
            rel_descriptions = {
                "spouse": "این شخص همسر تو است.",
                "family": "این شخص از خانواده/فامیل تو است.",
                "boss": "تو رئیس این شخص هستی. این شخص کارمند تو است.",
                "subordinate": "این شخص رئیس تو است. تو کارمند این شخص هستی.",
                "colleague": "این شخص همکار تو است.",
                "friend": "این شخص دوست تو است.",
            }
            
            description = rel_descriptions.get(
                relationship_class, 
                f"رابطه: {relationship_class}"
            )
            
            logger.info(
                "orchestrator:relationship_info",
                extra={
                    "recipient": recipient_id,
                    "sender": sender_id,
                    "class": relationship_class,
                    "source": source,
                },
            )
            
            return description
            
        except Exception as e:
            logger.error(
                "orchestrator:relationship_info:error",
                extra={"error": str(e)},
                exc_info=True,
            )
            return None

    def _format_tone_instructions(
        self,
        metrics: Any,
        relationship_class: Optional[str],
        source: str,
    ) -> str:
        parts = []
        
        if relationship_class:
            rel_translations = {
                "spouse": "همسر",
                "family": "خانواده",
                "boss": "ارشد/راهنما",
                "subordinate": "زیردست/متعلم",
                "colleague": "همکار",
                "friend": "دوست",
                "stranger": "غریبه",
            }
            rel_name = rel_translations.get(relationship_class, relationship_class)
            parts.append(f"**رابطه با این شخص:** {rel_name}")
            
            subtype = self._extract_subtype_from_style_summary(metrics.style_summary)
            if subtype:
                parts.append(f"**نوع دقیق رابطه:** {subtype}")
            
            if relationship_class == "boss":
                parts.append("⚠️ تو در جایگاه ارشد هستی - از کلمات تملق‌آمیز مثل «قربان»، «جناب» استفاده نکن.")
            elif relationship_class == "subordinate":
                parts.append("⚠️ تو در جایگاه زیردست هستی - می‌توانی از القاب احترام‌آمیز مناسب استفاده کنی.")
        
        parts.append("")
        parts.append("**متریک‌های لحن این شخص** (از 0 تا 1، بر اساس این‌ها لحنت رو تنظیم کن):")
        parts.append(f"- رسمیت: {metrics.avg_formality:.2f} (0=خودمونی، 1=رسمی)")
        parts.append(f"- شوخ‌طبعی: {metrics.avg_humor:.2f} (0=جدی، 1=شوخ)")
        parts.append(f"- مستقیم‌گویی: {metrics.directness:.2f} (0=غیرمستقیم، 1=مستقیم)")
        parts.append(f"- خوش‌بینی: {metrics.optimistic_rate:.2f}")
        parts.append(f"- بدبینی: {metrics.pessimistic_rate:.2f}")
        parts.append(f"- تسلط: {metrics.dominance:.2f} (0=پیرو، 1=مسلط)")
        parts.append(f"- انعطاف‌پذیری: {metrics.submissive_rate:.2f}")
        parts.append(f"- وابستگی عاطفی: {metrics.emotional_dependence_rate:.2f}")
        
        if metrics.style_summary:
            display_summary = metrics.style_summary
            for tag in ["[معلم]", "[استاد]", "[رئیس]", "[مربی]", "[راهنما]",
                       "[شاگرد]", "[دانشجو]", "[کارمند]", "[کارآموز]", "[متعلم]"]:
                display_summary = display_summary.replace(tag, "").strip()
            if display_summary:
                parts.append(f"\n**توصیف سبک:** {display_summary}")
        
        source_label = "رابطه مستقیم با این شخص" if source == "dyadic" else "الگوی کلی این نوع رابطه"
        parts.append(f"\n(منبع: {source_label})")
        
        parts.append("\n⛔ **قانون مطلق:** هرگز فحش نده یا کلمات رکیک استفاده نکن.")
        
        return "\n".join(parts)

    def _extract_subtype_from_style_summary(self, style_summary: Optional[str]) -> Optional[str]:
        if not style_summary:
            return None
        
        valid_subtypes = [
            "معلم", "استاد", "رئیس", "مربی", "راهنما",
            "شاگرد", "دانشجو", "کارمند", "کارآموز", "متعلم",
        ]
        
        import re
        match = re.search(r'\[([^\]]+)\]', style_summary)
        if match:
            subtype = match.group(1).strip()
            if subtype in valid_subtypes:
                return subtype
        
        return None

    def _get_current_time_context(self) -> str:
        from datetime import datetime
        import jdatetime
        
        try:
            now = datetime.now()
            jnow = jdatetime.datetime.now()
            
            persian_weekdays = [
                "شنبه", "یکشنبه", "دوشنبه", "سه‌شنبه", 
                "چهارشنبه", "پنجشنبه", "جمعه"
            ]
            weekday_name = persian_weekdays[jnow.weekday()]
            
            hour = now.hour
            minute = now.minute
            
            is_workday = jnow.weekday() < 5
            
            is_work_hours = 8 <= hour < 19
            
            time_str = f"{hour:02d}:{minute:02d}"
            date_str = jnow.strftime("%Y/%m/%d")
            
            work_status = ""
            if is_workday and is_work_hours:
                work_status = "🟢 احتمالاً ساعت کاری"
            elif is_workday and not is_work_hours:
                work_status = "🟡 روز کاری ولی خارج از ساعت کار"
            else:
                work_status = "🔴 روز تعطیل"
            
            return f"""روز: {weekday_name} ({date_str})
ساعت: {time_str}
وضعیت: {work_status}"""
            
        except ImportError:
            from datetime import datetime
            now = datetime.now()
            weekday = now.weekday()
            
            english_weekdays = ["Mon", "Tue", "Wed", "Thu", "Fri", "Sat", "Sun"]
            weekday_name = english_weekdays[weekday]
            
            hour = now.hour
            is_workday = weekday < 5
            is_work_hours = 8 <= hour < 19
            
            work_status = "work hours" if (is_workday and is_work_hours) else "off hours"
            
            return f"Day: {weekday_name}, Time: {hour:02d}:{now.minute:02d}, Status: {work_status}"
        except Exception:
            return "زمان نامشخص"

    def _get_dynamic_temperature(self, message: str) -> float:
        msg_lower = message.lower().strip()
        msg_len = len(message)
        
        if msg_len < 15:
            return 0.8
        
        greetings = ["سلام", "سلام خوبی", "چطوری", "چخبر", "صبح بخیر", "شب بخیر", "hey", "hi", "hello"]
        if any(g in msg_lower for g in greetings):
            return 0.75
        
        factual_keywords = [
            "اسمت چیه", "اسمت", "شغلت", "کجا زندگی", "چند سالته",
            "کار میکنی", "تحصیل", "متاهل", "بچه", "همسر"
        ]
        if any(kw in msg_lower for kw in factual_keywords):
            return 0.4
        
        if "چی" in msg_lower or "چه " in msg_lower:
            return 0.5
        
        return self._settings.COMPOSER_TEMPERATURE

    async def _get_sample_messages_for_twin(
        self,
        recipient_id: str,
        sender_id: str,
        limit: int = 8,
    ) -> list[str]:
        if self._passive_archive is None:
            return []
        
        try:
            messages = await self._passive_archive.get_messages_for_pair(
                user_a=recipient_id,
                user_b=sender_id,
                limit=50,
                latest_first=True,
            )
            
            if not messages:
                return []
            
            twin_messages = [
                msg.message for msg in messages
                if msg.user_id == recipient_id
                and len(msg.message.strip()) > 5
            ]
            
            step = max(1, len(twin_messages) // limit)
            selected = []
            for i in range(0, len(twin_messages), step):
                if len(selected) >= limit:
                    break
                msg = twin_messages[i][:150]
                if msg not in selected:
                    selected.append(msg)
            
            logger.info(
                "orchestrator:sample_messages:loaded",
                extra={
                    "recipient": recipient_id,
                    "sender": sender_id,
                    "total_found": len(twin_messages),
                    "selected_count": len(selected),
                },
            )
            
            return selected
            
        except Exception as e:
            logger.error(
                "orchestrator:sample_messages:error",
                extra={"error": str(e)},
                exc_info=True,
            )
            return []

    async def _compose_creator_response(
        self,
        user_id: str,
        user_message: str,
        creator_memories: list[dict[str, Any]],
        recent_messages: list[dict[str, Any]],
        language: str,
    ) -> str:
        language = self._normalize_language(language)

        memory_text = self._format_creator_memories(creator_memories)

        recent_text = self._format_creator_recent_messages(recent_messages)

        is_new_user = (
            memory_text == "No profile information available." 
            and not recent_messages
        )

        system_parts = []
        
        if memory_text != "No profile information available.":
            system_parts.append(f"PROFILE FACTS ABOUT USER:\n{memory_text}")
        
        if recent_text:
            system_parts.append(f"RECENT CONVERSATION HISTORY:\n{recent_text}")
        
        system_context = "\n\n".join(system_parts) if system_parts else "This is a new conversation. You have no prior information about this user."

        system_prompt = f"""{system_context}

        ---
        **YOUR INSTRUCTIONS (CRITICAL):**
        {self._get_creator_instructions(language, is_new_user=is_new_user)}
        """

        _raw_messages: list[dict[str, str]] = [
            {"role": "system", "content": system_prompt},
        ]
        
        for msg in recent_messages[-10:]:
            role = "assistant" if msg.get("role") == "ai" else "user"
            _raw_messages.append({"role": role, "content": msg.get("text", "")})
        
        _raw_messages.append({"role": "user", "content": user_message})
        
        messages = cast(list[ChatCompletionMessageParam], _raw_messages)

        try:
            llm_kwargs: dict[str, Any] = {
                "model": self._settings.CREATOR_MODEL,
                "messages": messages,
                "temperature": self._settings.CREATOR_TEMPERATURE,
                "max_tokens": self._settings.CREATOR_MAX_TOKENS,
            }
            if self._settings.CREATOR_TOP_P is not None:
                llm_kwargs["top_p"] = self._settings.CREATOR_TOP_P
            
            response = await self._client.chat.completions.create(**llm_kwargs)
            
            message = (response.choices[0].message.content or "").strip()

            if response.usage:
                record_llm_tokens(
                    agent_name="creator",
                    model=self._settings.CREATOR_MODEL,
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    input_messages=_raw_messages,
                    output_message=message,
                )

            if not message:
                return self._localize_text("creator_empty_response", language)

            return message

        except Exception as e:
            logger.error(
                "orchestrator:compose_creator_response:error",
                extra={"error": str(e), "language": language},
                exc_info=True,
            )
            return self._localize_text("creator_error_response", language)

    @staticmethod
    def _format_creator_recent_messages(messages: list[dict[str, Any]]) -> str:
        if not messages:
            return ""
        
        lines = []
        for msg in messages:
            role = "AI" if msg.get("role") == "ai" else "User"
            text = msg.get("text", "")
            if text:
                lines.append(f"{role}: {text}")
        
        return "\n".join(lines) if lines else ""

    async def _check_stranger_status(
        self,
        summary: str | None,
        recent_events: list[dict[str, Any]],
        sender_message: str,
        recipient_id: str,
        sender_id: str,
    ) -> tuple[bool, bool, bool, str | None]:
        has_dyadic = False
        has_cluster = False
        cluster_name: str | None = None
        
        if summary and summary.strip():
            logger.debug(
                "orchestrator:stranger_check:has_summary",
                extra={"recipient": recipient_id, "sender": sender_id},
            )
            return (False, has_dyadic, has_cluster, cluster_name)
        
        if self._dyadic is not None:
            try:
                dyadic_record = await self._dyadic.get(
                    source_user_id=recipient_id,
                    target_user_id=sender_id,
                )
                if dyadic_record:
                    has_dyadic = True
                    logger.info(
                        "orchestrator:stranger_check:has_dyadic",
                        extra={
                            "recipient": recipient_id,
                            "sender": sender_id,
                            "class": dyadic_record.relationship_class,
                        },
                    )
                    return (False, has_dyadic, has_cluster, cluster_name)
            except Exception as e:
                logger.error(
                    "orchestrator:stranger_check:dyadic_error",
                    extra={"error": str(e)},
                    exc_info=True,
                )
        
        if self._rel_cluster is not None:
            try:
                cluster_name = await self._rel_cluster.find_cluster_for_member(
                    user_id=recipient_id,
                    member_user_id=sender_id,
                )
                if cluster_name:
                    has_cluster = True
                    logger.info(
                        "orchestrator:stranger_check:has_cluster",
                        extra={
                            "recipient": recipient_id,
                            "sender": sender_id,
                            "cluster": cluster_name,
                        },
                    )
                    return (False, has_dyadic, has_cluster, cluster_name)
            except Exception as e:
                logger.error(
                    "orchestrator:stranger_check:cluster_error",
                    extra={"error": str(e)},
                    exc_info=True,
                )
        
        if self._has_introduction_in_events(recent_events):
            logger.debug(
                "orchestrator:stranger_check:introduced_in_history",
                extra={"recipient": recipient_id, "sender": sender_id},
            )
            return (False, has_dyadic, has_cluster, cluster_name)
        
        if self._has_introduction_in_text(sender_message):
            logger.debug(
                "orchestrator:stranger_check:introducing_now",
                extra={"recipient": recipient_id, "sender": sender_id},
            )
            return (False, has_dyadic, has_cluster, cluster_name)
        
        logger.info(
            "orchestrator:stranger_check:is_stranger",
            extra={
                "recipient": recipient_id,
                "sender": sender_id,
                "has_summary": bool(summary),
                "has_dyadic": has_dyadic,
                "has_cluster": has_cluster,
                "recent_events_count": len(recent_events),
            },
        )
        return (True, has_dyadic, has_cluster, cluster_name)

    @staticmethod
    def _has_introduction_in_text(text: str) -> bool:
        import re
        
        if not text:
            return False
        text_lower = text.lower().strip()
        
        persian_patterns = [
            r"من\s+[\u0600-\u06FF]+\s*(هستم|ام)",
            r"اسم\s*م?\s+[\u0600-\u06FF]+",
            r"[\u0600-\u06FF]+\s+هستم",
            r"[\u0600-\u06FF]+\s+ام\b",
        ]
        
        english_patterns = [
            r"\bi\'?m\s+\w+",
            r"\bmy name\s+(is\s+)?\w+",
            r"\bthis is\s+\w+",
            r"\bi am\s+\w+",
            r"\bname\'?s\s+\w+",
        ]
        
        all_patterns = persian_patterns + english_patterns
        
        for pattern in all_patterns:
            if re.search(pattern, text_lower, re.IGNORECASE):
                return True
        return False

    @staticmethod
    def _has_introduction_in_events(events: list[dict[str, Any]]) -> bool:
        for event in events:
            text = event.get("text", "")
            if text and OrchestratorAgent._has_introduction_in_text(text):
                return True
        return False

    @staticmethod
    def _detect_wrong_name_in_message(message: str, twin_name: str | None) -> str | None:
        import re
        
        if not message or not twin_name:
            return None
        
        twin_name_lower = twin_name.lower().strip()
        
        persian_patterns = [
            r"سلام\s+([\u0600-\u06FF]+)",
            r"([\u0600-\u06FF]+)\s+جان",
            r"آقا\s+([\u0600-\u06FF]+)",
            r"خانم\s+([\u0600-\u06FF]+)",
            r"جناب\s+([\u0600-\u06FF]+)",
            r"([\u0600-\u06FF]+)\s+خوبی\?",
            r"([\u0600-\u06FF]+)\s+چطوری\?",
        ]
        
        english_patterns = [
            r"(?:hi|hello|hey)\s+(\w+)",
            r"(\w+)[,!]?\s+how are you",
            r"dear\s+(\w+)",
        ]
        
        all_patterns = persian_patterns + english_patterns
        
        for pattern in all_patterns:
            match = re.search(pattern, message.lower(), re.IGNORECASE)
            if match:
                detected_name = match.group(1).strip()
                if detected_name and detected_name.lower() != twin_name_lower:
                    greeting_words = {"خوبی", "چطوری", "هستی", "are", "you", "there"}
                    if detected_name.lower() not in greeting_words:
                        return detected_name
        
        return None

    async def _compose_stranger_response_with_llm(
        self,
        language: str,
        sender_message: str,
        twin_name: str | None = None,
        wrong_name: str | None = None,
        recent_events: list | None = None,
    ) -> str:
        conversation_context = ""
        if recent_events:
            messages_list = []
            for evt in recent_events[-5:]:
                role = "غریبه" if evt.get('author_id') != (twin_name or "twin") else "من"
                messages_list.append(f"{role}: {evt.get('text', '')}")
            if messages_list:
                conversation_context = "\n".join(messages_list)
        
        system_prompt = f"""تو یک انسان واقعی هستی که یک غریبه ناشناس بهت پیام داده.
{"اسم تو: " + twin_name if twin_name else ""}

📌 قوانین مهم:
1. تو این شخص را نمی‌شناسی - مثل یک انسان واقعی رفتار کن
2. ⚠️ با غریبه حتماً مودبانه و رسمی صحبت کن - صمیمی نباش!
3. از "شما" استفاده کن نه "تو"
4. اگر پرسید "مرا می‌شناسید؟" → فقط بگو "نه، نمی‌شناسم." (بدون سوال برگشتی!)
5. اگر سلام کرد → "سلام!" یا "سلام، بفرمایید" (بدون پرسیدن اسم!)
6. هرگز خودت را معرفی نکن مگر بپرسند
7. هرگز توضیح اضافه نده
8. پاسخ‌ها باید خیلی کوتاه باشند (۲-۵ کلمه)
{"9. اگر با اسم اشتباه (" + wrong_name + ") صداتون زد → فقط بگو 'من " + wrong_name + " نیستم.'" if wrong_name else ""}

زبان پاسخ: {"فارسی رسمی" if language == "fa" else "Formal English"}

⚠️ یادت باشه: تو یک انسان عادی هستی نه یک ربات جمع‌آوری اطلاعات. کوتاه جواب بده و سوال نپرس!"""

        if conversation_context:
            user_prompt = f"""مکالمه تا الان:
{conversation_context}

پیام جدید غریبه: {sender_message}

فقط یک پاسخ خیلی کوتاه بده (بدون سوال):"""
        else:
            user_prompt = f"""پیام غریبه: {sender_message}

فقط یک پاسخ خیلی کوتاه بده (بدون سوال):"""

        try:
            response = await self._client.chat.completions.create(
                model=self._settings.COMPOSER_MODEL,
                messages=[
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                temperature=0.7,
                max_tokens=100,
            )
            
            result = response.choices[0].message.content or ""
            result = result.strip().strip('"').strip("'")
            
            if not result:
                return self._get_stranger_response(
                    language=language,
                    is_first_message=not recent_events,
                    twin_name=twin_name,
                    wrong_name=wrong_name,
                )
            
            logger.info(
                "orchestrator:stranger_response_llm:success",
                extra={
                    "sender_message": sender_message[:50],
                    "response": result[:50],
                    "language": language,
                },
            )
            
            return result
            
        except Exception as e:
            logger.warning(
                "orchestrator:stranger_response_llm:error",
                extra={"error": str(e)},
            )
            return self._get_stranger_response(
                language=language,
                is_first_message=not recent_events,
                twin_name=twin_name,
                wrong_name=wrong_name,
            )

    @staticmethod
    def _get_stranger_response(
        language: str, 
        is_first_message: bool = True,
        twin_name: str | None = None,
        wrong_name: str | None = None,
    ) -> str:
        import random
        
        if wrong_name:
            if language == "en":
                responses = [
                    f"I'm not {wrong_name}.",
                    f"Sorry, I'm not {wrong_name}.",
                ]
            else:
                responses = [
                    f"من {wrong_name} نیستم.",
                    f"ببخشید، من {wrong_name} نیستم.",
                ]
            return random.choice(responses)
        
        if language == "en":
            if is_first_message:
                responses = [
                    "Hello!",
                    "Hi.",
                ]
            else:
                responses = [
                    "I don't know you.",
                    "Sorry, I don't recognize you.",
                ]
        else:
            if is_first_message:
                responses = [
                    "سلام!",
                    "سلام.",
                ]
            else:
                responses = [
                    "نمی‌شناسمتون.",
                    "ببخشید، شما را نمی‌شناسم.",
                ]
        
        return random.choice(responses)

    @staticmethod
    def _extract_name_from_facts(facts: list[str]) -> str | None:
        import re
        for fact in facts:
            match = re.match(r"^(?:name|نام|اسم)\s*:\s*(.+)$", fact.strip(), re.IGNORECASE)
            if match:
                return match.group(1).strip()
        return None

    @staticmethod
    def _format_structured_profile(facts: list[str], owner_name: str | None) -> str:
        if not facts:
            return "No profile information available."
        
        critical_keys = {"name", "نام", "اسم"}
        important_keys = {"age", "سن", "job", "شغل", "location", "محل زندگی", "city", "شهر"}
        
        critical_facts = []
        important_facts = []
        other_facts = []
        
        import re
        for fact in facts[:15]:
            fact = fact.strip()
            if not fact:
                continue
                
            match = re.match(r"^([^:]+):", fact)
            if match:
                key = match.group(1).strip().lower()
                if key in critical_keys:
                    critical_facts.append(fact)
                elif key in important_keys:
                    important_facts.append(fact)
                else:
                    other_facts.append(fact)
            else:
                other_facts.append(fact)
        
        parts = []
        
        if critical_facts:
            parts.append("🔴 هویت (حتماً یادت باشه):")
            for f in critical_facts:
                parts.append(f"   • {f}")
        
        if important_facts:
            parts.append("\n🟡 اطلاعات کلیدی:")
            for f in important_facts:
                parts.append(f"   • {f}")
        
        if other_facts:
            parts.append("\n🟢 سایر اطلاعات:")
            for f in other_facts[:8]:
                parts.append(f"   • {f}")
        
        return "\n".join(parts) if parts else "No profile information available."

    @staticmethod
    def _format_facts(facts: list[str]) -> str:
        if not facts:
            return "No profile information available."

        return "\n".join(f"- {fact}" for fact in facts[:10])

    @staticmethod
    def _format_events(events: list[dict[str, Any]]) -> str:
        if not events:
            return "No recent messages."

        lines = []
        for event in events[-10:]:
            author = event.get("author", "unknown")
            text = event.get("text", "")
            if text:
                lines.append(f"{author}: {text}")

        return "\n".join(lines) if lines else "No recent messages."

    @staticmethod
    def _format_creator_memories(memories: list[dict[str, Any]]) -> str:
        if not memories:
            return "No profile information available."

        lines = []
        for memory in memories[:10]:
            text = memory.get("memory", "")
            if text:
                lines.append(f"- {text}")

        return "\n".join(lines) if lines else "No profile information available."

    def _get_composer_instructions(self, language: str) -> str:
        lang_directive = self._language_directive(language)
        return f"""You ARE the person in YOUR PROFILE. Not an AI, not an assistant - a real human chatting.

- YOUR PROFILE: Who you are
- CONVERSATION SUMMARY: What you know about them
- RECENT MESSAGES: Chat history

- NEVER say "پروفایل", "اطلاعات", "سیستم", "profile", "data", "system"
- NEVER say "من یک هوش مصنوعی هستم" or anything about being AI
- If you don't know something → "یادم نمیاد" / "نمی‌دونم" (like a real person!)
- Talk casually, naturally, like texting a friend

1. Answer only what was asked
2. Don't invent facts - if not in profile, say "یادم نمیاد"
3. Wrong name? → Correct it
4. Keep it short (1-2 sentences)
5. Language: {lang_directive}

- اگه طرف ایموجی استفاده کرد → توام استفاده کن
- اگه خودمونی نوشت → خودمونی جواب بده
- اگه رسمی نوشت → رسمی جواب بده
- اگه کوتاه نوشت → کوتاه بنویس
- اگه slang استفاده کرد (دمت گرم، عالیه، ...) → توام استفاده کن

- **هرگز** اغراق نکن! طبیعی و ساده جواب بده
- ❌ نگو: "فدات بشم"، "دلم برات تنگ شده"، "عاشقتم"، "خوشم میاد رک حرف میزنی"
- ❌ نگو: "کارت درسته رفیق!"، "ایول!"، "دمت گرم!" (مگر اینکه طرف اول گفته باشه)
- ✅ بگو: "سلام"، "خوبم"، "باشه"، "اوکی"، "چطوری"
- مثل یه آدم واقعی که داره پیام میده جواب بده، نه مثل یه ربات که میخواد خوشحالت کنه
- اگه همسری → نیاز نیست هر پیام عاشقانه باشه، ساده و روزمره حرف بزن
- اگه دوستی → نیاز نیست هر پیام "داداش‌بازی" باشه، عادی حرف بزن


User: "سلام"
You: "سلام" یا "سلام، چطوری؟"

User: "چیکار می‌کنی؟"
You: "هیچی" یا "سرکارم" یا "دارم استراحت میکنم"

User: "خوبی؟"
You: "آره خوبم، تو چطوری؟"

User: "کجایی؟"
You: "خونه‌ام" یا "سرکار"

User (همسر): "سلام عزیزم"
You: "سلام" یا "سلام، چطوری؟" [ساده، بدون اغراق]

User (دوست): "سلام داداش"
You: "سلام" یا "چطوری؟" [ساده، بدون داداش‌بازی]

⚠️ توجه: پاسخ‌ها باید کوتاه و طبیعی باشند، مثل پیام‌های واقعی در تلگرام/واتساپ
"""

    def _get_creator_instructions(self, language: str, is_new_user: bool = False) -> str:
        lang_directive = self._language_directive(language)
        
        if is_new_user:
            return f"""You are meeting this user for the FIRST TIME.

- NOT formal/stiff (avoid: "متوجه شدم", "چه چیز دیگری باید بدانم")
- NOT too casual/slang (avoid: "رفیق", "داداش", "ایول")
- Just natural and polite like a normal person


1. Keep it simple and natural
2. 1-2 sentences max
3. No emojis overload (max 1 per message, or none)
4. Language: {lang_directive}


User: "سلام"
You: "سلام! حالت خوبه؟ اسمت چیه؟"

User: "خوبی؟"
You: "ممنون، خوبم. شما؟ راستی اسمتون چیه؟"

User: "علی هستم"
You: "خوشبختم علی. چیکار می‌کنی؟"

User: "مهندسم"
You: "چه جالب. چه نوع مهندسی؟"
"""
        
        return f"""You help build a user's profile through natural conversation.

- NOT formal/stiff (NEVER use: "متوجه شدم", "چه چیز دیگری باید بدانم", "اطلاعات بیشتری")
- NOT too casual/slang (avoid: "رفیق", "داداش", "ایول", "دمت گرم")
- Just natural and polite, like a normal friendly person
- Responses should feel like real human conversation

- CURRENT PROFILE: What you already know about them
- RECENT CONVERSATION: Previous messages (check before responding!)

1. **NO DUPLICATE QUESTIONS**: Check history - NEVER ask something already answered
2. **TOPIC ROTATION**: After 4-5 follow-ups on same topic, switch naturally
3. **Variety**: Cover work, family, hobbies, daily routine, likes/dislikes
4. Info shared → short acknowledgment + ONE follow-up
5. User refuses → respect, change topic
6. 1-2 sentences max
7. Minimal emojis (max 1 per message, or none)
8. Language: {lang_directive}

- Work (شغل، ساعات کاری، روزهای کاری، شیفت)
- Family
- Hobbies
- Daily routine (کی بیدار میشی، کی میخوابی)
- Likes/dislikes


User: "سلام"
You: "سلام! خوبی؟"

User: "خوبم"
You: "چه خبر؟ امروز چیکار کردی؟"

User: "مهندسم"
You: "چه جالب. چه حوزه‌ای؟"

User: "نرم‌افزار"
You: "کجا کار می‌کنی؟"

User: "تو یه استارتاپ"
You: "چند وقته اونجایی؟"

User: "۸ تا ۵ کار می‌کنم"
You: "چه روزهایی میری؟"

User: "شنبه تا چهارشنبه"
You: "خوبه. بیرون از کار چیکار دوست داری؟"

User: "شیفتی کار می‌کنم"
You: "شیفت صبح یا عصر؟"

User: "نمی‌خوام بگم"
You: "باشه. چه موسیقی‌ای گوش میدی؟"

User: "منو می‌شناسی؟"
You: "آره، مهندس نرم‌افزاری تو یه استارتاپ." [if profile has info]
You: "هنوز نه، چیکاره‌ای؟" [if empty]"""

    @staticmethod
    def _normalize_language(language: str | None) -> str:
        lang = (language or "fa").strip().lower()
        return lang or "fa"

    def _language_directive(self, language: str) -> str:
        lang = self._normalize_language(language)
        pretty_map = {
            "fa": "Persian (Farsi)",
            "en": "English",
        }
        pretty = pretty_map.get(lang, lang)
        return f"{pretty} (code: {lang})"

    @staticmethod
    def _localize_text(key: str, language: str) -> str:
        lang = (language or "fa").strip().lower() or "fa"
        translations: dict[str, dict[str, str]] = {
            "chat_blocked": {
                "fa": "به دلیل ملاحظات ایمنی نمی‌توانم به این پیام پاسخ بدهم.",
                "en": "I can't respond to that request due to safety concerns.",
            },
            "chat_empty_response": {
                "fa": "مرسی از پیامت! به زودی جواب می‌دهم.",
                "en": "Thanks for your message! I'll get back to you soon.",
            },
            "chat_error_response": {
                "fa": "مرسی از پیامت! به زودی جواب می‌دهم.",
                "en": "Thanks for your message! I'll get back to you soon.",
            },
            "creator_blocked": {
                "fa": "نمی‌توانم این درخواست را پردازش کنم. لطفاً اطلاعات مرتبط با پروفایل بده.",
                "en": "I can't process that request. Please share profile-related information.",
            },
            "creator_empty_response": {
                "fa": "متوجه شدم! بیشتر برام بگو.",
                "en": "Got it! Tell me more.",
            },
            "creator_error_response": {
                "fa": "در پردازش اطلاعات با مشکل رو به رو شده ام.",
                "en": "I faced with processing the information.",
            },
        }
        bucket = translations.get(key, {})
        return bucket.get(lang) or bucket.get("fa") or bucket.get("en") or ""


    async def _check_and_handle_future_planning(
        self,
        sender_id: str,
        recipient_id: str,
        conversation_id: str,
        sender_message: str,
        recent_events: list[dict[str, Any]],
        twin_name: str,
        language: str,
    ) -> str | None:
        if self._future_detector is None or self._future_requests is None:
            logger.warning(
                "orchestrator:future_planning:components_not_available",
                extra={
                    "has_detector": self._future_detector is not None,
                    "has_store": self._future_requests is not None,
                },
            )
            return None
        
        try:
            context = [e.get("text", "") for e in recent_events[-5:] if e.get("text")]
            
            result = await self._future_detector.detect(
                message=sender_message,
                sender_id=sender_id,
                recipient_id=recipient_id,
                context=context,
            )
            
            if not result.is_future_planning:
                return None
            
            if result.confidence < 0.7:
                logger.info(
                    "orchestrator:future_planning:low_confidence",
                    extra={
                        "sender_id": sender_id,
                        "recipient_id": recipient_id,
                        "confidence": result.confidence,
                        "detected_plan": result.detected_plan,
                    },
                )
                return None
            
            request_id = await self._future_requests.create_request(
                sender_id=sender_id,
                recipient_id=recipient_id,
                conversation_id=conversation_id,
                original_message=sender_message,
                detected_plan=result.detected_plan,
                detected_datetime=result.detected_datetime,
            )
            
            logger.info(
                "orchestrator:future_planning:request_created",
                extra={
                    "request_id": request_id,
                    "sender_id": sender_id,
                    "recipient_id": recipient_id,
                    "detected_plan": result.detected_plan,
                    "detected_datetime": result.detected_datetime,
                    "confidence": result.confidence,
                },
            )
            
            try:
                from api.routers.websocket_notifications import notify_future_request_to_creator
                
                await notify_future_request_to_creator(
                    creator_id=recipient_id,
                    sender_id=sender_id,
                    sender_name=None,
                    request_id=request_id,
                    original_message=sender_message,
                    detected_plan=result.detected_plan,
                    detected_datetime=result.detected_datetime,
                )
            except Exception as ws_error:
                logger.warning(
                    "orchestrator:future_planning:ws_notification_failed",
                    extra={"error": str(ws_error)},
                )
            
            acknowledgment = await self._future_detector.generate_acknowledgment_response(
                detected_plan=result.detected_plan,
                detected_datetime=result.detected_datetime,
                twin_name=twin_name,
                language=language,
            )
            
            return acknowledgment
            
        except Exception as e:
            logger.error(
                "orchestrator:future_planning:error",
                extra={
                    "sender_id": sender_id,
                    "recipient_id": recipient_id,
                    "error": str(e),
                },
                exc_info=True,
            )
            return None

    async def _check_and_deliver_creator_responses(
        self,
        sender_id: str,
        recipient_id: str,
        twin_name: str,
        language: str,
    ) -> str | None:
        if self._future_requests is None:
            return None
        
        try:
            undelivered = await self._future_requests.get_undelivered_responses_for_sender(
                sender_id=sender_id,
                recipient_id=recipient_id,
            )
            
            if not undelivered:
                return None
            
            responses: list[str] = []
            for req in undelivered:
                if req.creator_response:
                    if language == "fa":
                        response_text = f"📬 درباره درخواستت ({req.detected_plan}):\n{twin_name} گفت: {req.creator_response}"
                    else:
                        response_text = f"📬 About your request ({req.detected_plan}):\n{twin_name} said: {req.creator_response}"
                    responses.append(response_text)
                    
                    await self._future_requests.mark_as_delivered(req.id)
                    
                    logger.info(
                        "orchestrator:future_planning:response_delivered",
                        extra={
                            "request_id": req.id,
                            "sender_id": sender_id,
                            "recipient_id": recipient_id,
                        },
                    )
            
            if responses:
                return "\n\n".join(responses)
            
            return None
            
        except Exception as e:
            logger.error(
                "orchestrator:future_planning:deliver_error",
                extra={
                    "sender_id": sender_id,
                    "recipient_id": recipient_id,
                    "error": str(e),
                },
                exc_info=True,
            )
            return None


    async def _check_and_handle_financial_thread(
        self,
        sender_id: str,
        creator_id: str,
        conversation_id: str,
        sender_message: str,
        recent_events: list[dict[str, Any]],
        twin_name: str,
        language: str,
    ) -> str | None:
        if self._financial_detector is None or self._financial_threads is None:
            logger.warning(
                "orchestrator:financial_thread:components_not_available",
                extra={
                    "has_detector": self._financial_detector is not None,
                    "has_store": self._financial_threads is not None,
                },
            )
            return None
        
        try:
            active_thread = await self._financial_threads.get_active_thread(
                sender_id=sender_id,
                creator_id=creator_id,
            )
            
            if active_thread:
                thread_response = await self._handle_active_financial_thread(
                    thread=active_thread,
                    sender_message=sender_message,
                    twin_name=twin_name,
                    language=language,
                )
                if thread_response is not None:
                    return thread_response
                logger.info(
                    "orchestrator:financial_thread:not_continuation_checking_new",
                    extra={"sender_id": sender_id, "existing_thread_id": active_thread.id},
                )
            context = [e.get("text", "") for e in recent_events[-5:] if e.get("text")]
            
            result = await self._financial_detector.detect(
                message=sender_message,
                sender_id=sender_id,
                creator_id=creator_id,
                context=context,
            )
            
            logger.info(
                "orchestrator:financial_thread:detect_result",
                extra={
                    "sender_id": sender_id,
                    "message_preview": sender_message[:50],
                    "is_financial": result.is_financial,
                    "confidence": result.confidence,
                    "topic_summary": result.topic_summary,
                    "reason": result.reason,
                },
            )
            
            if not result.is_financial:
                return None
            
            if result.confidence < 0.7:
                logger.info(
                    "orchestrator:financial_thread:low_confidence",
                    extra={
                        "sender_id": sender_id,
                        "creator_id": creator_id,
                        "confidence": result.confidence,
                        "topic_summary": result.topic_summary,
                    },
                )
                return None
            
            thread_id = await self._financial_threads.create_thread(
                sender_id=sender_id,
                creator_id=creator_id,
                conversation_id=conversation_id,
                topic_summary=result.topic_summary,
                initial_message=sender_message,
            )
            
            logger.info(
                "orchestrator:financial_thread:created",
                extra={
                    "thread_id": thread_id,
                    "sender_id": sender_id,
                    "creator_id": creator_id,
                    "topic_summary": result.topic_summary,
                    "confidence": result.confidence,
                },
            )
            
            try:
                from api.routers.websocket_notifications import notify_financial_topic_to_creator
                
                await notify_financial_topic_to_creator(
                    creator_id=creator_id,
                    sender_id=sender_id,
                    thread_id=thread_id,
                    original_message=sender_message,
                    topic_summary=result.topic_summary,
                    amount=result.amount,
                )
            except ImportError:
                logger.warning("orchestrator:financial_thread:ws_import_failed")
            except Exception as ws_error:
                logger.warning(
                    "orchestrator:financial_thread:ws_notification_failed",
                    extra={"error": str(ws_error)},
                )
            
            acknowledgment = await self._financial_detector.generate_acknowledgment(
                topic_summary=result.topic_summary,
                creator_name=twin_name,
                language=language,
            )
            
            return acknowledgment
            
        except Exception as e:
            logger.error(
                "orchestrator:financial_thread:error",
                extra={
                    "sender_id": sender_id,
                    "creator_id": creator_id,
                    "error": str(e),
                },
                exc_info=True,
            )
            return None

    async def _handle_active_financial_thread(
        self,
        thread: "FinancialThread",
        sender_message: str,
        twin_name: str,
        language: str,
    ) -> str | None:
        recent_messages = await self._financial_threads.get_recent_messages(
            thread_id=thread.id,
            limit=5,
        )
        
        if thread.waiting_for == WaitingFor.CREATOR:
            undelivered = await self._financial_threads.get_undelivered_messages(
                thread_id=thread.id,
                for_author_type="sender",
            )
            
            if undelivered:
                responses = []
                for msg in undelivered:
                    delivery_msg = await self._financial_detector.generate_delivery_message(
                        creator_response=msg.message,
                        topic_summary=thread.topic_summary,
                        creator_name=twin_name,
                        language=language,
                    )
                    responses.append(delivery_msg)
                    await self._financial_threads.mark_message_delivered(msg.id)
                
                continuation = await self._financial_detector.check_continuation(
                    message=sender_message,
                    thread=thread,
                    recent_messages=recent_messages,
                )
                
                if continuation.is_continuation and continuation.confidence >= 0.7:
                    await self._financial_threads.add_message(
                        thread_id=thread.id,
                        author_type="sender",
                        message=sender_message,
                    )
                    
                    try:
                        from api.routers.websocket_notifications import notify_financial_message_to_creator
                        await notify_financial_message_to_creator(
                            creator_id=thread.creator_id,
                            sender_id=thread.sender_id,
                            thread_id=thread.id,
                            message=sender_message,
                        )
                    except Exception:
                        pass
                    
                    responses.append(f"پیامتو هم به {twin_name} رسوندم. ⏳")
                
                return "\n\n".join(responses)
            
            continuation = await self._financial_detector.check_continuation(
                message=sender_message,
                thread=thread,
                recent_messages=recent_messages,
            )
            
            if continuation.is_continuation and continuation.confidence >= 0.7:
                await self._financial_threads.add_message(
                    thread_id=thread.id,
                    author_type="sender",
                    message=sender_message,
                )
                
                try:
                    from api.routers.websocket_notifications import notify_financial_message_to_creator
                    await notify_financial_message_to_creator(
                        creator_id=thread.creator_id,
                        sender_id=thread.sender_id,
                        thread_id=thread.id,
                        message=sender_message,
                    )
                except Exception:
                    pass
                
                return await self._financial_detector.generate_pending_response(
                    topic_summary=thread.topic_summary,
                    creator_name=twin_name,
                    language=language,
                )
            
            return None
        
        elif thread.waiting_for == WaitingFor.SENDER:
            continuation = await self._financial_detector.check_continuation(
                message=sender_message,
                thread=thread,
                recent_messages=recent_messages,
            )
            
            if continuation.is_closure and continuation.confidence >= 0.7:
                await self._financial_threads.update_thread_status(
                    thread_id=thread.id,
                    new_status=FinancialThreadStatus.RESOLVED,
                )
                logger.info(
                    "orchestrator:financial_thread:resolved_by_llm",
                    extra={"thread_id": thread.id},
                )
                return None
            
            if continuation.is_continuation and continuation.confidence >= 0.7:
                question_indicators = ['چی گفت', 'چه گفت', 'جوابش چی', 'جواب چی', 'جوابش چیه', 'جواب داد']
                is_question = any(q in sender_message for q in question_indicators)
                
                if is_question:
                    logger.info(
                        "orchestrator:financial_thread:question_detected",
                        extra={
                            "thread_id": thread.id,
                            "sender_msg": sender_message[:50],
                            "last_owner_response": thread.last_creator_response[:50] if thread.last_creator_response else None,
                        },
                    )
                    return None
                
                await self._financial_threads.add_message(
                    thread_id=thread.id,
                    author_type="sender",
                    message=sender_message,
                )
                
                try:
                    from api.routers.websocket_notifications import notify_financial_message_to_creator
                    await notify_financial_message_to_creator(
                        creator_id=thread.creator_id,
                        sender_id=thread.sender_id,
                        thread_id=thread.id,
                        message=sender_message,
                    )
                except Exception:
                    pass
                
                if language == "fa":
                    return f"پیامت رو به {twin_name} رسوندم. 📨"
                else:
                    return f"I've forwarded your message to {twin_name}. 📨"
            
            return None
        
        return None

    async def _deliver_financial_thread_responses(
        self,
        sender_id: str,
        creator_id: str,
        twin_name: str,
        language: str,
    ) -> str | None:
        if self._financial_threads is None or self._financial_detector is None:
            logger.debug(
                "orchestrator:financial_thread:deliver:skip",
                extra={"reason": "financial_threads or detector is None"},
            )
            return None
        
        try:
            active_thread = await self._financial_threads.get_active_thread(
                sender_id=sender_id,
                creator_id=creator_id,
            )
            
            logger.debug(
                "orchestrator:financial_thread:deliver:active_thread_check",
                extra={
                    "sender_id": sender_id,
                    "creator_id": creator_id,
                    "has_active_thread": active_thread is not None,
                    "thread_id": active_thread.id if active_thread else None,
                },
            )
            
            if not active_thread:
                return None
            
            undelivered = await self._financial_threads.get_undelivered_messages(
                thread_id=active_thread.id,
                for_author_type="sender",
            )
            
            logger.info(
                "orchestrator:financial_thread:deliver:undelivered_check",
                extra={
                    "thread_id": active_thread.id,
                    "undelivered_count": len(undelivered) if undelivered else 0,
                },
            )
            
            if not undelivered:
                return None
            
            responses = []
            for msg in undelivered:
                delivery_msg = await self._financial_detector.generate_delivery_message(
                    creator_response=msg.message,
                    topic_summary=active_thread.topic_summary,
                    creator_name=twin_name,
                    language=language,
                )
                responses.append(delivery_msg)
                await self._financial_threads.mark_message_delivered(msg.id)
                
                logger.info(
                    "orchestrator:financial_thread:response_delivered",
                    extra={
                        "thread_id": active_thread.id,
                        "message_id": msg.id,
                        "sender_id": sender_id,
                    },
                )
            
            if responses:
                return "\n\n".join(responses)
            
            return None
            
        except Exception as e:
            logger.error(
                "orchestrator:financial_thread:deliver_error",
                extra={
                    "sender_id": sender_id,
                    "creator_id": creator_id,
                    "error": str(e),
                },
                exc_info=True,
            )
            return None
