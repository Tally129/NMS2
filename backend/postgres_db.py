"""
Async PostgreSQL database infrastructure.

This module exists alongside the current MongoDB connection during the
migration. Importing it does not switch the application away from MongoDB.
"""

from __future__ import annotations

import os
from collections.abc import AsyncIterator
from pathlib import Path

from dotenv import load_dotenv
from sqlalchemy import text
from sqlalchemy.ext.asyncio import (
    AsyncEngine,
    AsyncSession,
    async_sessionmaker,
    create_async_engine,
)

# Defensive: postgres_db can be imported before other modules have loaded the
# `.env` (e.g. Alembic env, tests). Load it here idempotently so DATABASE_URL
# is present regardless of import order.
load_dotenv(Path(__file__).resolve().parent / ".env")


def _get_database_url() -> str:
    raw_url = os.environ.get("DATABASE_URL", "").strip()

    if not raw_url:
        raise RuntimeError("DATABASE_URL is not configured")

    # SQLAlchemy's async engine requires an async-compatible dialect.
    # psycopg 3 supports both sync and async operation.
    if raw_url.startswith("postgres://"):
        raw_url = raw_url.replace(
            "postgres://",
            "postgresql+psycopg://",
            1,
        )
    elif raw_url.startswith("postgresql://"):
        raw_url = raw_url.replace(
            "postgresql://",
            "postgresql+psycopg://",
            1,
        )

    return raw_url


DATABASE_URL = _get_database_url()

engine: AsyncEngine = create_async_engine(
    DATABASE_URL,
    pool_pre_ping=True,
    pool_recycle=1800,
    echo=False,
)

AsyncSessionLocal = async_sessionmaker(
    bind=engine,
    class_=AsyncSession,
    expire_on_commit=False,
    autoflush=False,
)


async def get_postgres_session() -> AsyncIterator[AsyncSession]:
    """FastAPI dependency that provides one SQLAlchemy session per request."""
    async with AsyncSessionLocal() as session:
        try:
            yield session
        except Exception:
            await session.rollback()
            raise


async def check_postgres_connection() -> bool:
    """Run a minimal connection test without revealing credentials."""
    async with engine.connect() as connection:
        result = await connection.execute(text("SELECT 1"))
        return result.scalar_one() == 1


async def close_postgres() -> None:
    """Dispose of PostgreSQL connection-pool resources."""
    await engine.dispose()
