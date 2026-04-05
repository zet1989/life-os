"""Точка входа — мульти-бот архитектура.

Режим определяется настройкой USE_WEBHOOK:
- False (dev): Long Polling через asyncio.gather.
- True (prod): Webhooks через aiohttp на одном порту, роутинг по path.
"""

import asyncio
import signal

import structlog
from aiogram import Bot, Dispatcher
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.config import settings
from src.core.acl import ACLMiddleware

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        structlog.get_level_from_name(settings.log_level),
    ),
)
logger = structlog.get_logger()


async def _run_bot(
    token: str,
    bot_name: str,
    router,
    scheduler_factory=None,
) -> None:
    """Запуск одного бота в режиме Long Polling (dev)."""
    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.update.middleware(ACLMiddleware(bot_name=bot_name))
    dp.include_router(router)

    scheduler = None
    if scheduler_factory:
        scheduler = scheduler_factory(bot)
        scheduler.start()

    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("polling_started", bot=bot_name)
    try:
        await dp.start_polling(bot)
    finally:
        if scheduler:
            scheduler.shutdown(wait=False)


def _create_bot_dp(
    token: str,
    bot_name: str,
    router,
) -> tuple[Bot, Dispatcher]:
    """Создать Bot + Dispatcher (для webhook-режима)."""
    bot = Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
    )
    dp = Dispatcher()
    dp.update.middleware(ACLMiddleware(bot_name=bot_name))
    dp.include_router(router)
    return bot, dp


def _collect_bots() -> list[dict]:
    """Собрать список активных ботов с их роутерами и scheduler'ами."""
    bots_cfg = []

    if settings.bot_token_health:
        from src.bots.health.handlers import router as health_router
        from src.bots.health.scheduler import setup_scheduler as health_scheduler
        bots_cfg.append({"token": settings.bot_token_health, "name": "health", "router": health_router, "scheduler": health_scheduler})

    if settings.bot_token_assets:
        from src.bots.assets.handlers import router as assets_router
        from src.bots.assets.scheduler import setup_scheduler as assets_scheduler
        bots_cfg.append({"token": settings.bot_token_assets, "name": "assets", "router": assets_router, "scheduler": assets_scheduler})

    if settings.bot_token_business:
        from src.bots.business.handlers import router as business_router
        bots_cfg.append({"token": settings.bot_token_business, "name": "business", "router": business_router, "scheduler": None})

    if settings.bot_token_partner:
        from src.bots.partner.handlers import router as partner_router
        bots_cfg.append({"token": settings.bot_token_partner, "name": "partner", "router": partner_router, "scheduler": None})

    if settings.bot_token_mentor:
        from src.bots.mentor.handlers import router as mentor_router
        bots_cfg.append({"token": settings.bot_token_mentor, "name": "mentor", "router": mentor_router, "scheduler": None})

    if settings.bot_token_family:
        from src.bots.family.handlers import router as family_router
        bots_cfg.append({"token": settings.bot_token_family, "name": "family", "router": family_router, "scheduler": None})

    if settings.bot_token_psychology:
        from src.bots.psychology.handlers import router as psychology_router
        bots_cfg.append({"token": settings.bot_token_psychology, "name": "psychology", "router": psychology_router, "scheduler": None})

    if settings.bot_token_master:
        from src.bots.master.handlers import router as master_router
        from src.bots.master.scheduler import setup_scheduler as master_scheduler
        bots_cfg.append({"token": settings.bot_token_master, "name": "master", "router": master_router, "scheduler": master_scheduler})

    return bots_cfg


# === Polling mode (разработка) ===

async def _main_polling() -> None:
    bots_cfg = _collect_bots()
    if not bots_cfg:
        logger.error("no_bots_configured")
        return

    tasks = []
    for cfg in bots_cfg:
        tasks.append(
            asyncio.create_task(
                _run_bot(cfg["token"], cfg["name"], cfg["router"], cfg["scheduler"]),
                name=f"bot-{cfg['name']}",
            )
        )
        logger.info("bot_registered", bot=cfg["name"])

    logger.info("all_bots_starting", count=len(tasks), mode="polling")
    await asyncio.gather(*tasks)


# === Webhook mode (продакшен) ===

async def _main_webhook() -> None:
    from aiohttp import web

    bots_cfg = _collect_bots()
    if not bots_cfg:
        logger.error("no_bots_configured")
        return

    app = web.Application()
    instances: list[tuple[Bot, Dispatcher]] = []
    schedulers = []

    for cfg in bots_cfg:
        bot, dp = _create_bot_dp(cfg["token"], cfg["name"], cfg["router"])
        instances.append((bot, dp))

        # Webhook path: /webhook/<bot_name>
        path = f"/webhook/{cfg['name']}"

        async def make_handler(b=bot, d=dp):
            async def handler(request: web.Request) -> web.Response:
                # Верификация секрета
                if settings.webhook_secret:
                    token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
                    if token != settings.webhook_secret:
                        return web.Response(status=403)
                update = await request.json()
                from aiogram.types import Update
                telegram_update = Update.model_validate(update, context={"bot": b})
                await d.feed_update(bot=b, update=telegram_update)
                return web.Response(status=200)
            return handler

        app.router.add_post(path, await make_handler())

        # Scheduler
        if cfg["scheduler"]:
            sched = cfg["scheduler"](bot)
            sched.start()
            schedulers.append(sched)

        # Установить webhook
        webhook_url = f"{settings.webhook_host}{path}"
        await bot.set_webhook(
            url=webhook_url,
            secret_token=settings.webhook_secret or None,
            drop_pending_updates=True,
        )
        logger.info("webhook_set", bot=cfg["name"], url=webhook_url)

    # Health-check эндпоинт
    async def health_check(request: web.Request) -> web.Response:
        from src.core.health import get_status
        status = await get_status()
        code = 200 if status["ok"] else 503
        return web.json_response(status, status=code)

    app.router.add_get("/status", health_check)

    # Graceful shutdown
    async def on_shutdown(app: web.Application) -> None:
        logger.info("graceful_shutdown_started")
        for sched in schedulers:
            sched.shutdown(wait=False)
        for bot, dp in instances:
            await bot.delete_webhook()
            await bot.session.close()
        logger.info("graceful_shutdown_complete")

    app.on_shutdown.append(on_shutdown)

    logger.info("all_bots_starting", count=len(instances), mode="webhook", port=settings.webhook_port)
    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", settings.webhook_port)
    await site.start()

    # Ждём сигнала остановки
    stop_event = asyncio.Event()

    def _signal_handler() -> None:
        stop_event.set()

    loop = asyncio.get_running_loop()
    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            loop.add_signal_handler(sig, _signal_handler)
        except NotImplementedError:
            pass  # Windows

    await stop_event.wait()
    await runner.cleanup()


async def main() -> None:
    if settings.use_webhook:
        await _main_webhook()
    else:
        await _main_polling()


if __name__ == "__main__":
    asyncio.run(main())
