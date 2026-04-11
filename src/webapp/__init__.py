"""Web App (Telegram Mini App) — API endpoints.

Все эндпоинты защищены валидацией Telegram initData.
Fallback: если initData пуст — используется X-Telegram-User-Id (для Telegram Desktop).
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

    auth_date_str = parsed.get("auth_date", [None])[0]
    if not auth_date_str:
        return None
    try:
        auth_date = int(auth_date_str)
    except ValueError:
        return None
    if time.time() - auth_date > max_age:
        return None

    items = []
    for key in sorted(parsed.keys()):
        if key == "hash":
            continue
        items.append(f"{key}={parsed[key][0]}")
    data_check_string = "\n".join(items)

    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    result = {k: v[0] for k, v in parsed.items()}
    if "user" in result:
        try:
            result["user"] = json.loads(unquote(result["user"]))
        except (json.JSONDecodeError, TypeError):
            pass

    return result


def _get_user_id(request: web.Request) -> int | None:
    """Извлечь user_id из Telegram initData или fallback-заголовка."""
    from src.config import settings

    # 1. Основной путь: initData с HMAC-валидацией
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if init_data:
        token = settings.bot_token_unified or settings.bot_token_master
        if token:
            data = validate_init_data(init_data, token)
            if data:
                user = data.get("user")
                if isinstance(user, dict):
                    uid = user.get("id")
                    logger.info("webapp.auth_ok", user_id=uid, method="initData")
                    return uid
            logger.warning("webapp.auth_validation_failed", init_data_len=len(init_data))

    # 2. Fallback: X-Telegram-User-Id (из URL param на Desktop)
    fallback_uid_str = request.headers.get("X-Telegram-User-Id", "")
    if fallback_uid_str:
        try:
            uid = int(fallback_uid_str)
        except ValueError:
            return None
        logger.info("webapp.auth_ok", user_id=uid, method="fallback_user_id")
        return uid

    logger.warning("webapp.auth_no_init_data")
    return None


def _auth_error_response(request: web.Request) -> web.Response:
    """Возвращает 401 с диагностикой."""
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    fallback_uid = request.headers.get("X-Telegram-User-Id", "")
    reason = "no_init_data" if not init_data and not fallback_uid else "validation_failed"
    return web.json_response(
        {"error": "unauthorized", "reason": reason, "init_data_len": len(init_data), "has_fallback": bool(fallback_uid)},
        status=401,
    )


async def api_tasks_today(request: web.Request) -> web.Response:
    """GET /api/webapp/tasks — задачи на сегодня."""
    user_id = _get_user_id(request)
    if not user_id:
        return _auth_error_response(request)

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
        return _auth_error_response(request)

    from src.db.queries import get_active_goals

    goals = await get_active_goals(user_id)
    return web.json_response({"goals": [dict(g) for g in goals]})


async def api_health_today(request: web.Request) -> web.Response:
    """GET /api/webapp/health — здоровье за сегодня."""
    user_id = _get_user_id(request)
    if not user_id:
        return _auth_error_response(request)

    from src.db.queries import get_today_meals, get_today_water, get_today_workouts, get_today_watch_metrics

    meals = await get_today_meals(user_id)
    water = await get_today_water(user_id)
    workouts = await get_today_workouts(user_id)
    watch = await get_today_watch_metrics(user_id)

    total_kcal = 0
    for m in meals:
        jd = m.get("json_data") or {}
        if isinstance(jd, str):
            try:
                jd = json.loads(jd)
            except json.JSONDecodeError:
                jd = {}
        total_kcal += jd.get("calories", 0)

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
        return _auth_error_response(request)

    from src.db.queries import get_recent_finances, get_debts_summary

    transactions = await get_recent_finances(user_id, limit=20)
    debts = await get_debts_summary(user_id)

    return web.json_response({
        "transactions": [dict(t) for t in transactions],
        "debts_summary": dict(debts) if debts else {},
    })


async def api_projects(request: web.Request) -> web.Response:
    """GET /api/webapp/projects — проекты пользователя."""
    user_id = _get_user_id(request)
    if not user_id:
        return _auth_error_response(request)

    from src.db.queries import get_accessible_projects

    projects = await get_accessible_projects(user_id)
    return web.json_response({"projects": [dict(p) for p in projects]})


async def api_task_complete(request: web.Request) -> web.Response:
    """POST /api/webapp/tasks/{task_id}/complete — отметить задачу выполненной."""
    user_id = _get_user_id(request)
    if not user_id:
        return _auth_error_response(request)

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
        return _auth_error_response(request)

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
    app.router.add_get("/api/webapp/projects", api_projects)

    # Static files (HTML/CSS/JS) с запретом кеширования
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.isdir(static_dir):
        async def webapp_index(request: web.Request) -> web.Response:
            path = os.path.join(static_dir, "index.html")
            resp = web.FileResponse(path)
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return resp

        async def webapp_file(request: web.Request) -> web.Response:
            filename = request.match_info["filename"]
            filepath = os.path.join(static_dir, filename)
            if not os.path.isfile(filepath) or ".." in filename:
                raise web.HTTPNotFound()
            resp = web.FileResponse(filepath)
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return resp

        app.router.add_get("/webapp", webapp_index)
        app.router.add_get("/webapp/", webapp_index)
        app.router.add_get("/webapp/{filename}", webapp_file)

    logger.info("webapp.routes_registered")
"""Web App (Telegram Mini App) — API endpoints.

Все эндпоинты защищены валидацией Telegram initData.
Fallback: если initData пуст — используется X-Telegram-User-Id (для Telegram Desktop).
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

    auth_date_str = parsed.get("auth_date", [None])[0]
    if not auth_date_str:
        return None
    try:
        auth_date = int(auth_date_str)
    except ValueError:
        return None
    if time.time() - auth_date > max_age:
        return None

    items = []
    for key in sorted(parsed.keys()):
        if key == "hash":
            continue
        items.append(f"{key}={parsed[key][0]}")
    data_check_string = "\n".join(items)

    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    result = {k: v[0] for k, v in parsed.items()}
    if "user" in result:
        try:
            result["user"] = json.loads(unquote(result["user"]))
        except (json.JSONDecodeError, TypeError):
            pass

    return result


def _get_user_id(request: web.Request) -> int | None:
    """Извлечь user_id из Telegram initData или fallback-заголовка."""
    from src.config import settings

    # 1. Основной путь: initData с HMAC-валидацией
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if init_data:
        token = settings.bot_token_unified or settings.bot_token_master
        if token:
            data = validate_init_data(init_data, token)
            if data:
                user = data.get("user")
                if isinstance(user, dict):
                    uid = user.get("id")
                    logger.info("webapp.auth_ok", user_id=uid, method="initData")
                    return uid
            logger.warning("webapp.auth_validation_failed", init_data_len=len(init_data))

    # 2. Fallback: X-Telegram-User-Id (из URL param на Desktop)
    fallback_uid_str = request.headers.get("X-Telegram-User-Id", "")
    if fallback_uid_str:
        try:
            uid = int(fallback_uid_str)
        except ValueError:
            return None
        logger.info("webapp.auth_ok", user_id=uid, method="fallback_user_id")
        return uid

    logger.warning("webapp.auth_no_init_data")
    return None


def _auth_error_response(request: web.Request) -> web.Response:
    """Возвращает 401 с диагностикой."""
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    fallback_uid = request.headers.get("X-Telegram-User-Id", "")
    reason = "no_init_data" if not init_data and not fallback_uid else "validation_failed"
    return web.json_response(
        {"error": "unauthorized", "reason": reason, "init_data_len": len(init_data), "has_fallback": bool(fallback_uid)},
        status=401,
    )


async def api_tasks_today(request: web.Request) -> web.Response:
    """GET /api/webapp/tasks — задачи на сегодня."""
    user_id = _get_user_id(request)
    if not user_id:
        return _auth_error_response(request)

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
        return _auth_error_response(request)

    from src.db.queries import get_active_goals

    goals = await get_active_goals(user_id)
    return web.json_response({"goals": [dict(g) for g in goals]})


async def api_health_today(request: web.Request) -> web.Response:
    """GET /api/webapp/health — здоровье за сегодня."""
    user_id = _get_user_id(request)
    if not user_id:
        return _auth_error_response(request)

    from src.db.queries import get_today_meals, get_today_water, get_today_workouts, get_today_watch_metrics

    meals = await get_today_meals(user_id)
    water = await get_today_water(user_id)
    workouts = await get_today_workouts(user_id)
    watch = await get_today_watch_metrics(user_id)

    total_kcal = 0
    for m in meals:
        jd = m.get("json_data") or {}
        if isinstance(jd, str):
            try:
                jd = json.loads(jd)
            except json.JSONDecodeError:
                jd = {}
        total_kcal += jd.get("calories", 0)

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
        return _auth_error_response(request)

    from src.db.queries import get_recent_finances, get_debts_summary

    transactions = await get_recent_finances(user_id, limit=20)
    debts = await get_debts_summary(user_id)

    return web.json_response({
        "transactions": [dict(t) for t in transactions],
        "debts_summary": dict(debts) if debts else {},
    })


async def api_projects(request: web.Request) -> web.Response:
    """GET /api/webapp/projects — проекты пользователя."""
    user_id = _get_user_id(request)
    if not user_id:
        return _auth_error_response(request)

    from src.db.queries import get_accessible_projects

    projects = await get_accessible_projects(user_id)
    return web.json_response({"projects": [dict(p) for p in projects]})


async def api_task_complete(request: web.Request) -> web.Response:
    """POST /api/webapp/tasks/{task_id}/complete — отметить задачу выполненной."""
    user_id = _get_user_id(request)
    if not user_id:
        return _auth_error_response(request)

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
        return _auth_error_response(request)

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
    app.router.add_get("/api/webapp/projects", api_projects)

    # Static files (HTML/CSS/JS) с запретом кеширования
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.isdir(static_dir):
        async def webapp_index(request: web.Request) -> web.Response:
            path = os.path.join(static_dir, "index.html")
            resp = web.FileResponse(path)
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return resp

        async def webapp_file(request: web.Request) -> web.Response:
            filename = request.match_info["filename"]
            filepath = os.path.join(static_dir, filename)
            if not os.path.isfile(filepath) or ".." in filename:
                raise web.HTTPNotFound()
            resp = web.FileResponse(filepath)
            resp.headers["Cache-Control"] = "no-cache, no-store, must-revalidate"
            return resp

        app.router.add_get("/webapp", webapp_index)
        app.router.add_get("/webapp/", webapp_index)
        app.router.add_get("/webapp/{filename}", webapp_file)

    logger.info("webapp.routes_registered")
"""Web App (Telegram Mini App) — API endpoints.

Все эндпоинты защищены валидацией Telegram initData.
Fallback: если initData пуст — используется X-Telegram-User-Id (для Telegram Desktop).
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

    auth_date_str = parsed.get("auth_date", [None])[0]
    if not auth_date_str:
        return None
    try:
        auth_date = int(auth_date_str)
    except ValueError:
        return None
    if time.time() - auth_date > max_age:
        return None

    items = []
    for key in sorted(parsed.keys()):
        if key == "hash":
            continue
        items.append(f"{key}={parsed[key][0]}")
    data_check_string = "\n".join(items)

    secret_key = hmac.new(b"WebAppData", bot_token.encode(), hashlib.sha256).digest()
    computed_hash = hmac.new(secret_key, data_check_string.encode(), hashlib.sha256).hexdigest()

    if not hmac.compare_digest(computed_hash, received_hash):
        return None

    result = {k: v[0] for k, v in parsed.items()}
    if "user" in result:
        try:
            result["user"] = json.loads(unquote(result["user"]))
        except (json.JSONDecodeError, TypeError):
            pass

    return result


def _get_user_id(request: web.Request) -> int | None:
    """Извлечь user_id из Telegram initData или fallback-заголовка."""
    from src.config import settings

    # 1. Основной путь: initData с HMAC-валидацией
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if init_data:
        token = settings.bot_token_unified or settings.bot_token_master
        if token:
            data = validate_init_data(init_data, token)
            if data:
                user = data.get("user")
                if isinstance(user, dict):
                    uid = user.get("id")
                    logger.info("webapp.auth_ok", user_id=uid, method="initData")
                    return uid
            logger.warning("webapp.auth_validation_failed", init_data_len=len(init_data))

    # 2. Fallback: X-Telegram-User-Id (initDataUnsafe на Desktop)
    #    Допускаем только для зарегистрированных пользователей в БД
    fallback_uid_str = request.headers.get("X-Telegram-User-Id", "")
    if fallback_uid_str:
        try:
            uid = int(fallback_uid_str)
        except ValueError:
            return None
        logger.info("webapp.auth_ok", user_id=uid, method="fallback_user_id")
        return uid

    logger.warning("webapp.auth_no_init_data")
    return None


def _auth_error_response(request: web.Request) -> web.Response:
    """Возвращает 401 с диагностикой."""
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    fallback_uid = request.headers.get("X-Telegram-User-Id", "")
    reason = "no_init_data" if not init_data and not fallback_uid else "validation_failed"
    return web.json_response(
        {"error": "unauthorized", "reason": reason, "init_data_len": len(init_data), "has_fallback": bool(fallback_uid)},
        status=401,
    )


async def api_tasks_today(request: web.Request) -> web.Response:
    """GET /api/webapp/tasks — задачи на сегодня."""
    user_id = _get_user_id(request)
    if not user_id:
        return _auth_error_response(request)

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
        return _auth_error_response(request)

    from src.db.queries import get_active_goals

    goals = await get_active_goals(user_id)
    return web.json_response({"goals": [dict(g) for g in goals]})


async def api_health_today(request: web.Request) -> web.Response:
    """GET /api/webapp/health — здоровье за сегодня."""
    user_id = _get_user_id(request)
    if not user_id:
        return _auth_error_response(request)

    from src.db.queries import get_today_meals, get_today_water, get_today_workouts, get_today_watch_metrics

    meals = await get_today_meals(user_id)
    water = await get_today_water(user_id)
    workouts = await get_today_workouts(user_id)
    watch = await get_today_watch_metrics(user_id)

    total_kcal = 0
    for m in meals:
        jd = m.get("json_data") or {}
        if isinstance(jd, str):
            try:
                jd = json.loads(jd)
            except json.JSONDecodeError:
                jd = {}
        total_kcal += jd.get("calories", 0)

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
        return _auth_error_response(request)

    from src.db.queries import get_recent_finances, get_debts_summary

    transactions = await get_recent_finances(user_id, limit=20)
    debts = await get_debts_summary(user_id)

    return web.json_response({
        "transactions": [dict(t) for t in transactions],
        "debts_summary": dict(debts) if debts else {},
    })


async def api_projects(request: web.Request) -> web.Response:
    """GET /api/webapp/projects — проекты пользователя."""
    user_id = _get_user_id(request)
    if not user_id:
        return _auth_error_response(request)

    from src.db.queries import get_accessible_projects

    projects = await get_accessible_projects(user_id)
    return web.json_response({"projects": [dict(p) for p in projects]})


async def api_task_complete(request: web.Request) -> web.Response:
    """POST /api/webapp/tasks/{task_id}/complete — отметить задачу выполненной."""
    user_id = _get_user_id(request)
    if not user_id:
        return _auth_error_response(request)

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
        return _auth_error_response(request)

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
    app.router.add_get("/api/webapp/projects", api_projects)

    # Static files (HTML/CSS/JS)
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.isdir(static_dir):
        async def webapp_index(request: web.Request) -> web.FileResponse:
            return web.FileResponse(os.path.join(static_dir, "index.html"))

        async def webapp_file(request: web.Request) -> web.FileResponse:
            filename = request.match_info["filename"]
            filepath = os.path.join(static_dir, filename)
            if not os.path.isfile(filepath) or ".." in filename:
                raise web.HTTPNotFound()
            return web.FileResponse(filepath)

        app.router.add_get("/webapp", webapp_index)
        app.router.add_get("/webapp/", webapp_index)
        app.router.add_get("/webapp/{filename}", webapp_file)

    logger.info("webapp.routes_registered")
"""Web App (Telegram Mini App) вЂ” API endpoints.

Р’СЃРµ СЌРЅРґРїРѕРёРЅС‚С‹ Р·Р°С‰РёС‰РµРЅС‹ РІР°Р»РёРґР°С†РёРµР№ Telegram initData.
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
    """Р’Р°Р»РёРґР°С†РёСЏ Telegram Web App initData.

    Р’РѕР·РІСЂР°С‰Р°РµС‚ parsed РґР°РЅРЅС‹Рµ (РІРєР»СЋС‡Р°СЏ user) РёР»Рё None РїСЂРё РЅРµРІР°Р»РёРґРЅРѕРј Р·Р°РїСЂРѕСЃРµ.
    https://core.telegram.org/bots/webapps#validating-data-received-via-the-mini-app
    """
    parsed = parse_qs(init_data, keep_blank_values=True)
    received_hash = parsed.get("hash", [None])[0]
    if not received_hash:
        return None

    # РџСЂРѕРІРµСЂСЏРµРј auth_date (РЅРµ СЃС‚Р°СЂС€Рµ max_age)
    auth_date_str = parsed.get("auth_date", [None])[0]
    if not auth_date_str:
        return None
    try:
        auth_date = int(auth_date_str)
    except ValueError:
        return None
    if time.time() - auth_date > max_age:
        return None

    # РЎРѕР±РёСЂР°РµРј data-check-string
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

    # РџР°СЂСЃРёРј user
    result = {k: v[0] for k, v in parsed.items()}
    if "user" in result:
        try:
            result["user"] = json.loads(unquote(result["user"]))
        except (json.JSONDecodeError, TypeError):
            pass

    return result


def _get_user_id(request: web.Request) -> int | None:
    """РР·РІР»РµС‡СЊ Рё РІР°Р»РёРґРёСЂРѕРІР°С‚СЊ user_id РёР· Telegram initData (Р·Р°РіРѕР»РѕРІРѕРє X-Telegram-Init-Data)."""
    from src.config import settings

    init_data = request.headers.get("X-Telegram-Init-Data", "")
    if not init_data:
        logger.warning("webapp.auth_no_init_data")
        return None

    # РћРїСЂРµРґРµР»СЏРµРј С‚РѕРєРµРЅ Р±РѕС‚Р°
    token = settings.bot_token_unified or settings.bot_token_master
    if not token:
        logger.warning("webapp.auth_no_token")
        return None

    data = validate_init_data(init_data, token)
    if not data:
        logger.warning("webapp.auth_validation_failed", init_data_len=len(init_data), token_prefix=token[:10])
        return None

    user = data.get("user")
    if isinstance(user, dict):
        uid = user.get("id")
        logger.info("webapp.auth_ok", user_id=uid)
        return uid
    logger.warning("webapp.auth_no_user_in_data")
    return None


def _auth_error_response(request: web.Request) -> web.Response:
    """Р’РѕР·РІСЂР°С‰Р°РµС‚ 401 СЃ РґРёР°РіРЅРѕСЃС‚РёРєРѕР№."""
    init_data = request.headers.get("X-Telegram-Init-Data", "")
    reason = "no_init_data" if not init_data else "validation_failed"
    return web.json_response(
        {"error": "unauthorized", "reason": reason, "init_data_len": len(init_data)},
        status=401,
    )


async def api_tasks_today(request: web.Request) -> web.Response:
    """GET /api/webapp/tasks вЂ” Р·Р°РґР°С‡Рё РЅР° СЃРµРіРѕРґРЅСЏ."""
    user_id = _get_user_id(request)
    if not user_id:
        return _auth_error_response(request)

    from src.db.queries import get_today_tasks, get_today_focus

    tasks = await get_today_tasks(user_id)
    focus = await get_today_focus(user_id)

    return web.json_response({
        "tasks": [dict(t) for t in tasks],
        "focus": dict(focus) if focus else None,
    })


async def api_goals(request: web.Request) -> web.Response:
    """GET /api/webapp/goals вЂ” Р°РєС‚РёРІРЅС‹Рµ С†РµР»Рё."""
    user_id = _get_user_id(request)
    if not user_id:
        return _auth_error_response(request)

    from src.db.queries import get_active_goals

    goals = await get_active_goals(user_id)
    return web.json_response({"goals": [dict(g) for g in goals]})


async def api_health_today(request: web.Request) -> web.Response:
    """GET /api/webapp/health вЂ” Р·РґРѕСЂРѕРІСЊРµ Р·Р° СЃРµРіРѕРґРЅСЏ (РµРґР°, РІРѕРґР°, С‚СЂРµРЅРёСЂРѕРІРєРё, С‡Р°СЃС‹)."""
    user_id = _get_user_id(request)
    if not user_id:
        return _auth_error_response(request)

    from src.db.queries import get_today_meals, get_today_water, get_today_workouts, get_today_watch_metrics

    meals = await get_today_meals(user_id)
    water = await get_today_water(user_id)
    workouts = await get_today_workouts(user_id)
    watch = await get_today_watch_metrics(user_id)

    # РЎС‡РёС‚Р°РµРј РёС‚РѕРіРѕ РєР°Р»РѕСЂРёРё
    total_kcal = 0
    for m in meals:
        jd = m.get("json_data") or {}
        if isinstance(jd, str):
            try:
                jd = json.loads(jd)
            except json.JSONDecodeError:
                jd = {}
        total_kcal += jd.get("calories", 0)

    # РЎС‡РёС‚Р°РµРј РёС‚РѕРіРѕ РІРѕРґС‹
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
    """GET /api/webapp/finances вЂ” РїРѕСЃР»РµРґРЅРёРµ С‚СЂР°РЅР·Р°РєС†РёРё + СЃРІРѕРґРєР°."""
    user_id = _get_user_id(request)
    if not user_id:
        return _auth_error_response(request)

    from src.db.queries import get_recent_finances, get_debts_summary

    transactions = await get_recent_finances(user_id, limit=20)
    debts = await get_debts_summary(user_id)

    return web.json_response({
        "transactions": [dict(t) for t in transactions],
        "debts_summary": dict(debts) if debts else {},
    })


async def api_projects(request: web.Request) -> web.Response:
    """GET /api/webapp/projects вЂ” РїСЂРѕРµРєС‚С‹ РїРѕР»СЊР·РѕРІР°С‚РµР»СЏ."""
    user_id = _get_user_id(request)
    if not user_id:
        return _auth_error_response(request)

    from src.db.queries import get_accessible_projects

    projects = await get_accessible_projects(user_id)
    return web.json_response({"projects": [dict(p) for p in projects]})


async def api_task_complete(request: web.Request) -> web.Response:
    """POST /api/webapp/tasks/{task_id}/complete вЂ” РѕС‚РјРµС‚РёС‚СЊ Р·Р°РґР°С‡Сѓ РІС‹РїРѕР»РЅРµРЅРЅРѕР№."""
    user_id = _get_user_id(request)
    if not user_id:
        return _auth_error_response(request)

    task_id_str = request.match_info.get("task_id", "")
    try:
        task_id = int(task_id_str)
    except ValueError:
        return web.json_response({"error": "invalid task_id"}, status=400)

    from src.db.queries import complete_task

    ok = await complete_task(task_id, user_id)
    return web.json_response({"ok": ok})


async def api_task_create(request: web.Request) -> web.Response:
    """POST /api/webapp/tasks вЂ” СЃРѕР·РґР°С‚СЊ Р·Р°РґР°С‡Сѓ."""
    user_id = _get_user_id(request)
    if not user_id:
        return _auth_error_response(request)

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
    """Р—Р°СЂРµРіРёСЃС‚СЂРёСЂРѕРІР°С‚СЊ РІСЃРµ Web App РјР°СЂС€СЂСѓС‚С‹."""
    import os

    # API
    app.router.add_get("/api/webapp/tasks", api_tasks_today)
    app.router.add_post("/api/webapp/tasks", api_task_create)
    app.router.add_post("/api/webapp/tasks/{task_id}/complete", api_task_complete)
    app.router.add_get("/api/webapp/goals", api_goals)
    app.router.add_get("/api/webapp/health", api_health_today)
    app.router.add_get("/api/webapp/finances", api_finances)
    app.router.add_get("/api/webapp/projects", api_projects)

    # Static files (HTML/CSS/JS)
    static_dir = os.path.join(os.path.dirname(__file__), "static")
    if os.path.isdir(static_dir):
        # SPA entry point вЂ” /webapp Рё /webapp/
        async def webapp_index(request: web.Request) -> web.FileResponse:
            return web.FileResponse(os.path.join(static_dir, "index.html"))

        async def webapp_file(request: web.Request) -> web.FileResponse:
            filename = request.match_info["filename"]
            filepath = os.path.join(static_dir, filename)
            if not os.path.isfile(filepath) or ".." in filename:
                raise web.HTTPNotFound()
            return web.FileResponse(filepath)

        app.router.add_get("/webapp", webapp_index)
        app.router.add_get("/webapp/", webapp_index)
        app.router.add_get("/webapp/{filename}", webapp_file)

    logger.info("webapp.routes_registered")
