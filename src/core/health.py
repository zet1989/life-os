"""Health-check: проверка доступности БД, Redis, API."""

import structlog

logger = structlog.get_logger()


async def get_status() -> dict:
    """Проверить доступность зависимостей."""
    checks = {
        "postgres": False,
        "redis": False,
    }
    ok = True

    # PostgreSQL
    try:
        from src.db.postgres import get_pool
        pool = get_pool()
        val = await pool.fetchval("SELECT 1")
        checks["postgres"] = val == 1
    except Exception as e:
        logger.warning("health_check_postgres_fail", error=str(e))
        ok = False

    # Redis
    try:
        from src.config import settings
        import redis.asyncio as aioredis
        r = aioredis.from_url(settings.redis_url)
        await r.ping()
        await r.aclose()
        checks["redis"] = True
    except Exception as e:
        logger.warning("health_check_redis_fail", error=str(e))
        ok = False

    return {"ok": ok, "checks": checks}
