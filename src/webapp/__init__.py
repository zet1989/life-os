"""Web App (Telegram Mini App) — API endpoints.

Все эндпоинты защищены валидацией Telegram initData.
"""

import hashlib
import hmac
import json
import time
from urllib.parse import parse_qs, unquote

from aiohttp import web

import structlog

logger = structlog.get_logger()


def validate_init_data(init_data: str, bot_token: str, max_age: int = 86400) -> dict | None:
    """Валидация Telegram Web App initData.

    Возвращает parsed данные (включая user) или None при невалидном запросе.
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    parsed = parse_qs(init_data, keep_blank_values=True)
    received_hash = parsed.get("hash", [None])[0]
    if not received_hash:
        return None

    # Проверяем auth_date (не старше max_age)
    auth_date_str = parsed.get("auth_date", [None])[0]
    if not auth_date_str:
        return None
    try:
        auth_date = int(auth_date_str)
    except ValueError:
        return None
    if time.time() - auth_date > max_age:
        return None

    # Собираем data-check-string
    items = []
    for key in sorted(parsed.keys()):
        if key == "hash":
            continue
        items.append(f"{key}={parsed[key][0]}")
    data_check_string = "\n".join(items)

    # HMAC-SHA256
    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    # Парсим user
    result = {k: v[0] for k, v in parsed.items()}
    if "user" in result:
        try:
            result["user"] = json.loads(unquote(result["user"]))
        except (json.JSONDecodeError, TypeError):
            pass

    return result


def _get_user_id(request: web.Request) -> int | None:
    """Извлечь и валидировать user_id из Telegram initData (заголовок X-Telegram-Init-Data)."""
    from src.config import settings

    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if not init_data:
        return None

    # Определяем токен бота
    token = settings.bot_token_unified or settings.bot_token_master
    if not token:
        return None

    data = validate_init_data(init_data, token)
    if not data:
        return None

    user = data.get("user")
    if isinstance(user, dict):
        return user.get("id")
    return None


async def api_tasks_today(request: web.Request) -> web.Response:
    """GET /api/webapp/tasks — задачи на сегодня."""
    user_id = _get_user_id(request)
    if not user_id:
        return web.json_response({"error": "unauthorized"}, status=401)

    from src.db.queries import get_today_tasks, get_today_focus

    tasks = await get_today_tasks(user_id)
    focus = await get_today_focus(user_id)

    return web.json_response({
        "tasks": [dict(t) for t in tasks],
        "focus": dict(focus) if focus else None,
    })


async def api_goals(request: web.Request) -> web.Response:
    """GET /api/webapp/goals — активные цели."""
    user_id = _get_user_id(request)
    if not user_id:
        return web.json_response({"error": "unauthorized"}, status=401)

    from src.db.queries import get_active_goals

    goals = await get_active_goals(user_id)
    return web.json_response({"goals": [dict(g) for g in goals]})


async def api_health_today(request: web.Request) -> web.Response:
    """GET /api/webapp/health — здоровье за сегодня (еда, вода, тренировки, часы)."""
    user_id = _get_user_id(request)
    if not user_id:
        return web.json_response({"error": "unauthorized"}, status=401)

    from src.db.queries import get_today_meals, get_today_water, get_today_workouts, get_today_watch_metrics

    meals = await get_today_meals(user_id)
    water = await get_today_water(user_id)
    workouts = await get_today_workouts(user_id)
    watch = await get_today_watch_metrics(user_id)

    # Считаем итого калории
    total_kcal = 0
    for m in meals:
        jd = m.get("json_data") or {}
        if isinstance(jd, str):
            try:
                jd = json.loads(jd)
            except json.JSONDecodeError:
                jd = {}
        total_kcal += jd.get("calories", 0)

    # Считаем итого воды
    total_water = 0
    for w in water:
        jd = w.get("json_data") or {}
        if isinstance(jd, str):
            try:
                jd = json.loads(jd)
            except json.JSONDecodeError:
                jd = {}
        total_water += jd.get("amount_ml", 0)

    return web.json_response({
        "meals": [dict(m) for m in meals],
        "total_kcal": total_kcal,
        "water_ml": total_water,
        "workouts": [dict(w) for w in workouts],
        "watch": [dict(w) for w in watch],
    })


async def api_finances(request: web.Request) -> web.Response:
    """GET /api/webapp/finances — последние транзакции + сводка."""
    user_id = _get_user_id(request)
    if not user_id:
        return web.json_response({"error": "unauthorized"}, status=401)

    from src.db.queries import get_recent_finances, get_debts_summary

    transactions = await get_recent_finances(user_id, limit=20)
    debts = await get_debts_summary(user_id)

    return web.json_response({
        "transactions": [dict(t) for t in transactions],
        "debts_summary": dict(debts) if debts else {},
    })


async def api_task_complete(request: web.Request) -> web.Response:
    """POST /api/webapp/tasks/{task_id}/complete — отметить задачу выполненной."""
    user_id = _get_user_id(request)
    if not user_id:
        return web.json_response({"error": "unauthorized"}, status=401)

    task_id_str = request.match_info.get("task_id", "")
    try:
        task_id = int(task_id_str)
    except ValueError:
        return web.json_response({"error": "invalid task_id"}, status=400)

    from src.db.queries import complete_task

    ok = await complete_task(task_id, user_id)
    return web.json_response({"ok": ok})


async def api_task_create(request: web.Request) -> web.Response:
    """POST /api/webapp/tasks — создать задачу."""
    user_id = _get_user_id(request)
    if not user_id:
        return web.json_response({"error": "unauthorized"}, status=401)

    try:
        body = await request.json()
    except Exception:
        return web.json_response({"error": "invalid json"}, status=400)

    text = body.get("text", "").strip()
    if not text:
        return web.json_response({"error": "text required"}, status=400)

    from src.db.queries import create_task

    task = await create_task(
        user_id=user_id,
        task_text=text,
        due_date=body.get("due_date"),
        due_time=body.get("due_time"),
        priority=body.get("priority", "normal"),
    )

    return web.json_response({"ok": True, "task": dict(task)})


def setup_webapp_routes(app: web.Application) -> None:
    """Зарегистрировать все Web App маршруты."""
    import os

    # API
    app.router.add_get("/api/webapp/tasks", api_tasks_today)
    app.router.add_post("/api/webapp/tasks", api_task_create)
    app.router.add_post("/api/webapp/tasks/{task_id}/complete", api_task_complete)
    app.router.add_get("/api/webapp/goals", api_goals)
    app.router.add_get("/api/webapp/health", api_health_today)
    app.router.add_get("/api/webapp/finances", api_finances)

    # Static files (HTML/CSS/JS)
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.isdir(static_dir):
        app.router.add_static("/webapp/", static_dir, name="webapp_static")

        # SPA fallback — index.html
        async def webapp_index(request: web.Request) -> web.FileResponse:
            return web.FileResponse(os.path.join(static_dir, "index.html"))

        app.router.add_get("/webapp", webapp_index)

    logger.info("webapp.routes_registered")
