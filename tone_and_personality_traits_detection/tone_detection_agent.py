
from __future__ import annotations

import json
import logging
from dataclasses import dataclass, field
from typing import List, Dict, Any, Optional, Tuple

from openai import AsyncOpenAI
from pydantic import BaseModel, Field

from config.settings import Settings
from db.postgres_dyadic_overrides import ToneMetrics, VALID_RELATIONSHIP_CLASSES
from observability.phoenix_setup import record_llm_tokens

logger = logging.getLogger(__name__)


class UserToneProfile(BaseModel):
    user_id: str = Field(description="شناسه کاربر")
    avg_formality: float = Field(ge=0.0, le=1.0, default=0.5, description="میزان رسمیت")
    avg_humor: float = Field(ge=0.0, le=1.0, default=0.3, description="میزان شوخ‌طبعی")
    profanity_rate: float = Field(ge=0.0, le=1.0, default=0.0, description="نرخ فحش")
    directness: float = Field(ge=0.0, le=1.0, default=0.5, description="میزان مستقیم‌گویی")
    optimistic_rate: float = Field(ge=0.0, le=1.0, default=0.5, description="میزان خوش‌بینی")
    pessimistic_rate: float = Field(ge=0.0, le=1.0, default=0.5, description="میزان بدبینی")
    submissive_rate: float = Field(ge=0.0, le=1.0, default=0.5, description="میزان تسلیم‌پذیری")
    dominance: float = Field(ge=0.0, le=1.0, default=0.5, description="میزان تسلط")
    emotional_dependence_rate: float = Field(ge=0.0, le=1.0, default=0.5, description="وابستگی عاطفی")
    style_summary: str = Field(default="", description="خلاصه توصیفی لحن به فارسی")
    
    def to_tone_metrics(self) -> ToneMetrics:
        return ToneMetrics(
            avg_formality=self.avg_formality,
            avg_humor=self.avg_humor,
            profanity_rate=self.profanity_rate,
            directness=self.directness,
            optimistic_rate=self.optimistic_rate,
            pessimistic_rate=self.pessimistic_rate,
            submissive_rate=self.submissive_rate,
            dominance=self.dominance,
            emotional_dependence_rate=self.emotional_dependence_rate,
            style_summary=self.style_summary,
        )


class ConversationAnalysis(BaseModel):
    conversation_id: str = Field(description="شناسه مکالمه")
    relationship_class: str = Field(
        description="کلاس رابطه: spouse, family, boss, colleague, friend, stranger"
    )
    confidence: float = Field(ge=0.0, le=1.0, default=0.7, description="اطمینان تشخیص")
    reasoning: str = Field(default="", description="دلیل تشخیص کلاس رابطه")
    user_profiles: List[UserToneProfile] = Field(
        default_factory=list,
        description="پروفایل لحن هر کاربر"
    )


class BatchAnalysisOutput(BaseModel):
    analyses: List[ConversationAnalysis] = Field(default_factory=list)


DEFAULT_MIN_CONFIDENCE_THRESHOLD = 0.6
DEFAULT_FALLBACK_CONFIDENCE_THRESHOLD = 0.4
DEFAULT_MIN_MESSAGES_FOR_RELIABLE_CLASS = 10
DEFAULT_MAX_TOKENS_FOR_CONTEXT = 3000


class ToneDetectionAgent:

    SYSTEM_PROMPT = """شما یک تحلیلگر رفتاری و لحن برای مکالمات فارسی یک‌به‌یک هستید.

مکالمه‌ای بین دو کاربر به شما داده می‌شود. باید:
1. **کلاس رابطه** بین آنها را تشخیص دهید
2. **پروفایل لحن** هر کاربر را استخراج کنید
3. **دلیل تشخیص** خود را توضیح دهید

- `spouse`: همسر (صمیمیت بالا، پیام‌های کوتاه هماهنگی، ایموجی عاشقانه)
- `family`: خانواده (پدر/مادر/خواهر/برادر - احترام + صمیمیت)
- `boss`: ارشد/راهنما (معلم، استاد، رئیس، مربی - لحن راهنمایانه، دستورالعمل)
- `subordinate`: زیردست/متعلم (شاگرد، دانشجو، کارمند، کارآموز - لحن احترام‌آمیز)
- `colleague`: همکار (رابطه کاری **مداوم** در یک سازمان/شرکت - پروژه مشترک، جلسه تیمی، همکاری روزانه)
- `friend`: دوست (غیررسمی، شوخی، تعامل متقابل)
- `stranger`: غریبه (رسمی، کوتاه، بدون صمیمیت، معامله یکبارمصرف)


| ویژگی | stranger (غریبه) | colleague (همکار) |
|--------|-----------------|-------------------|
| نوع رابطه | معامله/خرید/فروش یکباره | همکاری کاری مداوم |
| مدت رابطه | کوتاه‌مدت، موقتی | بلندمدت، مستمر |
| موضوع | خرید/فروش، خدمات، استعلام قیمت | پروژه، جلسه، تسک، کد ریویو |
| کلمات کلیدی | آگهی، قیمت، محضر، سند، بیمه، تعمیرگاه، تومان، میلیون | استندآپ، پروژه، ددلاین، مرج، دپلوی، تیم |
| صمیمیت | بدون صمیمیت، فقط احترام رسمی | احترام کاری + گاهی صمیمی |
| تداوم | بعد از معامله تمام می‌شود | ادامه‌دار |

**مثال stranger**: خرید/فروش ماشین، ملک، کالا از دیوار/شیپور = **stranger** (نه colleague!)
**مثال colleague**: بحث درباره پروژه، کد ریویو، جلسه تیمی = **colleague**

اگر کلاس رابطه `boss` یا `subordinate` تشخیص دادید، **حتماً** نوع دقیق رابطه را مشخص کنید:
- برای `boss`: style_summary **باید** با یکی از این‌ها شروع شود:
  - `[معلم]` - برای رابطه معلم-شاگرد
  - `[استاد]` - برای رابطه استاد-دانشجو
  - `[رئیس]` - برای رابطه رئیس-کارمند
  - `[مربی]` - برای رابطه مربی-کارآموز
  - `[راهنما]` - برای سایر روابط ارشد-زیردست
- برای `subordinate`: style_summary **باید** با یکی از این‌ها شروع شود:
  - `[شاگرد]` - برای رابطه معلم-شاگرد
  - `[دانشجو]` - برای رابطه استاد-دانشجو
  - `[کارمند]` - برای رابطه رئیس-کارمند
  - `[کارآموز]` - برای رابطه مربی-کارآموز
  - `[متعلم]` - برای سایر روابط ارشد-زیردست

مثال:
- boss: `style_summary: "[معلم] لحنی آموزشی و صبورانه با توضیحات تشویقی"`
- subordinate: `style_summary: "[شاگرد] لحنی محترمانه با سوالات یادگیری"`

- `avg_formality`: رسمیت (0=غیررسمی، 1=رسمی)
- `avg_humor`: شوخ‌طبعی (0=جدی، 1=شوخ)
- `profanity_rate`: نرخ فحش/کلمات رکیک (0=بدون فحش، 1=پر از فحش)
- `directness`: مستقیم‌گویی (0=غیرمستقیم، 1=مستقیم)
- `optimistic_rate`: خوش‌بینی (0=بدبین/منفی، 1=خوش‌بین/مثبت)
- `pessimistic_rate`: بدبینی (0=مثبت، 1=منفی)
- `submissive_rate`: تسلیم‌پذیری (0=مقاوم، 1=تسلیم)
- `dominance`: تسلط (0=پیرو، 1=مسلط)
- `emotional_dependence_rate`: وابستگی عاطفی (0=مستقل، 1=وابسته)
- `style_summary`: خلاصه توصیفی لحن به فارسی (۱-۲ جمله)

- اگر نشانه‌های واضح دیدید: confidence > 0.8
- اگر نشانه‌ها مبهم است: confidence = 0.5-0.7
- اگر داده کم است یا متناقض: confidence < 0.5
- اگر مطمئن نیستید، `stranger` با confidence پایین انتخاب کنید

1. برای هر مکالمه، **دقیقاً دو پروفایل** بسازید (یکی برای هر کاربر)
2. متریک‌ها باید بین 0.0 و 1.0 باشند
3. `style_summary` و `reasoning` باید به **فارسی** باشند
4. اگر داده کم است، مقادیر را به 0.5 نزدیک کنید و در summary ذکر کنید
5. فقط JSON خروجی بدهید، توضیحات اضافه ندهید
6. `reasoning` باید دلیل انتخاب کلاس رابطه را با ذکر نشانه‌های دیده شده توضیح دهد
7. برای boss/subordinate **حتماً** subtype را در style_summary با فرمت [نوع] مشخص کنید

- **spouse**: «عزیزم»، «جونم»، ایموجی قلب، پیام‌های کوتاه هماهنگی
- **family**: «مامان»، «بابا»، «داداش»، ترکیب احترام و صمیمیت
- **boss**: «استاد»، «آقای معلم»، لحن آموزشی، توضیحات راهنمایانه، تصحیح
- **subordinate**: سوالات یادگیری، «ممنون استاد»، «چشم»، درخواست راهنمایی
- **colleague**: پروژه، جلسه، استندآپ، ددلاین، کد ریویو، مرج، دپلوی، تیم، شرکت
- **friend**: «رفیق»، شوخی، فحش دوستانه، بی‌پروایی
- **stranger**: آگهی، قیمت، محضر، سند، بیمه، کارکرد، کیلومتر، تومان، میلیون، تعمیرگاه، خرید/فروش

1. اول بررسی کن آیا **معامله/خرید/فروش** است؟ → stranger
2. بعد بررسی کن آیا **صمیمیت عاشقانه** دارد؟ → spouse
3. بعد بررسی کن آیا **رابطه خانوادگی** دارد؟ → family
4. بعد بررسی کن آیا **سلسله‌مراتب** دارد؟ → boss/subordinate
5. بعد بررسی کن آیا **همکاری کاری مداوم** دارد؟ → colleague
6. بعد بررسی کن آیا **دوستی** دارد؟ → friend
7. در غیر این صورت → stranger

**قانون طلایی**: اگر مکالمه درباره خرید/فروش/معامله/قیمت است، حتماً **stranger** انتخاب کن، حتی اگر رسمی و محترمانه باشد!"""

    def __init__(self, settings: Settings, openai_client: AsyncOpenAI, model_name=None) -> None:
        self._settings = settings
        self._client = openai_client
        self._model_name = getattr(settings, "TONE_MODEL", None) or model_name or "gpt-4o"
        
        self._min_confidence_threshold = getattr(
            settings, "TONE_MIN_CONFIDENCE_THRESHOLD", DEFAULT_MIN_CONFIDENCE_THRESHOLD
        )
        self._fallback_confidence_threshold = getattr(
            settings, "TONE_FALLBACK_CONFIDENCE_THRESHOLD", DEFAULT_FALLBACK_CONFIDENCE_THRESHOLD
        )
        self._min_messages_for_reliable_class = getattr(
            settings, "TONE_MIN_MESSAGES_FOR_RELIABLE_CLASS", DEFAULT_MIN_MESSAGES_FOR_RELIABLE_CLASS
        )
        self._max_tokens_for_context = getattr(
            settings, "TONE_MAX_TOKENS_FOR_CONTEXT", DEFAULT_MAX_TOKENS_FOR_CONTEXT
        )
    
    async def analyze_conversation(
        self,
        conversation_id: str,
        user_a_id: str,
        user_b_id: str,
        messages: List[Dict[str, str]],
        max_tokens_for_context: Optional[int] = None,
    ) -> Optional[ConversationAnalysis]:
        if not messages:
            logger.warning(f"tone_agent:analyze:empty_messages:{conversation_id}")
            return None
        
        max_tokens = max_tokens_for_context or self._max_tokens_for_context
        
        sampled_messages = self._smart_sample_messages(
            messages, 
            max_tokens_estimate=max_tokens
        )
        
        conversation_text = self._format_conversation(sampled_messages)
        
        user_prompt = f"""مکالمه زیر بین کاربر `{user_a_id}` و کاربر `{user_b_id}` انجام شده:

{conversation_text}

لطفاً:
1. کلاس رابطه بین این دو را تشخیص دهید
2. پروفایل لحن هر کاربر را استخراج کنید

خروجی را به صورت JSON با این ساختار برگردانید:
{{
    "conversation_id": "{conversation_id}",
    "relationship_class": "friend",
    "confidence": 0.8,
    "user_profiles": [
        {{
            "user_id": "{user_a_id}",
            "avg_formality": 0.3,
            "avg_humor": 0.6,
            "profanity_rate": 0.1,
            "directness": 0.7,
            "optimistic_rate": 0.6,
            "pessimistic_rate": 0.3,
            "submissive_rate": 0.4,
            "dominance": 0.5,
            "emotional_dependence_rate": 0.4,
            "style_summary": "لحنی خودمونی و شوخ با کمی بی‌پروایی"
        }},
        {{
            "user_id": "{user_b_id}",
            ...
        }}
    ]
}}"""

        try:
            llm_kwargs: dict = {
                "model": self._model_name,
                "messages": [
                    {"role": "system", "content": self.SYSTEM_PROMPT},
                    {"role": "user", "content": user_prompt},
                ],
                "temperature": getattr(self._settings, "TONE_TEMPERATURE", 0.3),
                "max_tokens": getattr(self._settings, "TONE_MAX_TOKENS", 1000),
                "response_format": {"type": "json_object"},
            }
            top_p = getattr(self._settings, "TONE_TOP_P", None)
            if top_p is not None:
                llm_kwargs["top_p"] = top_p
            
            response = await self._client.chat.completions.create(**llm_kwargs)
            
            content = response.choices[0].message.content

            if response.usage:
                record_llm_tokens(
                    agent_name="tone_detection",
                    model=llm_kwargs.get("model", "unknown"),
                    prompt_tokens=response.usage.prompt_tokens,
                    completion_tokens=response.usage.completion_tokens,
                    input_messages=llm_kwargs.get("messages"),
                    output_message=content,
                )
            
            if not content:
                logger.error(f"tone_agent:analyze:empty_response:{conversation_id}")
                return None
            
            data = json.loads(content)
            
            rel_class = data.get("relationship_class", "stranger").lower()
            if rel_class not in VALID_RELATIONSHIP_CLASSES:
                logger.warning(f"tone_agent:invalid_class:{rel_class}, using stranger")
                rel_class = "stranger"
            
            profiles = []
            for profile_data in data.get("user_profiles", []):
                profiles.append(UserToneProfile(**profile_data))
            
            existing_user_ids = {p.user_id for p in profiles}
            for user_id in [user_a_id, user_b_id]:
                if user_id not in existing_user_ids:
                    profiles.append(UserToneProfile(
                        user_id=user_id,
                        style_summary="داده کافی برای تحلیل وجود نداشت"
                    ))
            
            analysis = ConversationAnalysis(
                conversation_id=conversation_id,
                relationship_class=rel_class,
                confidence=data.get("confidence", 0.7),
                reasoning=data.get("reasoning", ""),
                user_profiles=profiles,
            )
            
            return self._validate_and_adjust(analysis, len(messages))
            
        except json.JSONDecodeError as e:
            logger.error(f"tone_agent:analyze:json_error:{conversation_id}:{e}")
            return None
        except Exception as e:
            logger.error(f"tone_agent:analyze:error:{conversation_id}:{e}", exc_info=True)
            return None

    def _validate_and_adjust(
        self,
        analysis: ConversationAnalysis,
        message_count: int,
    ) -> ConversationAnalysis:
        adjusted = analysis
        
        if message_count < self._min_messages_for_reliable_class:
            penalty = (self._min_messages_for_reliable_class - message_count) * 0.05
            new_confidence = max(0.3, analysis.confidence - penalty)
            
            logger.info(
                f"tone_agent:validate:low_message_count:"
                f"conv={analysis.conversation_id}, count={message_count}, "
                f"confidence {analysis.confidence:.2f} -> {new_confidence:.2f}"
            )
            
            adjusted = ConversationAnalysis(
                conversation_id=analysis.conversation_id,
                relationship_class=analysis.relationship_class,
                confidence=new_confidence,
                reasoning=analysis.reasoning + f" (تعداد پیام کم: {message_count})",
                user_profiles=analysis.user_profiles,
            )
        
        if adjusted.confidence < self._fallback_confidence_threshold:
            logger.warning(
                f"tone_agent:validate:fallback_to_stranger:"
                f"conv={analysis.conversation_id}, "
                f"original_class={analysis.relationship_class}, "
                f"confidence={adjusted.confidence:.2f}"
            )
            
            adjusted = ConversationAnalysis(
                conversation_id=adjusted.conversation_id,
                relationship_class="stranger",
                confidence=adjusted.confidence,
                reasoning=f"Fallback: confidence پایین ({adjusted.confidence:.2f}). " + adjusted.reasoning,
                user_profiles=adjusted.user_profiles,
            )
        
        return adjusted

    def should_update_cluster(self, analysis: ConversationAnalysis) -> bool:
        return analysis.confidence >= self._min_confidence_threshold

    async def analyze_batch(
        self,
        conversations: List[Dict[str, Any]],
    ) -> List[ConversationAnalysis]:
        results = []
        
        for conv in conversations:
            analysis = await self.analyze_conversation(
                conversation_id=conv["conversation_id"],
                user_a_id=conv["user_a_id"],
                user_b_id=conv["user_b_id"],
                messages=conv.get("turns", []),
            )
            if analysis:
                results.append(analysis)
        
        return results

    async def analyze_for_dyadic(
        self,
        user_a: str,
        user_b: str,
        messages: List[Dict[str, str]],
    ) -> Tuple[Optional[ToneMetrics], Optional[ToneMetrics], Optional[str]]:
        analysis = await self.analyze_conversation(
            conversation_id=f"dyadic_{user_a}_{user_b}",
            user_a_id=user_a,
            user_b_id=user_b,
            messages=messages,
        )
        
        if not analysis:
            return None, None, None
        
        metrics_a = None
        metrics_b = None
        
        for profile in analysis.user_profiles:
            if profile.user_id == user_a:
                metrics_a = profile.to_tone_metrics()
            elif profile.user_id == user_b:
                metrics_b = profile.to_tone_metrics()
        
        return metrics_a, metrics_b, analysis.relationship_class

    def _format_conversation(self, messages: List[Dict[str, str]]) -> str:
        lines = []
        for msg in messages[:100]:
            speaker = msg.get("speaker", "unknown")
            text = msg.get("text", "")
            if text:
                lines.append(f"{speaker}: {text}")
        return "\n".join(lines)

    def _smart_sample_messages(
        self,
        messages: List[Dict[str, str]],
        max_tokens_estimate: int = 3000,
        chars_per_token: int = 4,
    ) -> List[Dict[str, str]]:
        if not messages:
            return []
        
        max_chars = max_tokens_estimate * chars_per_token
        
        total_chars = sum(len(msg.get("text", "")) + len(msg.get("speaker", "")) + 3 for msg in messages)
        
        if total_chars <= max_chars:
            return messages
        
        logger.info(
            f"tone_agent:smart_sample:truncating from {len(messages)} messages, "
            f"{total_chars} chars to ~{max_chars} chars"
        )
        
        n = len(messages)
        
        avg_msg_len = total_chars / n
        estimated_fit = int(max_chars / avg_msg_len)
        
        if estimated_fit >= n:
            return messages
        
        n_start = int(estimated_fit * 0.30)
        n_middle = int(estimated_fit * 0.40)
        n_end = int(estimated_fit * 0.30)
        
        start_msgs = messages[:n_start]
        
        middle_start = n // 2 - n_middle // 2
        middle_end = middle_start + n_middle
        middle_msgs = messages[middle_start:middle_end]
        
        end_msgs = messages[-n_end:] if n_end > 0 else []
        
        result = []
        result.extend(start_msgs)
        
        if n_start < middle_start:
            result.append({"speaker": "[system]", "text": f"... ({middle_start - n_start} پیام حذف شده) ..."})
        
        result.extend(middle_msgs)
        
        if middle_end < n - n_end:
            result.append({"speaker": "[system]", "text": f"... ({n - n_end - middle_end} پیام حذف شده) ..."})
        
        result.extend(end_msgs)
        
        logger.info(f"tone_agent:smart_sample:result:{len(result)} messages")
        return result

    def _balance_speakers(
        self,
        messages: List[Dict[str, str]],
    ) -> Dict[str, List[Dict[str, str]]]:
        by_speaker: Dict[str, List[Dict[str, str]]] = {}
        for msg in messages:
            speaker = msg.get("speaker", "unknown")
            if speaker not in by_speaker:
                by_speaker[speaker] = []
            by_speaker[speaker].append(msg)
        return by_speaker
