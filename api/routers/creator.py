
from fastapi import APIRouter, Header, Depends
from dependency_injector.wiring import inject, Provide

from orchestrator.messages import CreatorRequest, CreatorResponse
from config.container import Container
from service.creator_service import CreatorService

router = APIRouter(prefix="/api/v1", tags=["Creator"])


@inject
async def get_creator_service(
    service: CreatorService = Depends(Provide[Container.creator_service]),
) -> CreatorService:
    return service


@router.post("/creator", response_model=CreatorResponse)
async def creator_endpoint(
    payload: CreatorRequest,
    x_correlation_id: str | None = Header(None, alias="X-Correlation-Id"),
    creator_service: CreatorService = Depends(get_creator_service),
) -> CreatorResponse:
    import uuid

    correlation_id = x_correlation_id or str(uuid.uuid4())

    result = await creator_service.handle_creator(
        user_id=payload.user_id,
        language=payload.language,
        message=payload.message,
        message_id=payload.message_id,
        timestamp=payload.timestamp,
        correlation_id=correlation_id,
        voice_data=payload.voice_data,
        input_type=payload.input_type,
        voice_format=payload.voice_format,
    )

    return CreatorResponse(**result)
