
from __future__ import annotations

import json
import logging
import re
import time
from dataclasses import dataclass, field
from enum import Enum
from typing import Any, Dict, List, Optional, TYPE_CHECKING

if TYPE_CHECKING:
    from openai import AsyncOpenAI

from config.settings import Settings
from observability.phoenix_setup import record_llm_tokens

logger = logging.getLogger(__name__)


class FactPriority(str, Enum):
    HIGH = "high"
    MEDIUM = "medium"
    LOW = "low"


class FactCategory(str, Enum):
    IDENTITY = "identity"
    LOCATION = "location"
    OCCUPATION = "occupation"
    FAMILY = "family"
    CONTACT = "contact"
    
    PREFERENCE = "preference"
    HABIT = "habit"
    GOAL = "goal"
    HEALTH = "health"
    
    EVENT = "event"
    MOOD = "mood"
    ACTIVITY = "activity"
    TEMPORAL = "temporal"


CATEGORY_TO_PRIORITY: Dict[FactCategory, FactPriority] = {
    FactCategory.IDENTITY: FactPriority.HIGH,
    FactCategory.LOCATION: FactPriority.HIGH,
    FactCategory.OCCUPATION: FactPriority.HIGH,
    FactCategory.FAMILY: FactPriority.HIGH,
    FactCategory.CONTACT: FactPriority.HIGH,
    FactCategory.PREFERENCE: FactPriority.MEDIUM,
    FactCategory.HABIT: FactPriority.MEDIUM,
    FactCategory.GOAL: FactPriority.MEDIUM,
    FactCategory.HEALTH: FactPriority.MEDIUM,
    FactCategory.EVENT: FactPriority.LOW,
    FactCategory.MOOD: FactPriority.LOW,
    FactCategory.ACTIVITY: FactPriority.LOW,
    FactCategory.TEMPORAL: FactPriority.LOW,
}


@dataclass
class ExtractedFact:
    category: str
    priority: str
    subject: str
    key: str
    value: str
    confidence: float = 0.9
    source_user: str = ""
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "category": self.category,
            "priority": self.priority,
            "subject": self.subject,
            "key": self.key,
            "value": self.value,
            "confidence": self.confidence,
            "source_user": self.source_user,
        }


@dataclass
class ExtractionResult:
    high_priority: List[ExtractedFact] = field(default_factory=list)
    medium_priority: List[ExtractedFact] = field(default_factory=list)
    low_priority: List[ExtractedFact] = field(default_factory=list)
    clean_summary: str = ""
    
    @property
    def all_facts(self) -> List[ExtractedFact]:
        return self.high_priority + self.medium_priority + self.low_priority
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "high_priority": [f.to_dict() for f in self.high_priority],
            "medium_priority": [f.to_dict() for f in self.medium_priority],
            "low_priority": [f.to_dict() for f in self.low_priority],
            "clean_summary": self.clean_summary,
        }


class CoreFactExtractor:

    EXTRACTION_PROMPT = """شما یک سیستم استخراج اطلاعات هستید. از متن زیر، اطلاعات کلیدی را استخراج و اولویت‌بندی کنید.

**سطوح اولویت:**

🔴 HIGH (هویتی/پایدار - هرگز حذف نشود):
- identity: نام، سن، تاریخ تولد، جنسیت
- location: شهر، آدرس، کشور، محل زندگی
- occupation: شغل، تحصیلات، محل کار
- family: روابط خانوادگی (همسر، فرزند، والدین)
- contact: شماره تلفن، ایمیل

🟡 MEDIUM (نیمه‌پایدار - آپدیت بعد از مدت طولانی):
- preference: علاقه‌مندی‌ها، ترجیحات
- habit: عادات، روتین‌ها
- goal: اهداف، برنامه‌های بلندمدت
- health: وضعیت سلامت پایدار

🟢 LOW (موقت - حذف بعد از خلاصه‌سازی):
- event: رویدادهای روزانه، قرارها
- mood: احساسات لحظه‌ای
- activity: فعالیت‌های روزانه
- temporal: اطلاعات زمان‌دار (امروز، فردا، دیروز)

**متن:**
{text}

**کاربران مکالمه:**
- user_a: {user_a}
- user_b: {user_b}

**خروجی را دقیقاً به این فرمت JSON برگردانید:**
```json
{{
  "facts": [
    {{
      "category": "identity|location|occupation|family|contact|preference|habit|goal|health|event|mood|activity|temporal",
      "priority": "high|medium|low",
      "subject": "self|spouse|child|parent|friend|other",
      "key": "name|age|city|job|...",
      "value": "مقدار",
      "confidence": 0.9,
      "source_user": "{user_a}|{user_b}"
    }}
  ],
  "clean_summary": "خلاصه بدون اطلاعات LOW priority (فقط HIGH و MEDIUM)"
}}
```

**قوانین:**
1. فقط اطلاعات واضح و مشخص را استخراج کنید
2. اگر اطلاعاتی نیست، لیست خالی برگردانید
3. clean_summary باید فقط اطلاعات HIGH و MEDIUM را داشته باشد
4. source_user را بر اساس اینکه اطلاعات از کدام کاربر است مشخص کنید"""

    def __init__(
        self,
        settings: Settings,
        openai_client: "AsyncOpenAI",
    ) -> None:
        self._settings = settings
        self._client = openai_client
        
        self._model = getattr(settings, "FACT_EXTRACTOR_MODEL", "gpt-4o-mini")
        self._temperature = getattr(settings, "FACT_EXTRACTOR_TEMPERATURE", 0.1)
        self._max_tokens = getattr(settings, "FACT_EXTRACTOR_MAX_TOKENS", 2000)
        self._top_p = getattr(settings, "FACT_EXTRACTOR_TOP_P", None)
        
        logger.info(
            "core_fact_extractor:init",
            extra={
                "model": self._model,
                "temperature": self._temperature,
                "max_tokens": self._max_tokens,
                "top_p": self._top_p,
            },
        )

    async def extract_facts(
        self,
        text: str,
        user_a: str,
        user_b: str,
    ) -> ExtractionResult:
        if not text or not text.strip():
            logger.warning(
                "core_fact_extractor:extract_facts:empty_input",
                extra={"user_a": user_a, "user_b": user_b},
            )
            return ExtractionResult(clean_summary="")

        start_time = time.time()
        
        logger.info(
            "core_fact_extractor:extract_facts:start",
            extra={
                "user_a": user_a,
                "user_b": user_b,
                "text_length": len(text),
                "model": self._model,
            },
        )

        try:
            prompt = self.EXTRACTION_PROMPT.format(
                text=text,
                user_a=user_a,
                user_b=user_b,
            )
            
            messages = [
                {"role": "system", "content": "You are a JSON-only response bot. Return only valid JSON."},
                {"role": "user", "content": prompt},
            ]
            
            llm_params: Dict[str, Any] = {
                "model": self._model,
                "messages": messages,
                "temperature": self._temperature,
                "max_tokens": self._max_tokens,
            }
            if self._top_p is not None:
                llm_params["top_p"] = self._top_p

            response = await self._client.chat.completions.create(**llm_params)

            content = response.choices[0].message.content or ""
            
            usage = response.usage
            if usage:
                record_llm_tokens(
                    agent_name="core_fact_extractor",
                    model=self._model,
                    prompt_tokens=usage.prompt_tokens,
                    completion_tokens=usage.completion_tokens,
                    total_tokens=usage.total_tokens,
                    input_messages=messages,
                    output_message=content,
                )
            
            result = self._parse_llm_response(content, text)
            
            elapsed_ms = int((time.time() - start_time) * 1000)
            
            logger.info(
                "core_fact_extractor:extract_facts:success",
                extra={
                    "user_a": user_a,
                    "user_b": user_b,
                    "high_count": len(result.high_priority),
                    "medium_count": len(result.medium_priority),
                    "low_count": len(result.low_priority),
                    "prompt_tokens": usage.prompt_tokens if usage else 0,
                    "completion_tokens": usage.completion_tokens if usage else 0,
                    "elapsed_ms": elapsed_ms,
                    "model": self._model,
                },
            )
            
            return result

        except Exception as e:
            elapsed_ms = int((time.time() - start_time) * 1000)
            
            logger.error(
                "core_fact_extractor:extract_facts:error",
                extra={
                    "user_a": user_a,
                    "user_b": user_b,
                    "error": str(e),
                    "elapsed_ms": elapsed_ms,
                    "model": self._model,
                },
                exc_info=True,
            )
            return ExtractionResult(clean_summary=text)

    def _parse_llm_response(self, content: str, original_text: str) -> ExtractionResult:
        try:
            json_match = re.search(r'```json\s*(.*?)\s*```', content, re.DOTALL)
            if json_match:
                json_str = json_match.group(1)
            else:
                json_str = content.strip()
            
            data = json.loads(json_str)
            
            result = ExtractionResult(
                clean_summary=data.get("clean_summary", original_text),
            )
            
            for fact_data in data.get("facts", []):
                fact = ExtractedFact(
                    category=fact_data.get("category", "temporal"),
                    priority=fact_data.get("priority", "low"),
                    subject=fact_data.get("subject", "self"),
                    key=fact_data.get("key", "unknown"),
                    value=fact_data.get("value", ""),
                    confidence=fact_data.get("confidence", 0.9),
                    source_user=fact_data.get("source_user", ""),
                )
                
                if fact.priority == "high":
                    result.high_priority.append(fact)
                elif fact.priority == "medium":
                    result.medium_priority.append(fact)
                else:
                    result.low_priority.append(fact)
            
            return result

        except json.JSONDecodeError as e:
            logger.warning(
                "core_fact_extractor:json_parse_error",
                extra={"error": str(e), "content_preview": content[:200]},
            )
            return ExtractionResult(clean_summary=original_text)

    async def extract_facts_simple(
        self,
        text: str,
        user_a: str,
        user_b: str,
    ) -> ExtractionResult:
        result = ExtractionResult(clean_summary=text)
        
        patterns = {
            ("identity", "name"): [
                r"(?:نام|اسم)\s*[:\s]+([^\s,،.]+)",
                r"([^\s]+)\s+(?:هستم|نام دارم)",
            ],
            ("identity", "age"): [
                r"(?:سن|سال)\s*[:\s]+(\d+)",
                r"(\d+)\s*(?:ساله|سالم)",
            ],
            ("location", "city"): [
                r"(?:شهر|ساکن|زندگی در)\s*[:\s]+([^\s,،.]+)",
                r"(?:اهل|از)\s+([^\s,،.]+)\s+(?:هستم|ام)",
            ],
            ("occupation", "job"): [
                r"(?:شغل|کار|حرفه)\s*[:\s]+([^\s,،.]+(?:\s+[^\s,،.]+)?)",
            ],
            ("family", "spouse"): [
                r"(?:همسر|زن|شوهر)\s*[:\s]+([^\s,،.]+)",
            ],
            ("family", "children"): [
                r"(\d+)\s*(?:بچه|فرزند)",
            ],
            ("preference", "likes"): [
                r"(?:دوست دارم|علاقه دارم به)\s+([^\s,،.]+(?:\s+[^\s,،.]+)*)",
            ],
            ("goal", "plan"): [
                r"(?:می‌خوام|قصد دارم|برنامه دارم)\s+([^\s,،.]+(?:\s+[^\s,،.]+)*)",
            ],
        }
        
        for (category, key), pattern_list in patterns.items():
            priority = CATEGORY_TO_PRIORITY.get(
                FactCategory(category), 
                FactPriority.LOW
            ).value
            
            for pattern in pattern_list:
                matches = re.findall(pattern, text, re.IGNORECASE)
                for match in matches:
                    if match and match.strip():
                        fact = ExtractedFact(
                            category=category,
                            priority=priority,
                            subject="self",
                            key=key,
                            value=match.strip(),
                            confidence=0.7,
                            source_user=user_a,
                        )
                        
                        if priority == "high":
                            result.high_priority.append(fact)
                        elif priority == "medium":
                            result.medium_priority.append(fact)
                        else:
                            result.low_priority.append(fact)
        
        return result


def merge_facts(
    existing: List[ExtractedFact],
    new_facts: List[ExtractedFact],
) -> List[ExtractedFact]:
    result_map: Dict[str, ExtractedFact] = {}
    
    for fact in existing:
        key = f"{fact.category}:{fact.subject}:{fact.key}"
        result_map[key] = fact
    
    for fact in new_facts:
        key = f"{fact.category}:{fact.subject}:{fact.key}"
        if key not in result_map or fact.confidence >= result_map[key].confidence:
            result_map[key] = fact
    
    return list(result_map.values())


def facts_to_text(facts: List[ExtractedFact], include_priority: bool = False) -> str:
    if not facts:
        return ""
    
    lines = []
    for f in facts:
        if include_priority:
            lines.append(f"[{f.priority.upper()}] {f.key}: {f.value}")
        else:
            lines.append(f"{f.key}: {f.value}")
    
    return " | ".join(lines)
