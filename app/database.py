from __future__ import annotations

from arcanus.materia.sqlalchemy import AsyncSession
from sqlalchemy.ext.asyncio import AsyncEngine, async_sessionmaker, create_async_engine

from app.configs import config

# Create async engine using the config
engine: AsyncEngine = create_async_engine(
    str(config.postgres_dsn),
    echo=False,
    pool_pre_ping=True,
    pool_size=8,
    max_overflow=16,
)

# Create async session factory using arcanus's AsyncSession
async_session_factory = async_sessionmaker(
    engine,
    class_=AsyncSession,
    expire_on_commit=False,
)

__all__ = [
    "engine",
    "async_session_factory",
]
