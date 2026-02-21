
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional, List, TYPE_CHECKING

from openai import AsyncOpenAI

if TYPE_CHECKING:
    from config.settings import Settings
    from db.postgres_financial_threads import FinancialThread, FinancialThreadMessage

logger = logging.getLogger(__name__)


@dataclass
class FinancialDetectionResult:
    is_financial: bool
    topic_summary: str
    amount: Optional[str]
    urgency: str
    confidence: float
    reason: str


@dataclass
class ThreadContinuationResult:
    is_continuation: bool
    is_closure: bool
    confidence: float
    reason: str


class FinancialTopicDetector:

    def __init__(
        self,
        openai_client: AsyncOpenAI,
        settings: "Settings",
    ):
        self._client = openai_client
        self._settings = settings
        self._model = getattr(settings, "AGENTS_MODEL", "gpt-4o-mini")
        logger.info("financial_topic_detector:init:success")


    async def detect(
        self,
        message: str,
        sender_id: str,
        creator_id: str,
        context: Optional[List[str]] = None,
    ) -> FinancialDetectionResult:
        try:
            result = await self._llm_detect_financial(message, context)
            
            logger.info(
                "financial_topic_detector:detect:result",
                extra={
                    "sender_id": sender_id,
                    "creator_id": creator_id,
                    "message_preview": message[:50],
                    "is_financial": result.is_financial,
                    "confidence": result.confidence,
                    "topic_summary": result.topic_summary[:100] if result.topic_summary else "",
                },
            )
            
            return result
            
        except Exception as e:
            logger.error(
                "financial_topic_detector:detect:error",
                extra={
                    "sender_id": sender_id,
                    "creator_id": creator_id,
                    "error": str(e),
                },
                exc_info=True,
            )
            
            return FinancialDetectionResult(
                is_financial=False,
                topic_summary="",
                amount=None,
                urgency="normal",
                confidence=0.0,
                reason="llm_error",
            )

    async def check_continuation(
        self,
        message: str,
        thread: "FinancialThread",
        recent_messages: List["FinancialThreadMessage"],
    ) -> ThreadContinuationResult:
        try:
            result = await self._llm_check_continuation(message, thread, recent_messages)
            
            logger.info(
                "financial_topic_detector:check_continuation:result",
                extra={
                    "thread_id": thread.id,
                    "is_continuation": result.is_continuation,
                    "is_closure": result.is_closure,
                    "confidence": result.confidence,
                },
            )
            
            return result
            
        except Exception as e:
            logger.error(
                "financial_topic_detector:check_continuation:error",
                extra={"thread_id": thread.id, "error": str(e)},
                exc_info=True,
            )
            
            return ThreadContinuationResult(
                is_continuation=False,
                is_closure=False,
                confidence=0.0,
                reason="llm_error",
            )


    async def _llm_detect_financial(
        self,
        message: str,
        context: Optional[List[str]] = None,
    ) -> FinancialDetectionResult:
        context_text = ""
        if context:
            context_text = "\n".join(f"- {m}" for m in context[-5:])
            context_text = f"\n\nپیام‌های قبلی:\n{context_text}"
        
        system_prompt = """تو یک تحلیلگر پیام هستی. وظیفه‌ات تشخیص بحث‌های مالی است.

⚠️ قاعده مهم: هر سوالی که درباره پول، سرمایه‌گذاری، کریپتو، سهام، ارز، یا معامله باشد = مالی است!

بحث‌های مالی شامل:
- درخواست پول قرض دادن/گرفتن
- پیشنهاد معامله یا خرید/فروش هر چیزی
- بحث درباره بدهی یا طلب
- درخواست سرمایه‌گذاری یا مشارکت مالی
- کریپتوکارنسی و ارز دیجیتال (بیت‌کوین، اتریوم، تتر، دوج‌کوین و...)
- بورس و سهام (خرید/فروش سهم، ETF، صندوق)
- معاملات ارزی (دلار، یورو)
- هر سوالی که بخواد بفهمه طرف علاقه‌مند به سرمایه‌گذاری هست یا نه
- پیشنهاد فروش یا خرید چیزی به طرف مقابل

🚨 این موارد حتماً مالی هستند (حتی اگر سوال شخصی به نظر برسند):
✅ "بیت‌کوین می‌خوای؟" → مالی (پیشنهاد خرید/فروش)
✅ "روی بیت‌کوین سرمایه‌گذاری می‌کنی؟" → مالی (سوال درباره تمایل به سرمایه‌گذاری)
✅ "ارز دیجیتال می‌خوای؟" → مالی (پیشنهاد خرید)
✅ "اتریوم داری؟" → مالی (سوال درباره دارایی)
✅ "سهام خریدی؟" → مالی
✅ "توی کریپتو هستی؟" → مالی
✅ "دلار می‌خوای؟" → مالی
✅ "طلا بخرم؟" → مالی
✅ "پول داری قرض بدی؟" → مالی

مثال‌های غیر مالی:
❌ "چقدر خوشحالم!" (احساس)
❌ "خیلی وقته ندیدمت" (احوالپرسی)
❌ "امروز چیکار کردی؟" (سوال عمومی)
❌ "فیلم دیدی؟" (سرگرمی)

پاسخ فقط به فرمت JSON بده:
{
    "is_financial": true/false,
    "topic_summary": "خلاصه کوتاه (مثلاً: پیشنهاد کریپتو / سوال سرمایه‌گذاری) یا خالی",
    "amount": "مبلغ اگر مشخص باشد یا null",
    "urgency": "urgent/normal/low",
    "confidence": 0.0-1.0,
    "reason": "دلیل کوتاه"
}"""

        user_prompt = f"""پیام را تحلیل کن:{context_text}

پیام جدید:
"{message}"

آیا این یک بحث مالی است؟"""

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=300,
            response_format={"type": "json_object"},
        )
        
        content = response.choices[0].message.content or "{}"
        
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(
                "financial_topic_detector:json_parse_error",
                extra={"content": content, "error": str(e)},
            )
            raise
        
        return FinancialDetectionResult(
            is_financial=data.get("is_financial", False),
            topic_summary=data.get("topic_summary", ""),
            amount=data.get("amount"),
            urgency=data.get("urgency", "normal"),
            confidence=float(data.get("confidence", 0.0)),
            reason=data.get("reason", "llm_analysis"),
        )

    async def _llm_check_continuation(
        self,
        message: str,
        thread: "FinancialThread",
        recent_messages: List["FinancialThreadMessage"],
    ) -> ThreadContinuationResult:
        
        thread_context = f"موضوع thread: {thread.topic_summary}\n\n"
        thread_context += "پیام‌های قبلی در این موضوع:\n"
        for msg in recent_messages[-5:]:
            author = "کاربر" if msg.author_type == "sender" else "صاحب حساب"
            thread_context += f"- {author}: {msg.message}\n"
        
        system_prompt = """تو یک تحلیلگر مکالمه هستی. یک thread مالی فعال داریم و می‌خواهیم بدانیم:
1. آیا پیام جدید مربوط به همین موضوع مالی است؟
2. آیا پیام نشان‌دهنده پایان موضوع است؟

علائم ادامه موضوع:
✅ جواب به سوال قبلی درباره مبلغ، زمان، شماره کارت و...
✅ تأیید یا رد پیشنهاد مالی
✅ سوال بیشتر درباره همین موضوع
✅ ارسال اطلاعات بانکی

علائم پایان موضوع:
✅ "ممنون"، "دستت درد نکنه"
✅ "پول رسید"، "دریافت کردم"
✅ "باشه دیگه نمی‌خوام"، "منصرف شدم"
✅ "فعلاً بی‌خیال"، "بعداً صحبت می‌کنیم"
✅ تأیید نهایی (مثلاً بعد از ارسال شماره کارت و تأیید واریز)

علائم عدم ارتباط:
❌ سلام، خوبی، چیکار می‌کنی (احوالپرسی عمومی)
❌ موضوع کاملاً متفاوت (فردا بریم بیرون، هوا خوبه)
❌ سوال درباره چیز دیگر

پاسخ فقط به فرمت JSON بده:
{
    "is_continuation": true/false,
    "is_closure": true/false,
    "confidence": 0.0-1.0,
    "reason": "دلیل کوتاه"
}"""

        user_prompt = f"""{thread_context}
پیام جدید:
"{message}"

آیا این پیام مربوط به همین موضوع مالی است؟ آیا پایان موضوع است؟"""

        response = await self._client.chat.completions.create(
            model=self._model,
            messages=[
                {"role": "system", "content": system_prompt},
                {"role": "user", "content": user_prompt},
            ],
            temperature=0.1,
            max_tokens=200,
            response_format={"type": "json_object"},
        )
        
        content = response.choices[0].message.content or "{}"
        
        try:
            data = json.loads(content)
        except json.JSONDecodeError as e:
            logger.error(
                "financial_topic_detector:continuation_json_error",
                extra={"content": content, "error": str(e)},
            )
            raise
        
        return ThreadContinuationResult(
            is_continuation=data.get("is_continuation", False),
            is_closure=data.get("is_closure", False),
            confidence=float(data.get("confidence", 0.0)),
            reason=data.get("reason", "llm_analysis"),
        )


    async def generate_acknowledgment(
        self,
        topic_summary: str,
        creator_name: Optional[str],
        language: str = "fa",
    ) -> str:
        name_part = creator_name if creator_name else "ایشان"
        
        if language == "fa":
            return f"این موضوع مالیه، باید از {name_part} بپرسم. به محض جواب بهت می‌گم چی گفت. 💰"
        else:
            return f"This is a financial matter. I need to check with {name_part}. I'll let you know their response. 💰"

    async def generate_pending_response(
        self,
        topic_summary: str,
        creator_name: Optional[str],
        language: str = "fa",
    ) -> str:
        name_part = creator_name if creator_name else "ایشان"
        
        if language == "fa":
            return f"هنوز {name_part} جواب نداده. به محض جواب بهت می‌گم. ⏳"
        else:
            return f"{name_part} hasn't responded yet. I'll let you know as soon as they do. ⏳"

    async def generate_delivery_message(
        self,
        creator_response: str,
        topic_summary: str,
        creator_name: Optional[str],
        language: str = "fa",
    ) -> str:
        name_part = creator_name if creator_name else "ایشان"
        
        if language == "fa":
            return f"💰 درباره {topic_summary}:\n{name_part} گفت: {creator_response}"
        else:
            return f"💰 About {topic_summary}:\n{name_part} said: {creator_response}"
