"""
SQLAlchemy async engine and session factory.

The async engine (asyncpg driver) is used by all FastAPI endpoints.
A separate sync engine is created inside ``app/worker/tasks.py`` for Celery,
which cannot use the async engine.

``echo`` is enabled only when ``LOG_LEVEL=DEBUG`` is set in the environment.
In all other modes SQLAlchemy query logging is suppressed to keep structured
log output clean.
"""

import os
from collections.abc import AsyncGenerator
from typing import Any

from sqlalchemy.ext.asyncio import AsyncSession, async_sessionmaker, create_async_engine

from app.core.config import settings

_echo_sql = os.getenv("LOG_LEVEL", "INFO").upper() == "DEBUG"

engine = create_async_engine(
    settings.DATABASE_URL_ASYNC,
    echo=_echo_sql,
    pool_pre_ping=True,
    pool_size=settings.DB_POOL_SIZE,
    max_overflow=settings.DB_MAX_OVERFLOW,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    expire_on_commit=False,
)


async def get_db() -> AsyncGenerator[AsyncSession, Any]:
    """FastAPI dependency that yields an async database session per request."""
    async with AsyncSessionLocal() as session:
        yield session
