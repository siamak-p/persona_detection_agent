
from fastapi import APIRouter, Depends
from dependency_injector.wiring import inject, Provide

from orchestrator.messages import PassiveLastMessageIdResponse
from config.container import Container
from service.passive_service import PassiveService

router = APIRouter(prefix="/api/v1", tags=["Passive"])


@inject
async def get_passive_service(
    service: PassiveService = Depends(Provide[Container.passive_service]),
) -> PassiveService:
    return service


@router.get("/passive/last-msgId", response_model=PassiveLastMessageIdResponse)
async def get_last_message_id(
    passive_service: PassiveService = Depends(get_passive_service),
) -> PassiveLastMessageIdResponse:
    result = await passive_service.get_last_message_id()
    return PassiveLastMessageIdResponse(**result)
