
from __future__ import annotations

import logging
from typing import List, Optional

from fastapi import APIRouter, Depends, HTTPException
from dependency_injector.wiring import inject, Provide
from pydantic import BaseModel, Field

from config.container import Container
from service.relationship_feedback_service import (
    RelationshipFeedbackService,
    FeedbackQuestion,
    VALID_RELATIONSHIP_CLASSES,
)
from db.postgres_relationship_cluster_personas import (
    RelationshipClusterPersonas,
)
from db.postgres_dyadic_overrides import (
    DyadicOverrides,
)
from db.postgres_future_requests import (
    PostgresFutureRequests,
    FutureRequest,
    FutureRequestStatus,
)
from db.postgres_financial_threads import (
    PostgresFinancialThreads,
    FinancialThread,
    FinancialThreadStatus,
    WaitingFor,
)
from memory.mem0_adapter import Mem0Adapter

logger = logging.getLogger(__name__)

RELATIONSHIP_LABELS = {
    "spouse": "همسر",
    "family": "خانواده",
    "boss": "کارمند شما",
    "subordinate": "رئیس شما",
    "colleague": "همکار",
    "friend": "دوست",
    "stranger": "ناشناس",
}

router = APIRouter(prefix="/api/v1/feedback", tags=["Relationship Feedback"])


class QuestionResponse(BaseModel):
    id: int
    about_user_id: str = Field(description="کاربری که راجع بهش می‌پرسیم")
    question_text: str = Field(description="متن سوال")
    conversation_summary: str = Field(description="خلاصه مکالمه")
    sample_messages: List[str] = Field(default_factory=list, description="نمونه پیام‌ها")
    status: str = Field(description="pending|answered|expired|skipped")
    sent_count: int = Field(description="تعداد دفعات ارسال")
    created_at: str


class QuestionsListResponse(BaseModel):
    questions: List[QuestionResponse]
    future_requests: List["FutureRequestResponse"] = Field(
        default_factory=list, 
        description="لیست درخواست‌های برنامه‌ریزی آینده"
    )
    has_unread: bool = Field(description="آیا سوالات یا درخواست خوانده نشده دارد")
    total_count: int = Field(description="مجموع سوالات و درخواست‌ها")


class SubmitAnswerRequest(BaseModel):
    question_id: int = Field(description="شناسه سوال")
    relationship_class: str = Field(
        description="کلاس رابطه: spouse, family, boss, colleague, friend"
    )
    answer_text: Optional[str] = Field(default=None, description="توضیحات اختیاری")


class SubmitAnswerResponse(BaseModel):
    success: bool
    message: str


class SkipQuestionRequest(BaseModel):
    question_id: int = Field(description="شناسه سوال")


class HasUnreadResponse(BaseModel):
    has_unread: bool
    count: int


class RelationshipClassesResponse(BaseModel):
    classes: List[dict]


class QuestionLimitStatusResponse(BaseModel):
    questions_asked_in_window: int = Field(description="تعداد سوالات پرسیده شده در بازه فعلی")
    questions_remaining: int = Field(description="تعداد سوالات باقی‌مانده در بازه فعلی")
    max_questions_per_window: int = Field(description="حداکثر سوالات در هر بازه")
    window_hours: int = Field(description="طول بازه زمانی به ساعت")
    window_description: str = Field(description="توضیح فارسی بازه زمانی")


class FutureRequestResponse(BaseModel):
    id: int
    sender_id: str = Field(description="شناسه فرستنده درخواست")
    sender_name: Optional[str] = Field(default=None, description="نام فرستنده (اگر موجود باشد)")
    relationship_class: Optional[str] = Field(default=None, description="کلاس رابطه با فرستنده")
    relationship_label: Optional[str] = Field(default=None, description="برچسب فارسی رابطه")
    original_message: str = Field(description="پیام اصلی فرستنده")
    detected_plan: str = Field(description="برنامه تشخیص داده شده")
    detected_datetime: Optional[str] = Field(default=None, description="زمان تشخیص داده شده")
    status: str = Field(description="pending|answered|delivered|expired")
    created_at: str
    created_at_formatted: Optional[str] = Field(default=None, description="زمان فرمت‌شده فارسی")


class FutureRequestsListResponse(BaseModel):
    requests: List[FutureRequestResponse]
    total_count: int


class SubmitFutureResponseRequest(BaseModel):
    request_id: int = Field(description="شناسه درخواست")
    response_text: str = Field(description="پاسخ کاربر به درخواست")


@inject
async def get_feedback_service(
    service: RelationshipFeedbackService = Depends(
        Provide[Container.relationship_feedback_service]
    ),
) -> RelationshipFeedbackService:
    return service


@inject
async def get_relationship_cluster(
    cluster: RelationshipClusterPersonas = Depends(
        Provide[Container.postgres_relationship_cluster_personas]
    ),
) -> RelationshipClusterPersonas:
    return cluster


@inject
async def get_dyadic_overrides(
    dyadic: DyadicOverrides = Depends(
        Provide[Container.postgres_dyadic_overrides]
    ),
) -> DyadicOverrides:
    return dyadic


@inject
async def get_future_requests(
    future_requests: PostgresFutureRequests = Depends(
        Provide[Container.postgres_future_requests]
    ),
) -> PostgresFutureRequests:
    return future_requests


@inject
async def get_financial_threads(
    financial_threads: PostgresFinancialThreads = Depends(
        Provide[Container.postgres_financial_threads]
    ),
) -> PostgresFinancialThreads:
    return financial_threads


@inject
async def get_memory_adapter(
    memory: Mem0Adapter = Depends(
        Provide[Container.mem0_adapter]
    ),
) -> Mem0Adapter:
    return memory


@inject
async def get_chat_store(
    chat_store = Depends(
        Provide[Container.postgres_chat_store]
    ),
):
    return chat_store


async def _get_sender_name(memory: Mem0Adapter, sender_id: str) -> Optional[str]:
    try:
        memories = await memory.get_memories(sender_id, limit=100)
        for m in memories:
            text = (m.get("memory") or "").strip()
            if text.lower().startswith("name:") or text.startswith("نام:") or text.startswith("اسم:"):
                return text.split(":", 1)[1].strip()
        return None
    except Exception as e:
        logger.warning(f"feedback:get_sender_name:error:{sender_id}:{e}")
        return None


def _format_datetime_persian(dt) -> str:
    try:
        weekdays = ["دوشنبه", "سه‌شنبه", "چهارشنبه", "پنج‌شنبه", "جمعه", "شنبه", "یکشنبه"]
        weekday = weekdays[dt.weekday()]
        
        hour = dt.hour
        minute = dt.minute
        
        return f"{weekday} ساعت {hour}:{minute:02d}"
    except Exception:
        return dt.isoformat() if dt else ""


@router.get(
    "/questions/{user_id}",
    response_model=QuestionsListResponse,
    summary="دریافت سوالات و درخواست‌های pending کاربر",
    description="لیست سوالاتی که از کاربر درباره روابطش پرسیده شده + درخواست‌های برنامه‌ریزی آینده",
)
async def get_user_questions(
    user_id: str,
    feedback_service: RelationshipFeedbackService = Depends(get_feedback_service),
    future_requests: PostgresFutureRequests = Depends(get_future_requests),
    relationship_cluster: RelationshipClusterPersonas = Depends(get_relationship_cluster),
    memory: Mem0Adapter = Depends(get_memory_adapter),
) -> QuestionsListResponse:
    try:
        questions = await feedback_service.get_pending_questions(user_id)
        has_unread_questions = await feedback_service.has_unread_questions(user_id)
        
        pending_future = await future_requests.get_pending_for_creator(user_id)
        
        future_responses = []
        for fr in pending_future:
            sender_name = await _get_sender_name(memory, fr.sender_id)
            
            rel_class = await relationship_cluster.find_cluster_for_member(
                user_id=user_id,
                member_user_id=fr.sender_id,
            )
            rel_label = RELATIONSHIP_LABELS.get(rel_class) if rel_class else None
            
            future_responses.append(
                FutureRequestResponse(
                    id=fr.id,
                    sender_id=fr.sender_id,
                    sender_name=sender_name,
                    relationship_class=rel_class,
                    relationship_label=rel_label,
                    original_message=fr.original_message,
                    detected_plan=fr.detected_plan,
                    detected_datetime=fr.detected_datetime,
                    status=fr.status.value,
                    created_at=fr.created_at.isoformat(),
                    created_at_formatted=_format_datetime_persian(fr.created_at),
                )
            )
        
        has_unread = has_unread_questions or len(pending_future) > 0
        total = len(questions) + len(pending_future)
        
        return QuestionsListResponse(
            questions=[
                QuestionResponse(
                    id=q.id,
                    about_user_id=q.about_user_id,
                    question_text=q.question_text,
                    conversation_summary=q.conversation_summary,
                    sample_messages=q.sample_messages,
                    status=q.status,
                    sent_count=q.sent_count,
                    created_at=q.created_at.isoformat(),
                )
                for q in questions
            ],
            future_requests=future_responses,
            has_unread=has_unread,
            total_count=total,
        )
        
    except Exception as e:
        logger.error(f"feedback:get_questions:error:{user_id}:{e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/has-unread/{user_id}",
    response_model=HasUnreadResponse,
    summary="بررسی سوالات و درخواست‌های خوانده نشده",
    description="آیا کاربر سوالات یا درخواست‌های خوانده نشده دارد؟",
)
async def check_has_unread(
    user_id: str,
    feedback_service: RelationshipFeedbackService = Depends(get_feedback_service),
    future_requests: PostgresFutureRequests = Depends(get_future_requests),
    financial_threads: PostgresFinancialThreads = Depends(get_financial_threads),
) -> HasUnreadResponse:
    try:
        questions = await feedback_service.get_pending_questions(user_id)
        pending_future = await future_requests.get_pending_for_creator(user_id)
        
        financial_count = await financial_threads.get_waiting_for_creator_count(user_id)
        
        total = len(questions) + len(pending_future) + financial_count
        
        return HasUnreadResponse(
            has_unread=total > 0,
            count=total,
        )
        
    except Exception as e:
        logger.error(f"feedback:has_unread:error:{user_id}:{e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/limit-status/{user_id}",
    response_model=QuestionLimitStatusResponse,
    summary="وضعیت محدودیت سوالات",
    description="نمایش تعداد سوالات پرسیده شده و باقی‌مانده در بازه زمانی فعلی",
)
async def get_question_limit_status(
    user_id: str,
    feedback_service: RelationshipFeedbackService = Depends(get_feedback_service),
) -> QuestionLimitStatusResponse:
    try:
        asked = await feedback_service.get_questions_count_in_window(user_id)
        remaining = await feedback_service.get_remaining_questions_in_window(user_id)
        max_q = feedback_service._max_questions_per_window
        window_hours = feedback_service._question_window_hours
        
        if window_hours == 24:
            desc = f"روزی {max_q} سوال"
        elif window_hours == 1:
            desc = f"ساعتی {max_q} سوال"
        else:
            desc = f"هر {window_hours} ساعت {max_q} سوال"
        
        return QuestionLimitStatusResponse(
            questions_asked_in_window=asked,
            questions_remaining=remaining,
            max_questions_per_window=max_q,
            window_hours=window_hours,
            window_description=desc,
        )
        
    except Exception as e:
        logger.error(f"feedback:limit_status:error:{user_id}:{e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/answer",
    response_model=SubmitAnswerResponse,
    summary="ثبت پاسخ کاربر",
    description="ثبت پاسخ کاربر به سوال رابطه",
)
async def submit_answer(
    request: SubmitAnswerRequest,
    feedback_service: RelationshipFeedbackService = Depends(get_feedback_service),
    relationship_cluster: RelationshipClusterPersonas = Depends(get_relationship_cluster),
    dyadic_overrides: DyadicOverrides = Depends(get_dyadic_overrides),
) -> SubmitAnswerResponse:
    rel_class = request.relationship_class.lower().strip()
    if rel_class not in VALID_RELATIONSHIP_CLASSES:
        raise HTTPException(
            status_code=400,
            detail=f"کلاس رابطه نامعتبر. گزینه‌های معتبر: {VALID_RELATIONSHIP_CLASSES}",
        )
    
    try:
        question = await feedback_service.get_question_by_id(request.question_id)
        if not question:
            raise HTTPException(status_code=404, detail="سوال یافت نشد")
        
        success, message = await feedback_service.submit_answer(
            question_id=request.question_id,
            relationship_class=rel_class,
            answer_text=request.answer_text,
        )
        
        if not success:
            raise HTTPException(status_code=400, detail=message)
        
        try:
            await feedback_service.apply_to_cluster_and_dyadic(
                user_id=question.asking_user_id,
                related_user_id=question.about_user_id,
                relationship_class=rel_class,
                rel_cluster=relationship_cluster,
                dyadic=dyadic_overrides,
            )
            logger.info(
                f"feedback:apply_cluster_dyadic:success:"
                f"{question.asking_user_id}<->{question.about_user_id}={rel_class}"
            )
        except Exception as cluster_error:
            logger.error(
                f"feedback:apply_cluster_dyadic:error:{cluster_error}",
                exc_info=True,
            )
        
        return SubmitAnswerResponse(success=True, message=message)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"feedback:answer:error:{request.question_id}:{e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/skip",
    response_model=SubmitAnswerResponse,
    summary="رد کردن سوال",
    description="رد کردن سوال و عدم پرسش مجدد",
)
async def skip_question(
    request: SkipQuestionRequest,
    feedback_service: RelationshipFeedbackService = Depends(get_feedback_service),
) -> SubmitAnswerResponse:
    try:
        success, message = await feedback_service.skip_question(request.question_id)
        
        if not success:
            raise HTTPException(status_code=400, detail=message)
        
        return SubmitAnswerResponse(success=True, message=message)
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"feedback:skip:error:{request.question_id}:{e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/relationship-classes",
    response_model=RelationshipClassesResponse,
    summary="دریافت کلاس‌های رابطه",
    description="لیست کلاس‌های رابطه معتبر با توضیحات",
)
async def get_relationship_classes() -> RelationshipClassesResponse:
    return RelationshipClassesResponse(
        classes=[
            {"id": "spouse", "name": "همسر", "emoji": "💑", "description": "همسر شما"},
            {"id": "family", "name": "خانواده", "emoji": "👨‍👩‍👧‍👦", "description": "پدر، مادر، خواهر، برادر"},
            {"id": "boss", "name": "رئیس/معلم", "emoji": "👔", "description": "مدیر، سرپرست یا معلم شما"},
            {"id": "subordinate", "name": "کارمند/شاگرد", "emoji": "👨‍🎓", "description": "کارمند، زیردست یا شاگرد شما"},
            {"id": "colleague", "name": "همکار", "emoji": "💼", "description": "همکار در محل کار"},
            {"id": "friend", "name": "دوست", "emoji": "🤝", "description": "دوست و رفیق"},
            {"id": "stranger", "name": "غریبه", "emoji": "😶", "description": "کسی که نمی‌شناسید یا فقط یکبار باهاش صحبت کردید"},
        ]
    )


@router.get(
    "/future-requests/{user_id}",
    response_model=FutureRequestsListResponse,
    summary="دریافت درخواست‌های برنامه‌ریزی آینده",
    description="لیست درخواست‌هایی که از twin این کاربر پرسیده شده و منتظر پاسخ است",
)
async def get_future_requests_for_user(
    user_id: str,
    future_requests: PostgresFutureRequests = Depends(get_future_requests),
) -> FutureRequestsListResponse:
    try:
        requests = await future_requests.get_pending_for_creator(user_id)
        
        return FutureRequestsListResponse(
            requests=[
                FutureRequestResponse(
                    id=req.id,
                    sender_id=req.sender_id,
                    original_message=req.original_message,
                    detected_plan=req.detected_plan,
                    detected_datetime=req.detected_datetime,
                    status=req.status.value,
                    created_at=req.created_at.isoformat(),
                )
                for req in requests
            ],
            total_count=len(requests),
        )
        
    except Exception as e:
        logger.error(
            "feedback:future_requests:get:error",
            extra={"user_id": user_id, "error": str(e)},
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/future-requests/respond",
    response_model=SubmitAnswerResponse,
    summary="ثبت پاسخ به درخواست برنامه‌ریزی",
    description="ثبت پاسخ کاربر به درخواست برنامه‌ریزی آینده",
)
async def submit_future_request_response(
    request: SubmitFutureResponseRequest,
    future_requests: PostgresFutureRequests = Depends(get_future_requests),
    memory: Mem0Adapter = Depends(get_memory_adapter),
    chat_store = Depends(get_chat_store),
) -> SubmitAnswerResponse:
    try:
        req = await future_requests.get_request_by_id(request.request_id)
        if not req:
            raise HTTPException(status_code=404, detail="درخواست یافت نشد")
        
        if req.status != FutureRequestStatus.PENDING:
            raise HTTPException(
                status_code=400,
                detail=f"درخواست در وضعیت {req.status.value} است و قابل پاسخ‌دهی نیست"
            )
        
        success = await future_requests.submit_creator_response(
            request_id=request.request_id,
            creator_response=request.response_text,
        )
        
        if success:
            logger.info(
                "feedback:future_requests:respond:success",
                extra={
                    "request_id": request.request_id,
                    "response_preview": request.response_text[:100],
                },
            )
            
            creator_name = await _get_sender_name(memory, req.recipient_id)
            name_part = creator_name or req.recipient_id
            
            if req.conversation_id and chat_store:
                try:
                    response_message = f"📬 درباره درخواستت ({req.detected_plan}):\n{name_part} گفت: {request.response_text}"
                    
                    await chat_store.log_event(
                        author_id=req.recipient_id,
                        user_a=req.sender_id,
                        user_b=req.recipient_id,
                        conversation_id=req.conversation_id,
                        text=response_message,
                        role="ai",
                    )
                    
                    logger.info(
                        "feedback:future_requests:chat_store_saved",
                        extra={
                            "request_id": request.request_id,
                            "conversation_id": req.conversation_id,
                        },
                    )
                    
                    
                except Exception as chat_error:
                    logger.warning(
                        "feedback:future_requests:chat_store_failed",
                        extra={"error": str(chat_error)},
                    )
            else:
                logger.warning(
                    "feedback:future_requests:no_conversation_id",
                    extra={
                        "request_id": request.request_id,
                        "has_conversation_id": bool(req.conversation_id),
                        "has_chat_store": bool(chat_store),
                    },
                )
            
            try:
                from api.routers.websocket_notifications import notify_future_response
                
                ws_sent = await notify_future_response(
                    sender_id=req.sender_id,
                    recipient_id=req.recipient_id,
                    recipient_name=creator_name,
                    detected_plan=req.detected_plan,
                    creator_response=request.response_text,
                )
                
                if ws_sent:
                    logger.info(
                        "feedback:future_requests:ws_notification_sent",
                        extra={"sender_id": req.sender_id},
                    )
                    
            except Exception as ws_error:
                logger.warning(
                    "feedback:future_requests:ws_notification_failed",
                    extra={"error": str(ws_error)},
                )
            
            return SubmitAnswerResponse(
                success=True,
                message="پاسخ شما ثبت شد و در چت طرف مقابل نمایش داده می‌شود ✅",
            )
        else:
            raise HTTPException(status_code=400, detail="خطا در ثبت پاسخ")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "feedback:future_requests:respond:error",
            extra={"request_id": request.request_id, "error": str(e)},
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/future-requests/count/{user_id}",
    summary="تعداد درخواست‌های pending",
    description="تعداد درخواست‌های برنامه‌ریزی که منتظر پاسخ هستند",
)
async def get_future_requests_count(
    user_id: str,
    future_requests: PostgresFutureRequests = Depends(get_future_requests),
) -> dict:
    try:
        count = await future_requests.get_pending_count_for_creator(user_id)
        return {"count": count, "has_pending": count > 0}
    except Exception as e:
        logger.error(
            "feedback:future_requests:count:error",
            extra={"user_id": user_id, "error": str(e)},
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(e))


class SenderRequestResponse(BaseModel):
    id: int
    recipient_id: str = Field(description="شناسه گیرنده (صاحب Twin)")
    original_message: str = Field(description="پیام اصلی شما")
    detected_plan: str = Field(description="برنامه تشخیص داده شده")
    status: str = Field(description="pending|answered|delivered")
    creator_response: Optional[str] = Field(default=None, description="پاسخ کاربر حقیقی")
    responded_at: Optional[str] = Field(default=None, description="زمان پاسخ")
    created_at: str


@router.get(
    "/my-requests/{sender_id}",
    summary="درخواست‌های من",
    description="لیست درخواست‌هایی که من به دیگران فرستاده‌ام",
)
async def get_my_requests(
    sender_id: str,
    future_requests: PostgresFutureRequests = Depends(get_future_requests),
) -> dict:
    try:
        requests = await future_requests.get_requests_by_sender(sender_id)
        
        return {
            "requests": [
                SenderRequestResponse(
                    id=req.id,
                    recipient_id=req.recipient_id,
                    original_message=req.original_message,
                    detected_plan=req.detected_plan,
                    status=req.status.value,
                    creator_response=req.creator_response,
                    responded_at=req.responded_at.isoformat() if req.responded_at else None,
                    created_at=req.created_at.isoformat(),
                )
                for req in requests
            ],
            "total_count": len(requests),
            "pending_count": sum(1 for r in requests if r.status == FutureRequestStatus.PENDING),
            "answered_count": sum(1 for r in requests if r.status == FutureRequestStatus.ANSWERED),
        }
        
    except Exception as e:
        logger.error(
            "feedback:my_requests:error",
            extra={"sender_id": sender_id, "error": str(e)},
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(e))


class FinancialThreadMessageResponse(BaseModel):
    id: int
    author_type: str
    message: str
    created_at: str


class FinancialThreadResponse(BaseModel):
    id: int
    sender_id: str
    sender_name: Optional[str] = None
    relationship_type: Optional[str] = None
    topic_summary: str
    last_sender_message: Optional[str] = None
    last_creator_response: Optional[str] = None
    recent_messages: List[FinancialThreadMessageResponse] = []
    status: str
    waiting_for: str
    created_at: str
    last_activity_at: str


class FinancialThreadsListResponse(BaseModel):
    threads: List[FinancialThreadResponse]
    total_count: int
    waiting_for_response_count: int


class SubmitFinancialResponseRequest(BaseModel):
    thread_id: int = Field(..., description="شناسه thread")
    response_text: str = Field(..., min_length=1, description="متن پاسخ")


class CloseFinancialThreadRequest(BaseModel):
    thread_id: int = Field(..., description="شناسه thread")


def get_financial_threads() -> PostgresFinancialThreads:
    from config.container import Container
    container = Container()
    return container.postgres_financial_threads()


@router.get(
    "/financial-threads/{user_id}",
    response_model=FinancialThreadsListResponse,
    summary="دریافت thread های مالی",
    description="دریافت thread های مالی باز برای یک کاربر (creator)",
)
async def get_financial_threads_for_user(
    user_id: str,
    financial_threads: PostgresFinancialThreads = Depends(get_financial_threads),
) -> FinancialThreadsListResponse:
    from config.container import Container
    
    try:
        container = Container()
        mem0_adapter = container.mem0_adapter()
        rel_cluster = container.postgres_relationship_cluster_personas()
        
        threads = await financial_threads.get_open_threads_for_creator(user_id)
        waiting_count = sum(
            1 for t in threads if t.waiting_for == WaitingFor.CREATOR
        )
        
        thread_responses = []
        for t in threads:
            recent_msgs = await financial_threads.get_recent_messages(
                thread_id=t.id,
                limit=3,
            )
            
            sender_name = None
            relationship_type = None
            try:
                summary = await mem0_adapter.get_summary(
                    user_a=user_id,
                    user_b=t.sender_id,
                )
                if summary:
                    import re
                    name_match = re.search(r'نام[:\s]+([^\n,]+)', summary)
                    if name_match:
                        sender_name = name_match.group(1).strip()
                
                rel_class, _ = await rel_cluster.find_cluster_with_confidence(
                    user_id=user_id,
                    partner_id=t.sender_id,
                )
                if rel_class:
                    relationship_type = rel_class
            except Exception:
                pass
            
            thread_responses.append(
                FinancialThreadResponse(
                    id=t.id,
                    sender_id=t.sender_id,
                    sender_name=sender_name,
                    relationship_type=relationship_type,
                    topic_summary=t.topic_summary,
                    last_sender_message=t.last_sender_message,
                    last_creator_response=t.last_creator_response,
                    recent_messages=[
                        FinancialThreadMessageResponse(
                            id=m.id,
                            author_type=m.author_type,
                            message=m.message,
                            created_at=m.created_at.isoformat(),
                        )
                        for m in recent_msgs
                    ],
                    status=t.status.value,
                    waiting_for=t.waiting_for.value,
                    created_at=t.created_at.isoformat(),
                    last_activity_at=t.last_activity_at.isoformat(),
                )
            )
        
        return FinancialThreadsListResponse(
            threads=thread_responses,
            total_count=len(threads),
            waiting_for_response_count=waiting_count,
        )
        
    except Exception as e:
        logger.error(
            "feedback:financial_threads:get_error",
            extra={"user_id": user_id, "error": str(e)},
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/financial-threads/respond",
    response_model=SubmitAnswerResponse,
    summary="ثبت پاسخ در thread مالی",
    description="ثبت پاسخ creator در یک thread مالی",
)
async def submit_financial_thread_response(
    request: SubmitFinancialResponseRequest,
    financial_threads: PostgresFinancialThreads = Depends(get_financial_threads),
    chat_store = Depends(get_chat_store),
) -> SubmitAnswerResponse:
    try:
        thread = await financial_threads.get_thread_by_id(request.thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")
        
        if thread.status != FinancialThreadStatus.OPEN:
            raise HTTPException(
                status_code=400,
                detail="این موضوع بسته شده است",
            )
        
        await financial_threads.add_message(
            thread_id=request.thread_id,
            author_type="creator",
            message=request.response_text,
        )
        
        if chat_store:
            try:
                await chat_store.log_event(
                    author_id=thread.creator_id,
                    user_a=thread.creator_id,
                    user_b=thread.sender_id,
                    conversation_id=thread.conversation_id,
                    text=f"[پاسخ به موضوع مالی: {thread.topic_summary}]\n{request.response_text}",
                    role="ai",
                )
                logger.info(
                    "feedback:financial_threads:response_logged_to_chat_events",
                    extra={
                        "thread_id": request.thread_id,
                        "creator_id": thread.creator_id,
                    },
                )
            except Exception as log_error:
                logger.warning(
                    "feedback:financial_threads:chat_events_log_failed",
                    extra={"error": str(log_error)},
                )
        
        try:
            from api.routers.websocket_notifications import notify_financial_response_to_sender
            await notify_financial_response_to_sender(
                sender_id=thread.sender_id,
                creator_id=thread.creator_id,
                creator_name=None,
                thread_id=thread.id,
                topic_summary=thread.topic_summary,
                creator_response=request.response_text,
            )
        except Exception as ws_error:
            logger.warning(
                "feedback:financial_threads:ws_error",
                extra={"thread_id": request.thread_id, "error": str(ws_error)},
            )
        
        logger.info(
            "feedback:financial_threads:response_submitted",
            extra={
                "thread_id": request.thread_id,
                "creator_id": thread.creator_id,
                "sender_id": thread.sender_id,
            },
        )
        
        return SubmitAnswerResponse(
            success=True,
            message="پاسخ شما ثبت شد و به طرف مقابل ارسال می‌شود ✅",
        )
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "feedback:financial_threads:respond_error",
            extra={"thread_id": request.thread_id, "error": str(e)},
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/financial-threads/{thread_id}/close",
    response_model=SubmitAnswerResponse,
    summary="بستن thread مالی",
    description="بستن دستی یک thread مالی توسط creator",
)
async def close_financial_thread(
    thread_id: int,
    financial_threads: PostgresFinancialThreads = Depends(get_financial_threads),
) -> SubmitAnswerResponse:
    try:
        thread = await financial_threads.get_thread_by_id(thread_id)
        if not thread:
            raise HTTPException(status_code=404, detail="Thread not found")
        
        if thread.status != FinancialThreadStatus.OPEN:
            raise HTTPException(
                status_code=400,
                detail="این موضوع قبلاً بسته شده است",
            )
        
        success = await financial_threads.update_thread_status(
            thread_id=thread_id,
            new_status=FinancialThreadStatus.RESOLVED,
        )
        
        if success:
            logger.info(
                "feedback:financial_threads:closed_manually",
                extra={"thread_id": thread_id, "creator_id": thread.creator_id},
            )
            return SubmitAnswerResponse(
                success=True,
                message="موضوع مالی بسته شد ✅",
            )
        else:
            raise HTTPException(status_code=500, detail="Failed to close thread")
        
    except HTTPException:
        raise
    except Exception as e:
        logger.error(
            "feedback:financial_threads:close_error",
            extra={"thread_id": thread_id, "error": str(e)},
            exc_info=True,
        )
        raise HTTPException(status_code=500, detail=str(e))
