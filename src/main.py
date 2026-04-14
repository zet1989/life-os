"""Точка входа — мульти-бот / unified-бот архитектура.

Режимы:
1. Unified (bot_token_unified задан): один бот, все секции через меню.
2. Multi-bot (legacy): отдельный бот на каждый токен.

Транспорт определяется USE_WEBHOOK:
- False (dev): Long Polling.
- True (prod): Webhooks через aiohttp.
"""

import asyncio
import logging
import signal

import structlog
from aiogram import Bot, Dispatcher, Router
from aiogram.client.default import DefaultBotProperties
from aiogram.enums import ParseMode

from src.config import settings
from src.core.acl import ACLMiddleware
from src.db.postgres import close_pool, init_pool

structlog.configure(
    wrapper_class=structlog.make_filtering_bound_logger(
        logging.getLevelName(settings.log_level.upper()),
    ),
)
logger = structlog.get_logger()


def _make_bot(token: str) -> Bot:
    """Создать Bot-инстанс с прокси (если настроен TELEGRAM_PROXY)."""
    session = None
    if settings.telegram_proxy:
        from aiogram.client.session.aiohttp import AiohttpSession
        session = AiohttpSession(proxy=settings.telegram_proxy)
        logger.info("bot_proxy_enabled", proxy=settings.telegram_proxy)
    return Bot(
        token=token,
        default=DefaultBotProperties(parse_mode=ParseMode.HTML),
        session=session,
    )


# ─────────────────────────────────────────────────────────
#  Unified mode — единый бот-хаб
# ─────────────────────────────────────────────────────────

def _collect_unified() -> dict:
    """Собрать unified-бота: один токен, все секции через SectionFilter."""
    from src.bots.hub.keyboard import set_unified_mode
    from src.bots.hub.handlers import router as hub_router
    from src.bots.hub.section_filter import SectionFilter

    set_unified_mode()  # включить кнопку 🏠 Меню в клавиатурах секций

    routers: list[Router] = [hub_router]  # Hub первый — ловит /start, 🏠 Меню
    scheduler_factories = []

    # Health
    from src.bots.health.handlers import router as health_router, watch_router
    from src.bots.health.scheduler import setup_scheduler as health_scheduler
    health_router.message.filter(SectionFilter("health"))
    health_router.callback_query.filter(SectionFilter("health"))
    routers.append(watch_router)   # watch_router БЕЗ SectionFilter — /watch_connect из любой секции
    routers.append(health_router)
    scheduler_factories.append(health_scheduler)

    # Assets
    from src.bots.assets.handlers import router as assets_router
    from src.bots.assets.scheduler import setup_scheduler as assets_scheduler
    assets_router.message.filter(SectionFilter("assets"))
    assets_router.callback_query.filter(SectionFilter("assets"))
    routers.append(assets_router)
    scheduler_factories.append(assets_scheduler)

    # Business
    from src.bots.business.handlers import router as business_router
    from src.bots.business.scheduler import setup_scheduler as business_scheduler
    business_router.message.filter(SectionFilter("business"))
    business_router.callback_query.filter(SectionFilter("business"))
    routers.append(business_router)
    scheduler_factories.append(business_scheduler)

    # Partner
    from src.bots.partner.handlers import router as partner_router
    partner_router.message.filter(SectionFilter("partner"))
    partner_router.callback_query.filter(SectionFilter("partner"))
    routers.append(partner_router)

    # Mentor
    from src.bots.mentor.handlers import router as mentor_router
    mentor_router.message.filter(SectionFilter("mentor"))
    mentor_router.callback_query.filter(SectionFilter("mentor"))
    routers.append(mentor_router)

    # Family
    from src.bots.family.handlers import router as family_router
    family_router.message.filter(SectionFilter("family"))
    family_router.callback_query.filter(SectionFilter("family"))
    routers.append(family_router)

    # Psychology
    from src.bots.psychology.handlers import router as psychology_router
    from src.bots.psychology.scheduler import setup_scheduler as psychology_scheduler
    psychology_router.message.filter(SectionFilter("psychology"))
    psychology_router.callback_query.filter(SectionFilter("psychology"))
    routers.append(psychology_router)
    scheduler_factories.append(psychology_scheduler)

    # Master
    from src.bots.master.handlers import router as master_router
    from src.bots.master.scheduler import setup_scheduler as master_scheduler
    master_router.message.filter(SectionFilter("master"))
    master_router.callback_query.filter(SectionFilter("master"))
    routers.append(master_router)
    scheduler_factories.append(master_scheduler)

    return {
        "token": settings.bot_token_unified,
        "routers": routers,
        "scheduler_factories": scheduler_factories,
    }


async def _run_unified_polling() -> None:
    """Запуск единого бота в режиме Long Polling + aiohttp для webapp."""
    import asyncio
    from aiohttp import web

    cfg = _collect_unified()

    bot = _make_bot(cfg["token"])
    dp = Dispatcher()
    dp.update.middleware(ACLMiddleware(bot_name="unified"))

    for r in cfg["routers"]:
        dp.include_router(r)

    schedulers = []
    for factory in cfg["scheduler_factories"]:
        sched = factory(bot)
        sched.start()
        schedulers.append(sched)

    await bot.delete_webhook(drop_pending_updates=True)
    logger.info("unified_polling_started", sections=len(cfg["routers"]) - 1)

    # Запускаем aiohttp-сервер для webapp/status даже в polling-режиме
    app = web.Application()

    async def health_check(request: web.Request) -> web.Response:
        from src.core.health import get_status
        status = await get_status()
        code = 200 if status["ok"] else 503
        return web.json_response(status, status=code)

    app.router.add_get("/status", health_check)

    from src.webapp import setup_webapp_routes
    setup_webapp_routes(app)

    # Amazfit Watch push endpoint
    async def watch_push_handler(request: web.Request) -> web.Response:
        """Принять push-данные от Amazfit Balance 2."""
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return web.json_response({"error": "missing auth"}, status=401)
        api_key = auth[7:]

        from src.db.queries import get_watch_user_by_api_key, update_watch_last_push
        wt = await get_watch_user_by_api_key(api_key)
        if not wt:
            return web.json_response({"error": "invalid key"}, status=403)

        try:
            payload = await request.json()
        except Exception as exc:
            logger.error("watch_push_json_error", error=str(exc), content_type=request.content_type)
            body_raw = await request.text()
            logger.error("watch_push_raw_body", body=body_raw[:500])
            return web.json_response({"error": "invalid json"}, status=400)

        from src.integrations.amazfit import process_watch_push
        data = await process_watch_push(wt["user_id"], payload)
        await update_watch_last_push(wt["user_id"])

        return web.json_response({"ok": True, "saved_keys": list(data.keys())})

    app.router.add_post("/api/watch/push", watch_push_handler)

    runner = web.AppRunner(app)
    await runner.setup()
    site = web.TCPSite(runner, "0.0.0.0", settings.webhook_port or 8443)
    await site.start()
    logger.info("webapp_server_started", port=settings.webhook_port or 8443, mode="polling")

    try:
        await dp.start_polling(bot)
    finally:
        for sched in schedulers:
            sched.shutdown(wait=False)
        await runner.cleanup()


async def _run_unified_webhook(app, instances, schedulers) -> None:
    """Настроить webhook для единого бота."""
    from aiohttp import web

    cfg = _collect_unified()

    bot = _make_bot(cfg["token"])
    dp = Dispatcher()
    dp.update.middleware(ACLMiddleware(bot_name="unified"))

    for r in cfg["routers"]:
        dp.include_router(r)

    instances.append((bot, dp))

    path = "/webhook/unified"

    async def webhook_handler(request: web.Request) -> web.Response:
        if settings.webhook_secret:
            token = request.headers.get("X-Telegram-Bot-Api-Secret-Token", "")
            if token != settings.webhook_secret:
                logger.warning("webhook_secret_mismatch")
                return web.Response(status=403)
        try:
            update = await request.json()
            logger.info("webhook_received", update_id=update.get("update_id"))
            from aiogram.types import Update
            telegram_update = Update.model_validate(update, context={"bot": bot})
            await dp.feed_update(bot=bot, update=telegram_update)
            logger.info("webhook_processed", update_id=update.get("update_id"))
        except Exception as e:
            logger.error("webhook_handler_error", error=str(e), error_type=type(e).__name__)
        return web.Response(status=200)

    app.router.add_post(path, webhook_handler)

    for factory in cfg["scheduler_factories"]:
        sched = factory(bot)
        sched.start()
        schedulers.append(sched)

    webhook_url = f"{settings.webhook_host}{path}"
    try:
        await bot.set_webhook(
            url=webhook_url,
            secret_token=settings.webhook_secret or None,
            drop_pending_updates=True,
        )
        logger.info("unified_webhook_set", url=webhook_url, sections=len(cfg["routers"]) - 1)
    except Exception as e:
        logger.error("unified_webhook_set_failed", url=webhook_url, error=str(e))


# ─────────────────────────────────────────────────────────
#  Legacy multi-bot mode
# ─────────────────────────────────────────────────────────

async def _run_bot(
    token: str,
    bot_name: str,
    router,
    scheduler_factory=None,
) -> None:
    """Запуск одного бота в режиме Long Polling (dev)."""
    bot = _make_bot(token)
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
    bot = _make_bot(token)
    dp = Dispatcher()
    dp.update.middleware(ACLMiddleware(bot_name=bot_name))
    dp.include_router(router)
    return bot, dp


def _collect_bots() -> list[dict]:
    """Собрать список активных ботов (legacy multi-bot mode)."""
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
        from src.bots.psychology.scheduler import setup_scheduler as psychology_scheduler
        bots_cfg.append({"token": settings.bot_token_psychology, "name": "psychology", "router": psychology_router, "scheduler": psychology_scheduler})

    if settings.bot_token_master:
        from src.bots.master.handlers import router as master_router
        from src.bots.master.scheduler import setup_scheduler as master_scheduler
        bots_cfg.append({"token": settings.bot_token_master, "name": "master", "router": master_router, "scheduler": master_scheduler})

    return bots_cfg


# ─────────────────────────────────────────────────────────
#  Entrypoints
# ─────────────────────────────────────────────────────────

async def _main_polling() -> None:
    await init_pool()

    # Obsidian watcher
    from src.integrations.obsidian.watcher import start_watcher
    await start_watcher(user_id=settings.admin_user_id)

    # Unified mode: один бот, все секции
    if settings.bot_token_unified:
        logger.info("mode_unified", transport="polling")
        try:
            await _run_unified_polling()
        finally:
            await close_pool()
        return

    # Legacy multi-bot mode
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
    try:
        await asyncio.gather(*tasks)
    finally:
        await close_pool()


async def _main_webhook() -> None:
    from aiohttp import web

    await init_pool()

    # Obsidian watcher
    from src.integrations.obsidian.watcher import start_watcher
    await start_watcher(user_id=settings.admin_user_id)

    app = web.Application()
    instances: list[tuple[Bot, Dispatcher]] = []
    schedulers = []

    # Unified mode: один бот, все секции
    if settings.bot_token_unified:
        logger.info("mode_unified", transport="webhook")
        await _run_unified_webhook(app, instances, schedulers)
    else:
        # Legacy multi-bot mode
        bots_cfg = _collect_bots()
        if not bots_cfg:
            logger.error("no_bots_configured")
            return

        for cfg in bots_cfg:
            bot, dp = _create_bot_dp(cfg["token"], cfg["name"], cfg["router"])
            instances.append((bot, dp))

            path = f"/webhook/{cfg['name']}"

            async def make_handler(b=bot, d=dp):
                async def handler(request: web.Request) -> web.Response:
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

            if cfg["scheduler"]:
                sched = cfg["scheduler"](bot)
                sched.start()
                schedulers.append(sched)

            webhook_url = f"{settings.webhook_host}{path}"
            try:
                await bot.set_webhook(
                    url=webhook_url,
                    secret_token=settings.webhook_secret or None,
                    drop_pending_updates=True,
                )
                logger.info("webhook_set", bot=cfg["name"], url=webhook_url)
            except Exception as e:
                logger.error("webhook_set_failed", bot=cfg["name"], url=webhook_url, error=str(e))
                logger.info("webhook_retry_hint", hint="Webhook will be retried on next restart")

    # Health-check эндпоинт
    async def health_check(request: web.Request) -> web.Response:
        from src.core.health import get_status
        status = await get_status()
        code = 200 if status["ok"] else 503
        return web.json_response(status, status=code)

    app.router.add_get("/status", health_check)

    # Web App (Mini App) — API + статика
    from src.webapp import setup_webapp_routes
    setup_webapp_routes(app)

    # Amazfit Watch push endpoint
    async def watch_push_handler(request: web.Request) -> web.Response:
        """Принять push-данные от Amazfit Balance 2 (Zepp OS мини-приложение)."""
        auth = request.headers.get("Authorization", "")
        if not auth.startswith("Bearer "):
            return web.json_response({"error": "missing auth"}, status=401)
        api_key = auth[7:]

        from src.db.queries import get_watch_user_by_api_key, update_watch_last_push
        wt = await get_watch_user_by_api_key(api_key)
        if not wt:
            return web.json_response({"error": "invalid key"}, status=403)

        try:
            payload = await request.json()
        except Exception as exc:
            logger.error("watch_push_json_error", error=str(exc), content_type=request.content_type)
            body_raw = await request.text()
            logger.error("watch_push_raw_body", body=body_raw[:500])
            return web.json_response({"error": "invalid json"}, status=400)

        from src.integrations.amazfit import process_watch_push
        data = await process_watch_push(wt["user_id"], payload)
        await update_watch_last_push(wt["user_id"])

        return web.json_response({"ok": True, "saved_keys": list(data.keys())})

    app.router.add_post("/api/watch/push", watch_push_handler)

    # Graceful shutdown
    async def on_shutdown(app: web.Application) -> None:
        logger.info("graceful_shutdown_started")
        for sched in schedulers:
            sched.shutdown(wait=False)
        for bot, dp in instances:
            await bot.delete_webhook()
            await bot.session.close()
        await close_pool()
        logger.info("graceful_shutdown_complete")

    app.on_shutdown.append(on_shutdown)

    bot_count = len(instances)
    logger.info("all_bots_starting", count=bot_count, mode="webhook", port=settings.webhook_port)
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
