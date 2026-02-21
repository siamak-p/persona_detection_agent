
from __future__ import annotations

from typing import Any, Optional

from db.passive_storage import PassiveStorage


class PassiveMemory:

    def __init__(self, storage: PassiveStorage) -> None:
        self._storage = storage

    async def get(self, limit: int = 100) -> list[dict] | dict | None:
        return await self._storage.get(limit=limit)

    async def clear(self) -> None:
        await self._storage.clear()
