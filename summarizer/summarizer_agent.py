
from __future__ import annotations

import logging
import traceback
from dataclasses import dataclass, field
from typing import Any, List, Sequence, Optional, Dict

from openai import AsyncOpenAI
import tiktoken

from pydantic import BaseModel

from config.settings import Settings
from observability.phoenix_setup import record_llm_tokens

logger = logging.getLogger(__name__)


@dataclass
class SummaryWithFacts:
    summary_text: str
    clean_summary: str
    high_priority_facts: List[Dict] = field(default_factory=list)
    medium_priority_facts: List[Dict] = field(default_factory=list)
    low_priority_facts: List[Dict] = field(default_factory=list)


class SummaryOutput(BaseModel):

    summary: str | None = None


class SummarizerAgent:

    DEFAULT_MAX_INPUT_CHARS: int = 12000
    DEFAULT_MAX_WORDS: int = 120
    MAX_SUMMARY_TOKENS: int = 1000

    def __init__(self, settings: Settings, openai_client: AsyncOpenAI):
        self._settings = settings
        self._client = openai_client

        self._model_name = getattr(settings, "SUMMARIZER_MODEL", "gpt-4o-mini")
        if not self._model_name:
            logger.warning("SUMMARIZER_MODEL not found in settings, using default 'gpt-4o-mini'")
            self._model_name = "gpt-4o-mini"

        self._max_input_chars = int(
            getattr(settings, "SUMMARY_MAX_INPUT_CHARS", self.DEFAULT_MAX_INPUT_CHARS)
        )
        self._default_max_words = int(
            getattr(settings, "SUMMARY_MAX_WORDS", self.DEFAULT_MAX_WORDS)
        )

        try:
            self._tokenizer = tiktoken.encoding_for_model(self._model_name)
        except KeyError:
            self._tokenizer = tiktoken.get_encoding("cl100k_base")
            logger.warning(f"Using fallback tokenizer cl100k_base for model {self._model_name}")

        logger.info(f"SummarizerAgent initialized to use model: {self._model_name}")


    async def summarize_messages(
        self, *, texts: Sequence[str], max_words: int | None = None
    ) -> str:
        msg_list: list[str] = [str(t) for t in texts] if texts else []
        return await self.summarize(
            messages=msg_list, max_words=(max_words or self._default_max_words)
        )

    async def summarize_per_user(
        self,
        *,
        previous_summary: Optional[str],
        messages_with_authors: List[tuple[str, str]],
        user_a_id: str,
        user_b_id: str,
    ) -> str:
        if not messages_with_authors:
            return previous_summary or f"{user_a_id}: بدون پیام. {user_b_id}: بدون پیام."

        messages_a = [text for author, text in messages_with_authors if author == user_a_id]
        messages_b = [text for author, text in messages_with_authors if author == user_b_id]

        system_prompt = f"""شما یک دستیار خلاصه‌سازی هستید. مکالمه‌ای بین دو کاربر ({user_a_id} و {user_b_id}) دارید.

**وظیفه:**
برای هر کاربر جداگانه، پیام‌هایش را خلاصه کنید.

**فرمت خروجی (دقیقاً به این شکل):**
{user_a_id}: خلاصه پیام‌های {user_a_id} به فارسی.
{user_b_id}: خلاصه پیام‌های {user_b_id} به فارسی.

**قوانین:**
- خلاصه به **فارسی**
- برای هر کاربر، فقط محتوای پیام‌هایش را خلاصه کنید
- مختصر و مفید
- اگر خلاصه قبلی وجود دارد، آن را با پیام‌های جدید ادغام کنید
- حداکثر طول کل: ۸۰۰ کلمه

فقط دو خط خروجی (یکی برای هر کاربر) برگردانید."""

        parts = []

        if previous_summary and previous_summary.strip():
            parts.append(f"**خلاصه قبلی:**\n{previous_summary.strip()}\n")

        if messages_a:
            msgs_a = "\n".join(f"- {m}" for m in messages_a[:50])
            parts.append(f"**پیام‌های جدید {user_a_id}:**\n{msgs_a}\n")

        if messages_b:
            msgs_b = "\n".join(f"- {m}" for m in messages_b[:50])
            parts.append(f"**پیام‌های جدید {user_b_id}:**\n{msgs_b}\n")

        user_prompt = (
            "\n".join(parts) + f"\n\nخلاصه جدید (فرمت: {user_a_id}: ... {user_b_id}: ...):"
        )

        try:
            logger.info(
                "summarizer:summarize_per_user:calling_openai",
                extra={
                    "has_prev": bool(previous_summary),
                    "msgs_a": len(messages_a),
                    "msgs_b": len(messages_b),
                },
            )

            llm_kwargs: dict = {
                "model": self._model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": getattr(self._settings, "SUMMARIZER_TEMPERATURE", 0.2),
                "max_tokens": getattr(self._settings, "SUMMARIZER_MAX_TOKENS", 1200),
            }
            top_p = getattr(self._settings, "SUMMARIZER_TOP_P", None)
            if top_p is not None:
                llm_kwargs["top_p"] = top_p
            
            response = await self._client.chat.completions.create(**llm_kwargs)
            
            summary = (response.choices[0].message.content or "").strip()

            if response.usage:
                record_llm_tokens(
                    agent_name="summarizer",
                    model=llm_kwargs.get("model", "unknown"),
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    input_messages=llm_kwargs.get("messages"),
                    output_message=summary,
                )

            if not summary:
                logger.warning("summarizer:summarize_per_user:empty_response")
                return (
                    previous_summary
                    or f"{user_a_id}: خلاصه موجود نیست. {user_b_id}: خلاصه موجود نیست."
                )

            trimmed = self._trim_to_token_limit(summary, self.MAX_SUMMARY_TOKENS)

            logger.info(
                "summarizer:summarize_per_user:success",
                extra={
                    "tokens": self._count_tokens(trimmed),
                    "chars": len(trimmed),
                },
            )

            return trimmed

        except Exception as e:
            logger.error(
                "summarizer:summarize_per_user:error",
                extra={"error": str(e)},
                exc_info=True,
            )
            return (
                previous_summary or f"{user_a_id}: خطا در خلاصه‌سازی. {user_b_id}: خطا در خلاصه‌سازی."
            )

    async def summarize_with_facts(
        self,
        *,
        previous_summary: Optional[str],
        messages_with_authors: List[tuple[str, str]],
        user_a_id: str,
        user_b_id: str,
        extract_facts: bool = True,
    ) -> SummaryWithFacts:
        logger.info(
            "summarizer:summarize_with_facts:start",
            extra={
                "user_a": user_a_id,
                "user_b": user_b_id,
                "message_count": len(messages_with_authors),
                "has_previous": bool(previous_summary),
                "extract_facts": extract_facts,
            },
        )
        
        summary_text = await self.summarize_per_user(
            previous_summary=previous_summary,
            messages_with_authors=messages_with_authors,
            user_a_id=user_a_id,
            user_b_id=user_b_id,
        )
        
        if not extract_facts or not summary_text:
            logger.info(
                "summarizer:summarize_with_facts:skip_extraction",
                extra={
                    "user_a": user_a_id,
                    "user_b": user_b_id,
                    "reason": "extract_facts=False" if not extract_facts else "empty_summary",
                },
            )
            return SummaryWithFacts(
                summary_text=summary_text,
                clean_summary=summary_text,
            )
        
        try:
            from summarizer.core_fact_extractor import CoreFactExtractor
            
            extractor = CoreFactExtractor(
                settings=self._settings,
                openai_client=self._client,
            )
            
            result = await extractor.extract_facts(
                text=summary_text,
                user_a=user_a_id,
                user_b=user_b_id,
            )
            
            logger.info(
                "summarizer:summarize_with_facts:success",
                extra={
                    "user_a": user_a_id,
                    "user_b": user_b_id,
                    "summary_length": len(summary_text),
                    "clean_summary_length": len(result.clean_summary or ""),
                    "high_facts": len(result.high_priority),
                    "medium_facts": len(result.medium_priority),
                    "low_facts_discarded": len(result.low_priority),
                },
            )
            
            return SummaryWithFacts(
                summary_text=summary_text,
                clean_summary=result.clean_summary or summary_text,
                high_priority_facts=[f.to_dict() for f in result.high_priority],
                medium_priority_facts=[f.to_dict() for f in result.medium_priority],
                low_priority_facts=[f.to_dict() for f in result.low_priority],
            )
            
        except Exception as e:
            logger.error(
                "summarizer:summarize_with_facts:extract_error",
                extra={
                    "user_a": user_a_id,
                    "user_b": user_b_id,
                    "error": str(e),
                    "error_type": type(e).__name__,
                },
                exc_info=True,
            )
            logger.warning(
                "summarizer:summarize_with_facts:fallback_no_facts",
                extra={"user_a": user_a_id, "user_b": user_b_id},
            )
            return SummaryWithFacts(
                summary_text=summary_text,
                clean_summary=summary_text,
            )

    async def summarize(
        self,
        messages: list[str],
        max_words: int = 120,
    ) -> str:

        if not messages:
            logger.warning("summarizer:summarize:received_empty_messages_list_skipping")
            return ""

        message_texts = [str(msg).strip() for msg in messages if msg and str(msg).strip()]
        if not message_texts:
            logger.warning("summarizer:summarize:no_valid_non_empty_messages_found_skipping")
            return ""

        message_texts = self._clamp_by_chars(message_texts, budget_chars=self._max_input_chars)

        lang_hint = self._detect_lang_hint(message_texts)

        logger.info(
            "summarizer:summarize:start_processing",
            extra={
                "input_message_count": len(message_texts),
                "max_words": max_words,
                "char_budget": self._max_input_chars,
                "lang_hint": lang_hint,
            },
        )

        system_prompt = self._get_instructions(lang_hint=lang_hint)
        try:
            convo = "\n".join(f"{i+1}. {m}" for i, m in enumerate(message_texts))
            user_prompt = f"""Conversation ({len(message_texts)} messages):
{convo}

Summarize in ONE paragraph under {max_words} words."""
            logger.debug(
                "summarizer:summarize:prepared_prompts_for_api",
                extra={
                    "user_prompt_length": len(user_prompt),
                    "user_prompt_preview": user_prompt[:500]
                    + ("..." if len(user_prompt) > 500 else ""),
                    "system_prompt_length": len(system_prompt),
                    "target_model": self._model_name,
                },
            )

        except Exception as format_exc:
            logger.error(
                "summarizer:summarize:prompt_formatting_failed",
                extra={"error": str(format_exc)},
                exc_info=True,
            )
            return f"Error formatting summary prompt for {len(message_texts)} messages."

        summary = ""
        try:
            logger.info(
                f"summarizer:summarize:calling_openai_chat_completions_api_model={self._model_name}"
            )
            llm_kwargs: dict = {
                "model": self._model_name,
                "messages": [
                    {"role": "system", "content": system_prompt},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": getattr(self._settings, "SUMMARIZER_TEMPERATURE", 0.2),
                "max_tokens": max(64, min(max_words + 80, 512)),
                "n": 1,
                "stop": None,
            }
            top_p = getattr(self._settings, "SUMMARIZER_TOP_P", None)
            if top_p is not None:
                llm_kwargs["top_p"] = top_p
            
            response = await self._client.chat.completions.create(**llm_kwargs)

            logger.info("summarizer:summarize:openai_api_call_finished")

            summary = ""
            if response.choices:
                first_choice = response.choices[0]
                if getattr(first_choice, "message", None) and getattr(
                    first_choice.message, "content", None
                ):
                    summary = first_choice.message.content.strip()
                    logger.info(f"summarizer:summarize:extracted_summary_len={len(summary)}")
                else:
                    logger.warning(
                        "summarizer:summarize:api_response_choice_message_or_content_is_empty"
                    )
            else:
                logger.warning("summarizer:summarize:api_response_contained_no_choices")

            if response.usage:
                record_llm_tokens(
                    agent_name="summarizer",
                    model=llm_kwargs.get("model", "unknown"),
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    input_messages=llm_kwargs.get("messages"),
                    output_message=summary,
                )

            if not summary:
                logger.warning(
                    "summarizer:summarize:llm_resulted_in_empty_summary_string_after_extraction"
                )
                return f"Summary generation yielded empty result for {len(message_texts)} messages."

            logger.info(
                "summarizer:summarize:execution_done_with_summary",
                extra={
                    "input_count": len(message_texts),
                    "output_summary_len": len(summary),
                    "summary_preview": summary[:100] + ("..." if len(summary) > 100 else ""),
                },
            )
            return summary

        except Exception as e:
            detailed_error = traceback.format_exc()
            logger.error(
                "summarizer:summarize:error_during_openai_api_call_or_processing",
                extra={
                    "error": str(e),
                    "error_type": type(e).__name__,
                    "traceback": detailed_error,
                    "model_used": self._model_name,
                    "user_prompt_preview": user_prompt[:200]
                    + ("..." if len(user_prompt) > 200 else ""),
                },
            )
            return f"Failed to generate summary for {len(message_texts)} messages due to API or processing error."

    
    PROTECTED_INFO_PATTERNS = [
        (r"(?:نام|اسم)\s*[:\s]+[\u0600-\u06FF\w]+", "نام"),
        (r"(?:سن|سال)\s*[:\s]+\d+", "سن"),
        (r"(?:شهر|محل زندگی|ساکن)\s*[:\s]+[\u0600-\u06FF\w]+", "شهر"),
        (r"(?:شغل|کار|حرفه)\s*[:\s]+[\u0600-\u06FF\w\s]+", "شغل"),
        (r"(?:name)\s*[:\s]+\w+", "name"),
        (r"(?:age)\s*[:\s]+\d+", "age"),
        (r"(?:city|location|lives? in)\s*[:\s]+\w+", "city"),
        (r"(?:job|work|profession)\s*[:\s]+[\w\s]+", "job"),
        (r"\b\d{1,3}\s*(?:ساله|سالش|years? old)\b", "age"),
    ]
    
    def _extract_protected_info(self, text: str) -> list[str]:
        import re
        protected = []
        
        for pattern, label in self.PROTECTED_INFO_PATTERNS:
            matches = re.findall(pattern, text, re.IGNORECASE)
            for match in matches:
                if match.strip() and match.strip() not in protected:
                    protected.append(match.strip())
        
        return protected
    
    def _merge_protected_info(self, trimmed_text: str, protected_info: list[str]) -> str:
        if not protected_info:
            return trimmed_text
        
        missing = []
        for info in protected_info:
            if info.lower() not in trimmed_text.lower():
                missing.append(info)
        
        if not missing:
            return trimmed_text
        
        protected_block = "[اطلاعات کلیدی: " + " | ".join(missing) + "] "
        
        logger.info(
            "summarizer:merge_protected:restored",
            extra={"restored_count": len(missing), "items": missing},
        )
        
        return protected_block + trimmed_text

    def _count_tokens(self, text: str) -> int:
        try:
            return len(self._tokenizer.encode(text))
        except Exception:
            return len(text) // 4

    def _trim_to_token_limit(self, text: str, max_tokens: int) -> str:
        try:
            tokens = self._tokenizer.encode(text)
            if len(tokens) <= max_tokens:
                return text

            protected_info = self._extract_protected_info(text)
            
            trimmed_tokens = tokens[-max_tokens:]
            trimmed_text = self._tokenizer.decode(trimmed_tokens)
            
            final_text = self._merge_protected_info(trimmed_text, protected_info)

            logger.info(
                "summarizer:trim:truncated",
                extra={
                    "original": len(tokens), 
                    "trimmed": len(trimmed_tokens),
                    "protected_count": len(protected_info),
                },
            )
            return final_text
        except Exception as e:
            logger.error(f"Error trimming text: {e}")
            max_chars = max_tokens * 4
            if len(text) <= max_chars:
                return text
            return text[-max_chars:]

    @staticmethod
    def _is_persian_text(s: str) -> bool:
        for ch in s:
            if (
                "\u0600" <= ch <= "\u06ff"
                or "\u0750" <= ch <= "\u077f"
                or "\u08a0" <= ch <= "\u08ff"
            ):
                return True
        return False

    def _detect_lang_hint(self, texts: Sequence[str]) -> str:
        if not texts:
            return "en"
        joined = " ".join(texts)
        return "fa" if self._is_persian_text(joined) else "en"

    def _clamp_by_chars(self, messages: Sequence[str], budget_chars: int) -> list[str]:
        if budget_chars <= 0:
            return list(messages)

        total = 0
        kept: list[str] = []
        for m in reversed(messages):
            ln = len(m)
            if total + ln > budget_chars and kept:
                break
            kept.append(m)
            total += ln
        kept.reverse()
        return kept

    @staticmethod
    def _get_instructions(*, lang_hint: str = "en") -> str:
        if lang_hint == "fa":
            return """You are a concise summarization assistant.

Summarize the provided conversation in ONE paragraph in **Persian**.
Include goals, decisions, blockers, and next steps if present.

Requirements:
- NO bullet points, lists, or quotation marks
- Keep it under the specified word limit
- Make it coherent and self-contained
- Focus on key information

Return only the summary paragraph, nothing else."""
        else:
            return """You are a concise summarization assistant.

Summarize the provided conversation in ONE paragraph.
Include goals, decisions, blockers, and next steps if present.

Requirements:
- NO bullet points, lists, or quotation marks
- Keep it under the specified word limit
- Make it coherent and self-contained
- Focus on key information

Return only the summary paragraph, nothing else."""
