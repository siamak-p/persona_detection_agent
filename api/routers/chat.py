
from fastapi import APIRouter, Header, Depends
from dependency_injector.wiring import inject, Provide

from orchestrator.messages import ChatRequest, ChatResponse
from config.container import Container
from service.chat_service import ChatService

router = APIRouter(prefix="/api/v1", tags=["Chat"])


@inject
async def get_chat_service(
    service: ChatService = Depends(Provide[Container.chat_service]),
) -> ChatService:
    return service


@router.post("/chat", response_model=ChatResponse)
async def chat_endpoint(
    payload: ChatRequest,
    x_correlation_id: str | None = Header(None, alias="X-Correlation-Id"),
    chat_service: ChatService = Depends(get_chat_service),
) -> ChatResponse:
    import uuid

    correlation_id = x_correlation_id or str(uuid.uuid4())

    result = await chat_service.handle_chat(
        user_id=payload.user_id,
        to_user_id=payload.to_user_id,
        language=payload.language,
        message=payload.message,
        message_id=payload.message_id,
        conversation_id=payload.conversation_id,
        timestamp=payload.timestamp,
        correlation_id=correlation_id,
        voice_data=payload.voice_data,
        input_type=payload.input_type,
        voice_format=payload.voice_format,
    )

    return ChatResponse(**result)
