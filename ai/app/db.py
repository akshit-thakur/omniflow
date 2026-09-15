import asyncio
from contextlib import asynccontextmanager
import logging
from typing import AsyncIterator

import asyncpg

from .settings import get_settings


logger = logging.getLogger(__name__)

_pool: asyncpg.Pool | None = None


async def open_pool() -> None:
    global _pool
    if _pool is None:
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
            min_size=1,
            max_size=5,
            command_timeout=60,
            max_inactive_connection_lifetime=300,
        )


async def close_pool(*, timeout_seconds: float = 5.0) -> None:
    global _pool
    pool = _pool
    _pool = None
    if pool is None:
        return
    try:
        await asyncio.wait_for(pool.close(), timeout=timeout_seconds)
    except TimeoutError:
        logger.warning("Database pool did not close in time; terminating connections")
        pool.terminate()


@asynccontextmanager
async def connection() -> AsyncIterator[asyncpg.Connection]:
    if _pool is None:
        raise RuntimeError("Database pool is not initialized")
    async with _pool.acquire() as conn:
        yield conn
