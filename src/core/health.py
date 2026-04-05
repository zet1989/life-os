"""Health-check: проверка доступности БД, Redis, API."""

import structlog

logger = structlog.get_logger()


async def get_status() -> dict:
    """Проверить доступность зависимостей."""
    checks = {
        "supabase": False,
        "redis": False,
    }
    ok = True

    # Supabase
    try:
        from src.db.supabase_client import get_supabase
        result = get_supabase().table("users").select("user_id").limit(1).execute()
        checks["supabase"] = True
    except Exception as e:
        logger.warning("health_check_supabase_fail", error=str(e))
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
