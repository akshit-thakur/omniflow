from contextlib import asynccontextmanager
from typing import AsyncIterator

import asyncpg

from .settings import get_settings

_pool: asyncpg.Pool | None = None
EXPECTED_ALEMBIC_REVISION = "010_finite_numeric_constraints"


async def open_pool() -> None:
    global _pool
    if _pool is not None:
        return
    settings = get_settings()
    connection_arguments = (
        {
            "host": settings.database_host,
            "port": settings.database_port,
            "database": settings.database_name,
            "user": settings.database_user,
            "password": settings.database_password,
        }
        if settings.database_host
        else {"dsn": settings.database_url}
    )
    _pool = await asyncpg.create_pool(
        **connection_arguments,
        min_size=settings.pool_min_size,
        max_size=settings.pool_max_size,
        command_timeout=settings.db_command_timeout,
        max_inactive_connection_lifetime=300,
    )


async def close_pool() -> None:
    global _pool
    if _pool is not None:
        await _pool.close()
        _pool = None


@asynccontextmanager
async def connection() -> AsyncIterator[asyncpg.Connection]:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")
    async with _pool.acquire() as conn:
        yield conn


async def ready() -> bool:
    """Prove the connection points at an initialized OmniFlow schema."""
    async with connection() as conn:
        return bool(
            await conn.fetchval(
                """
                SELECT (SELECT count(*) = 1 FROM alembic_version)
                   AND EXISTS(
                       SELECT 1 FROM alembic_version WHERE version_num = $1
                   )
                   AND to_regclass('public.tasks') IS NOT NULL
                   AND to_regclass('public.ai_entity_embeddings') IS NOT NULL
                   AND to_regclass('public.ai_action_requests') IS NOT NULL
                   AND to_regclass('public.ai_action_proposals') IS NOT NULL
                """,
                EXPECTED_ALEMBIC_REVISION,
            )
        )
