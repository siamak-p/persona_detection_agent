
from __future__ import annotations

import logging
from contextlib import asynccontextmanager, contextmanager
from typing import Any, AsyncGenerator, Generator

logger = logging.getLogger(__name__)

from sqlalchemy import create_engine as sa_create_engine
from sqlalchemy.ext.asyncio import (
    create_async_engine as sa_create_async_engine,
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
)
from sqlalchemy.orm import sessionmaker, Session


def create_async_engine(
    dsn: str, *, echo: bool = False, pool_size: int = 5, max_overflow: int = 10
) -> AsyncEngine:
    return sa_create_async_engine(
        dsn,
        echo=echo,
        pool_size=pool_size,
        max_overflow=max_overflow,
        pool_pre_ping=True,
        future=True,
    )


def create_async_session_factory(engine: AsyncEngine) -> async_sessionmaker:
    return async_sessionmaker(
        engine,
        class_=AsyncSession,
        expire_on_commit=False,
    )


@asynccontextmanager
async def get_async_session(
    session_factory: async_sessionmaker,
) -> AsyncGenerator[AsyncSession, None]:
    async with session_factory() as session:
        try:
            yield session
            await session.commit()
        except Exception as e:
            logger.error("Database session error, rolling back: %s", e, exc_info=True)
            await session.rollback()
            raise
