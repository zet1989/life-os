"""PostgreSQL connection pool (asyncpg + pgvector).

Единая точка подключения к БД. Инициализация при старте, закрытие при остановке.
"""

import json

import asyncpg
import structlog
from pgvector.asyncpg import register_vector

from src.config import settings

logger = structlog.get_logger()

_pool: asyncpg.Pool | None = None


async def _init_connection(conn: asyncpg.Connection) -> None:
    """Настройка каждого нового соединения в пуле."""
    await register_vector(conn)
    await conn.set_type_codec(
        "jsonb", encoder=json.dumps, decoder=json.loads, schema="pg_catalog",
    )
    await conn.set_type_codec(
        "json", encoder=json.dumps, decoder=json.loads, schema="pg_catalog",
    )


async def init_pool() -> None:
    """Инициализация пула соединений. Вызывать при старте приложения."""
    global _pool
    _pool = await asyncpg.create_pool(
        settings.database_url,
        min_size=2,
        max_size=10,
        init=_init_connection,
    )
    logger.info("pg_pool_ready", min=2, max=10)


def get_pool() -> asyncpg.Pool:
    """Получить пул. Бросает AssertionError если пул не инициализирован."""
    assert _pool is not None, "DB pool not initialized. Call init_pool() first."
    return _pool


async def close_pool() -> None:
    """Закрыть пул соединений. Вызывать при остановке приложения."""
    global _pool
    if _pool:
        await _pool.close()
        _pool = None
        logger.info("pg_pool_closed")
