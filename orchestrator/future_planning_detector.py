
from __future__ import annotations

import json
import logging
from dataclasses import dataclass
from typing import Optional, List, TYPE_CHECKING

from openai import AsyncOpenAI

if TYPE_CHECKING:
    from config.settings import Settings

logger = logging.getLogger(__name__)


@dataclass
class FuturePlanningResult:
    is_future_planning: bool
    detected_plan: str
    detected_datetime: Optional[str]
    confidence: float
    reason: str


class FuturePlanningDetector:

    def __init__(
        self,
        openai_client: AsyncOpenAI,
        settings: "Settings",
    ):
        self._client = openai_client
        self._settings = settings
        self._model = getattr(settings, "AGENTS_MODEL", "gpt-4o-mini")
        logger.info("future_planning_detector:init:success")

    async def detect(
        self,
        message: str,
        sender_id: str,
        recipient_id: str,
        context: Optional[List[str]] = None,
    ) -> FuturePlanningResult:
        try:
            result = await self._llm_analysis(message, context)
            
            logger.info(
                "future_planning_detector:result",
                extra={
                    "sender_id": sender_id,
                    "recipient_id": recipient_id,
                    "message_preview": message[:50],
                    "is_future_planning": result.is_future_planning,
                    "confidence": result.confidence,
                    "detected_plan": result.detected_plan[:100] if result.detected_plan else "",
                },
            )
            
            return result
            
        except Exception as e:
            logger.error(
                "future_planning_detector:error",
                extra={
                    "sender_id": sender_id,
                    "recipient_id": recipient_id,
                    "error": str(e),
                },
                exc_info=True,
            )
            
            return FuturePlanningResult(
                is_future_planning=False,
                detected_plan="",
                detected_datetime=None,
                confidence=0.0,
                reason="llm_error",
            )

    async def _llm_analysis(
        self,
        message: str,
        context: Optional[List[str]] = None,
    ) -> FuturePlanningResult:
        context_text = ""
        if context:
            context_text = "\n".join(f"- {m}" for m in context[-5:])
            context_text = f"\n\nپیام‌های قبلی:\n{context_text}"
        
        system_prompt = """تو یک تحلیلگر پیام هستی. وظیفه‌ات تشخیص درخواست‌های برنامه‌ریزی آینده است.

درخواست برنامه‌ریزی آینده یعنی:
- پیشنهاد انجام کاری در آینده (فردا، هفته بعد، ...)
- دعوت به ملاقات یا قرار
- هماهنگی برای یک رویداد
- سوال درباره زمان‌بندی آینده
- درخواست همراهی برای انجام کاری

مثال‌های درخواست برنامه‌ریزی:
✅ "فردا بریم کوه؟"
✅ "هفته بعد وقت داری ناهار بریم؟"
✅ "شنبه ساعت ۵ بیا پیشم"
✅ "کی می‌تونیم همدیگرو ببینیم؟"
✅ "بریم سینما"
✅ "میای فوتبال؟"
✅ "یه قرار بذاریم"

مثال‌های غیر برنامه‌ریزی:
❌ "دیروز رفتم کوه" (گذشته)
❌ "سلام، خوبی؟" (احوالپرسی)
❌ "چیکار می‌کنی؟" (سوال عمومی)
❌ "ممنون از کمکت" (تشکر)
❌ "خوش گذشت" (گذشته)
❌ "چه خبر؟" (احوالپرسی)

پاسخ فقط به فرمت JSON بده:
{
    "is_future_planning": true/false,
    "detected_plan": "خلاصه کوتاه برنامه (مثلاً: رفتن به کوه) یا خالی اگر برنامه‌ریزی نیست",
    "detected_datetime": "زمان تشخیص داده شده (مثلاً: فردا) یا null",
    "confidence": 0.0-1.0,
    "reason": "دلیل کوتاه"
}"""

        user_prompt = f"""پیام را تحلیل کن:{context_text}

پیام جدید:
"{message}"

آیا این یک درخواست برنامه‌ریزی آینده است؟"""

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
                "future_planning_detector:json_parse_error",
                extra={"content": content, "error": str(e)},
            )
            raise
        
        return FuturePlanningResult(
            is_future_planning=data.get("is_future_planning", False),
            detected_plan=data.get("detected_plan", ""),
            detected_datetime=data.get("detected_datetime"),
            confidence=float(data.get("confidence", 0.0)),
            reason=data.get("reason", "llm_analysis"),
        )

    async def generate_acknowledgment_response(
        self,
        detected_plan: str,
        detected_datetime: Optional[str],
        twin_name: Optional[str],
        language: str = "fa",
    ) -> str:
        name_part = twin_name if twin_name else "ایشان"
        
        if language == "fa":
            return f"باشه، این موضوع رو به {name_part} اطلاع می‌دم. وقتی جواب داد، توی پیام بعدیت بهت می‌گم چی گفت. 👍"
        else:
            return f"Got it! I'll let {name_part} know about this. When they respond, I'll tell you in our next chat. 👍"
