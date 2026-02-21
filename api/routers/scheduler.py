
from __future__ import annotations

import logging
from typing import Dict, Any, List

from fastapi import APIRouter, Depends, HTTPException
from dependency_injector.wiring import inject, Provide
from pydantic import BaseModel, Field

from config.container import Container

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1/admin/scheduler", tags=["Admin - Scheduler"])


class SchedulerRunResponse(BaseModel):
    success: bool
    scheduler: str
    message: str
    stats: Dict[str, Any] = Field(default_factory=dict)


class ToneRetryStatsResponse(BaseModel):
    retry_total: int
    retry_pending: int
    failed_total: int


class SummaryRetryStatsResponse(BaseModel):
    retry_total: int
    retry_pending: int
    failed_total: int


class PassiveSummarizationStatsResponse(BaseModel):
    retry_total: int
    retry_pending: int
    failed_total: int


class PassiveSummarizationResponse(BaseModel):
    success: bool
    message: str
    stats: Dict[str, Any] = Field(default_factory=dict)


@inject
def get_tone_scheduler(
    scheduler=Depends(Provide[Container.tone_scheduler]),
):
    return scheduler


@inject
def get_tone_retry_worker(
    worker=Depends(Provide[Container.tone_retry_worker]),
):
    return worker


@inject
def get_tone_retry_storage(
    storage=Depends(Provide[Container.tone_retry_storage]),
):
    return storage


@inject
def get_feedback_scheduler(
    scheduler=Depends(Provide[Container.feedback_scheduler]),
):
    return scheduler


@inject
def get_retry_worker(
    worker=Depends(Provide[Container.retry_worker]),
):
    return worker


@inject
def get_chat_store(
    store=Depends(Provide[Container.postgres_chat_store]),
):
    return store


@inject
def get_listener_agent(
    listener=Depends(Provide[Container.listener_agent]),
):
    return listener


@inject
def get_passive_summarization_scheduler(
    scheduler=Depends(Provide[Container.passive_summarization_scheduler]),
):
    return scheduler


@inject
def get_passive_summarization_retry_worker(
    worker=Depends(Provide[Container.passive_summarization_retry_worker]),
):
    return worker


@inject
def get_passive_summarization_storage(
    storage=Depends(Provide[Container.passive_summarization_storage]),
):
    return storage


@router.post(
    "/tone/run",
    response_model=SchedulerRunResponse,
    summary="اجرای دستی ToneScheduler",
    description="استخراج لحن از پیام‌های passive و آپدیت relationship clusters",
)
async def run_tone_scheduler(
    tone_scheduler=Depends(get_tone_scheduler),
) -> SchedulerRunResponse:
    try:
        logger.info("admin:scheduler:tone:manual_run:start")
        
        stats = await tone_scheduler.process_passive_batch()
        
        logger.info(f"admin:scheduler:tone:manual_run:done:{stats}")
        
        return SchedulerRunResponse(
            success=True,
            scheduler="ToneScheduler",
            message="اجرا با موفقیت انجام شد",
            stats=stats,
        )
        
    except Exception as e:
        logger.error(f"admin:scheduler:tone:manual_run:error:{e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/tone-retry/run",
    response_model=SchedulerRunResponse,
    summary="اجرای دستی ToneRetryWorker",
    description="پردازش صف retry تحلیل لحن",
)
async def run_tone_retry_worker(
    tone_retry_worker=Depends(get_tone_retry_worker),
) -> SchedulerRunResponse:
    try:
        logger.info("admin:scheduler:tone_retry:manual_run:start")
        
        stats = await tone_retry_worker.process_retries()
        
        logger.info(f"admin:scheduler:tone_retry:manual_run:done:{stats}")
        
        return SchedulerRunResponse(
            success=True,
            scheduler="ToneRetryWorker",
            message="اجرا با موفقیت انجام شد",
            stats=stats,
        )
        
    except Exception as e:
        logger.error(f"admin:scheduler:tone_retry:manual_run:error:{e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/tone-retry/stats",
    response_model=ToneRetryStatsResponse,
    summary="آمار صف retry لحن",
    description="تعداد رکوردها در صف retry و failed",
)
async def get_tone_retry_stats(
    tone_retry_storage=Depends(get_tone_retry_storage),
) -> ToneRetryStatsResponse:
    try:
        stats = await tone_retry_storage.get_stats()
        return ToneRetryStatsResponse(**stats)
    except Exception as e:
        logger.error(f"admin:scheduler:tone_retry:stats:error:{e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/feedback/run",
    response_model=SchedulerRunResponse,
    summary="اجرای دستی FeedbackScheduler",
    description="ایجاد سوالات رابطه برای کاربران با روابط stranger",
)
async def run_feedback_scheduler(
    feedback_scheduler=Depends(get_feedback_scheduler),
) -> SchedulerRunResponse:
    try:
        logger.info("admin:scheduler:feedback:manual_run:start")
        
        stats = await feedback_scheduler.run_once()
        
        logger.info(f"admin:scheduler:feedback:manual_run:done:{stats}")
        
        return SchedulerRunResponse(
            success=True,
            scheduler="FeedbackScheduler",
            message="اجرا با موفقیت انجام شد",
            stats=stats,
        )
        
    except Exception as e:
        logger.error(f"admin:scheduler:feedback:manual_run:error:{e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


class ChatSummaryRequest(BaseModel):
    user_id: str = Field(..., description="شناسه کاربر اصلی")
    to_user_id: str = Field(..., description="شناسه کاربر مقابل")
    conversation_id: str = Field(..., description="شناسه مکالمه")


@router.post(
    "/chat-summary/run",
    response_model=SchedulerRunResponse,
    summary="اجرای دستی خلاصه‌سازی چت",
    description="خلاصه‌سازی یک مکالمه چت خاص و ذخیره در Qdrant",
)
async def run_chat_summary(
    request: ChatSummaryRequest,
    listener=Depends(get_listener_agent),
) -> SchedulerRunResponse:
    try:
        logger.info(
            "admin:scheduler:chat_summary:manual_run:start",
            extra={
                "user_id": request.user_id,
                "to_user_id": request.to_user_id,
                "conversation_id": request.conversation_id,
            },
        )
        
        await listener.check_and_trigger_summarization(
            memory_owner_id=request.user_id,
            partner_user_id=request.to_user_id,
            conversation_id=request.conversation_id,
        )
        
        logger.info("admin:scheduler:chat_summary:manual_run:done")
        
        return SchedulerRunResponse(
            success=True,
            scheduler="ChatSummary",
            message="خلاصه‌سازی با موفقیت انجام شد",
            stats={
                "user_id": request.user_id,
                "to_user_id": request.to_user_id,
                "conversation_id": request.conversation_id,
            },
        )
        
    except Exception as e:
        logger.error(f"admin:scheduler:chat_summary:manual_run:error:{e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/retry/run",
    response_model=SchedulerRunResponse,
    summary="اجرای دستی RetryWorker",
    description="پردازش job های ناموفق خلاصه‌سازی",
)
async def run_retry_worker(
    retry_worker=Depends(get_retry_worker),
) -> SchedulerRunResponse:
    try:
        logger.info("admin:scheduler:retry:manual_run:start")
        
        stats = await retry_worker._process_pending_retries()
        
        logger.info(f"admin:scheduler:retry:manual_run:done:{stats}")
        
        return SchedulerRunResponse(
            success=True,
            scheduler="RetryWorker",
            message="اجرا با موفقیت انجام شد",
            stats=stats,
        )
        
    except Exception as e:
        logger.error(f"admin:scheduler:retry:manual_run:error:{e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/retry/stats",
    response_model=SummaryRetryStatsResponse,
    summary="آمار صف retry خلاصه‌سازی",
    description="تعداد رکوردها در صف retry و failed خلاصه‌سازی",
)
async def get_summary_retry_stats(
    chat_store=Depends(get_chat_store),
) -> SummaryRetryStatsResponse:
    try:
        stats = await chat_store.get_retry_queue_stats()
        return SummaryRetryStatsResponse(**stats)
    except Exception as e:
        logger.error(f"admin:scheduler:retry:stats:error:{e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/status",
    summary="وضعیت scheduler ها",
    description="نمایش تنظیمات و interval هر scheduler",
)
@inject
async def get_scheduler_status(
    settings=Depends(Provide[Container.settings]),
    tone_retry_storage=Depends(get_tone_retry_storage),
    chat_store=Depends(get_chat_store),
    passive_summ_storage=Depends(get_passive_summarization_storage),
) -> Dict[str, Any]:
    tone_hours = settings.TONE_SCHEDULER_INTERVAL_SECONDS / 3600
    feedback_hours = settings.FEEDBACK_SCHEDULER_INTERVAL_SECONDS / 3600
    retry_minutes = settings.SUMMARY_RETRY_WORKER_INTERVAL_SECONDS / 60
    tone_retry_minutes = settings.TONE_RETRY_WORKER_INTERVAL_SECONDS / 60
    passive_summ_hours = getattr(settings, "PASSIVE_SUMMARIZATION_INTERVAL_SECONDS", 3600) / 3600
    passive_summ_retry_minutes = getattr(settings, "PASSIVE_SUMMARIZATION_RETRY_INTERVAL_SECONDS", 300) / 60
    
    try:
        tone_retry_stats = await tone_retry_storage.get_stats()
    except Exception:
        tone_retry_stats = {"retry_total": 0, "retry_pending": 0, "failed_total": 0}
    
    try:
        summary_retry_stats = await chat_store.get_retry_queue_stats()
    except Exception:
        summary_retry_stats = {"retry_total": 0, "retry_pending": 0, "failed_total": 0}
    
    try:
        passive_summ_stats = await passive_summ_storage.get_stats()
    except Exception:
        passive_summ_stats = {"retry_total": 0, "retry_pending": 0, "failed_total": 0}
    
    return {
        "scheduler_enabled": settings.SCHEDULER_ENABLED,
        "tone_scheduler": {
            "interval_hours": round(tone_hours, 1),
            "max_conversations": settings.TONE_SCHEDULER_MAX_CONVERSATIONS,
            "batch_size": settings.TONE_SCHEDULER_BATCH_SIZE,
        },
        "tone_retry_worker": {
            "interval_minutes": round(tone_retry_minutes, 1),
            "max_attempts": settings.TONE_RETRY_MAX_ATTEMPTS,
            "retry_delays": settings.TONE_RETRY_DELAYS_SECONDS,
            "queue_stats": tone_retry_stats,
        },
        "feedback_scheduler": {
            "interval_hours": round(feedback_hours, 1),
        },
        "summary_retry_worker": {
            "interval_minutes": round(retry_minutes, 1),
            "max_attempts": settings.SUMMARY_RETRY_MAX_ATTEMPTS,
            "retry_delays": settings.SUMMARY_RETRY_DELAYS_SECONDS,
            "queue_stats": summary_retry_stats,
        },
        "passive_summarization_scheduler": {
            "interval_hours": round(passive_summ_hours, 1),
            "batch_size": getattr(settings, "PASSIVE_SUMMARIZATION_BATCH_SIZE", 10),
            "min_messages": getattr(settings, "PASSIVE_SUMMARIZATION_MIN_MESSAGES", 20),
        },
        "passive_summarization_retry_worker": {
            "interval_minutes": round(passive_summ_retry_minutes, 1),
            "max_attempts": getattr(settings, "PASSIVE_SUMMARIZATION_MAX_ATTEMPTS", 3),
            "retry_delays": getattr(settings, "PASSIVE_SUMMARIZATION_RETRY_DELAYS", "300,3600,14400"),
            "queue_stats": passive_summ_stats,
        },
    }


@router.post(
    "/passive-summarization/run",
    response_model=SchedulerRunResponse,
    summary="اجرای دستی خلاصه‌سازی passive",
    description="خلاصه‌سازی پیام‌های آرشیو شده passive و ذخیره در Qdrant",
)
async def run_passive_summarization(
    scheduler=Depends(get_passive_summarization_scheduler),
) -> SchedulerRunResponse:
    try:
        logger.info("admin:scheduler:passive_summarization:manual_run:start")
        
        stats = await scheduler.process_batch()
        
        logger.info(f"admin:scheduler:passive_summarization:manual_run:done:{stats}")
        
        return SchedulerRunResponse(
            success=True,
            scheduler="PassiveSummarizationScheduler",
            message="اجرا با موفقیت انجام شد",
            stats=stats,
        )
        
    except Exception as e:
        logger.error(f"admin:scheduler:passive_summarization:manual_run:error:{e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/passive-summarization-retry/run",
    response_model=SchedulerRunResponse,
    summary="اجرای دستی PassiveSummarizationRetryWorker",
    description="پردازش صف retry خلاصه‌سازی passive",
)
async def run_passive_summarization_retry(
    worker=Depends(get_passive_summarization_retry_worker),
) -> SchedulerRunResponse:
    try:
        logger.info("admin:scheduler:passive_summarization_retry:manual_run:start")
        
        stats = await worker.process_retries()
        
        logger.info(f"admin:scheduler:passive_summarization_retry:manual_run:done:{stats}")
        
        return SchedulerRunResponse(
            success=True,
            scheduler="PassiveSummarizationRetryWorker",
            message="اجرا با موفقیت انجام شد",
            stats=stats,
        )
        
    except Exception as e:
        logger.error(f"admin:scheduler:passive_summarization_retry:manual_run:error:{e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/passive-summarization/stats",
    response_model=PassiveSummarizationStatsResponse,
    summary="آمار صف retry خلاصه‌سازی passive",
    description="تعداد رکوردها در صف retry و failed خلاصه‌سازی passive",
)
async def get_passive_summarization_stats(
    storage=Depends(get_passive_summarization_storage),
) -> PassiveSummarizationStatsResponse:
    try:
        stats = await storage.get_stats()
        return PassiveSummarizationStatsResponse(**stats)
    except Exception as e:
        logger.error(f"admin:scheduler:passive_summarization:stats:error:{e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.post(
    "/passive-summarization/retry-failed/{failed_id}",
    response_model=Dict[str, Any],
    summary="انتقال یک خلاصه‌سازی از failed به retry",
    description="یک خلاصه‌سازی ناموفق را دوباره به صف retry اضافه می‌کند",
)
async def retry_failed_passive_summarization(
    failed_id: int,
    storage=Depends(get_passive_summarization_storage),
) -> Dict[str, Any]:
    try:
        new_retry_id = await storage.retry_failed(failed_id)
        if new_retry_id is None:
            raise HTTPException(status_code=404, detail=f"Failed summarization {failed_id} not found")
        
        return {
            "success": True,
            "failed_id": failed_id,
            "new_retry_id": new_retry_id,
            "message": "Moved to retry queue successfully",
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"admin:scheduler:passive_summarization:retry_failed:error:{e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))


@router.get(
    "/passive-summarization/failed",
    response_model=List[Dict[str, Any]],
    summary="لیست خلاصه‌سازی‌های ناموفق passive",
    description="دریافت لیست خلاصه‌سازی‌هایی که بعد از 3 تلاش ناموفق بوده‌اند",
)
async def list_failed_passive_summarizations(
    limit: int = 100,
    offset: int = 0,
    storage=Depends(get_passive_summarization_storage),
) -> List[Dict[str, Any]]:
    try:
        failed_items = await storage.get_failed(limit=limit, offset=offset)
        return [
            {
                "id": f.id,
                "conversation_id": f.conversation_id,
                "pair_id": f.pair_id,
                "user_a": f.user_a,
                "user_b": f.user_b,
                "message_ids": f.message_ids,
                "attempt_count": f.attempt_count,
                "last_error": f.last_error,
                "created_at": f.created_at.isoformat(),
                "failed_at": f.failed_at.isoformat(),
            }
            for f in failed_items
        ]
    except Exception as e:
        logger.error(f"admin:scheduler:passive_summarization:failed:list:error:{e}", exc_info=True)
        raise HTTPException(status_code=500, detail=str(e))
