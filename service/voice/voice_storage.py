
from __future__ import annotations

import logging
from pathlib import Path
from typing import Optional
import aiofiles
import aiofiles.os

from .base import VoiceStorageProvider

logger = logging.getLogger(__name__)


class LocalVoiceStorage(VoiceStorageProvider):
    def __init__(self, base_path: str = "/data/voices"):
        self._base_path = Path(base_path)
        self._base_path.mkdir(parents=True, exist_ok=True)
        logger.info("voice_storage:init", extra={"base_path": str(self._base_path)})

    async def save(
        self,
        audio_data: bytes,
        conversation_id: str,
        message_id: str,
        prefix: str = "response",
    ) -> str:
        conv_dir = self._base_path / conversation_id
        conv_dir.mkdir(parents=True, exist_ok=True)

        filename = f"{prefix}_{message_id}.mp3"
        file_path = conv_dir / filename

        logger.info(
            "voice_storage:save:start",
            extra={
                "conversation_id": conversation_id,
                "message_id": message_id,
                "prefix": prefix,
                "size": len(audio_data),
            },
        )

        try:
            async with aiofiles.open(file_path, "wb") as f:
                await f.write(audio_data)

            url = f"/voices/{conversation_id}/{filename}"

            logger.info(
                "voice_storage:save:success",
                extra={"url": url, "size": len(audio_data)},
            )

            return url

        except Exception as e:
            logger.error(
                "voice_storage:save:error",
                extra={"conversation_id": conversation_id, "error": str(e)},
                exc_info=True,
            )
            raise

    async def get(self, url: str) -> Optional[bytes]:
        relative_path = url.replace("/voices/", "").lstrip("/")
        file_path = self._base_path / relative_path

        try:
            if not file_path.exists():
                logger.warning("voice_storage:get:not_found", extra={"url": url})
                return None

            async with aiofiles.open(file_path, "rb") as f:
                data = await f.read()

            logger.info(
                "voice_storage:get:success",
                extra={"url": url, "size": len(data)},
            )

            return data

        except Exception as e:
            logger.error(
                "voice_storage:get:error",
                extra={"url": url, "error": str(e)},
                exc_info=True,
            )
            return None

    async def delete(self, url: str) -> bool:
        relative_path = url.replace("/voices/", "").lstrip("/")
        file_path = self._base_path / relative_path

        try:
            if not file_path.exists():
                logger.warning("voice_storage:delete:not_found", extra={"url": url})
                return False

            await aiofiles.os.remove(file_path)

            logger.info("voice_storage:delete:success", extra={"url": url})

            return True

        except Exception as e:
            logger.error(
                "voice_storage:delete:error",
                extra={"url": url, "error": str(e)},
                exc_info=True,
            )
            return False

    async def save_input(
        self,
        voice_data_base64: str,
        conversation_id: str,
        message_id: str,
    ) -> str:
        import base64
        audio_bytes = base64.b64decode(voice_data_base64)
        return await self.save(
            audio_bytes,
            conversation_id,
            message_id,
            prefix="input",
        )
