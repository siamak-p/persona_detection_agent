
from __future__ import annotations

import logging
from typing import Optional, TYPE_CHECKING

import asyncpg

if TYPE_CHECKING:
    pass

logger = logging.getLogger(__name__)


class SharedPostgresPool:
    
    _pool: Optional[asyncpg.Pool] = None
    _dsn: Optional[str] = None
    
    @classmethod
    async def get_pool(cls, dsn: str) -> asyncpg.Pool:
        if cls._pool is None:
            cls._dsn = dsn
            cls._pool = await asyncpg.create_pool(
                dsn=dsn,
                min_size=2,
                max_size=20,
            )
            logger.info(
                "shared_pool:created",
                extra={"min_size": 2, "max_size": 20},
            )
        return cls._pool
    
    @classmethod
    async def close(cls) -> None:
        if cls._pool is not None:
            await cls._pool.close()
            cls._pool = None
            logger.info("shared_pool:closed")
    
    @classmethod
    def is_initialized(cls) -> bool:
        return cls._pool is not None
