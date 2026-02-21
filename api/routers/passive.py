
import logging
import uuid

from fastapi import APIRouter, Header, Depends
from dependency_injector.wiring import inject, Provide

from orchestrator.messages import PassiveRecordItem, PassiveRecordResponse
from config.container import Container
from service.passive_service import PassiveService

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/api/v1", tags=["Passive"])


@inject
async def get_passive_service(
    service: PassiveService = Depends(Provide[Container.passive_service]),
) -> PassiveService:
    return service


@router.post("/passive", response_model=PassiveRecordResponse)
async def passive_endpoint(
    payload: list[PassiveRecordItem],
    x_correlation_id: str | None = Header(None, alias="X-Correlation-Id"),
    passive_service: PassiveService = Depends(get_passive_service),
) -> PassiveRecordResponse:
    correlation_id = x_correlation_id or str(uuid.uuid4())
    
    logger.info(
        "Passive observation received: correlation_id=%s, items_count=%d",
        correlation_id,
        len(payload),
    )

    items = [item.dict() for item in payload]
    try:
        result = await passive_service.record_observations(items, correlation_id)
        logger.info(
            "Passive observation recorded successfully: correlation_id=%s",
            correlation_id,
        )
        return PassiveRecordResponse(**result)
    except Exception as e:
        logger.error(
            "Passive observation failed: correlation_id=%s, error=%s",
            correlation_id,
            e,
            exc_info=True,
        )
        raise
