
import logging
from pathlib import Path

from fastapi import APIRouter, HTTPException
from fastapi.responses import FileResponse

from config.settings import Settings

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/voices", tags=["Voice"])

_settings = Settings()
VOICE_PATH = Path(_settings.VOICE_STORAGE_PATH)


@router.get("/{conversation_id}/{filename}")
async def get_voice_file(conversation_id: str, filename: str) -> FileResponse:
    file_path = VOICE_PATH / conversation_id / filename

    logger.info(
        "voice_static:get_file",
        extra={
            "conversation_id": conversation_id,
            "filename": filename,
            "path": str(file_path),
        },
    )

    if not file_path.exists():
        logger.warning("voice_static:file_not_found", extra={"path": str(file_path)})
        raise HTTPException(status_code=404, detail="Voice file not found")

    try:
        file_path.resolve().relative_to(VOICE_PATH.resolve())
    except ValueError:
        logger.error("voice_static:path_traversal_attempt", extra={"path": str(file_path)})
        raise HTTPException(status_code=403, detail="Access denied")

    return FileResponse(
        file_path,
        media_type="audio/mpeg",
        filename=filename,
    )
