"""Todoist API v1 integration — двусторонняя синхронизация с Inbox.

Todoist REST API v1: https://developer.todoist.com/api/v1/
Авторизация: Bearer token (personal API token из Settings → Integrations → Developer).
"""

import aiohttp
import structlog

from src.config import settings

logger = structlog.get_logger()

BASE_URL = "https://api.todoist.com/api/v1"
LABEL_SYNCED = "life-os"  # метка для задач, синхронизированных из Life OS


def _headers() -> dict[str, str]:
    return {
        "Authorization": f"Bearer {settings.todoist_api_token}",
        "Content-Type": "application/json",
    }


def is_configured() -> bool:
    return bool(settings.todoist_api_token)


async def get_user_info() -> dict | None:
    """Получить информацию о пользователе (в т.ч. inbox_project_id)."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(f"{BASE_URL}/user", headers=_headers()) as resp:
                if resp.status == 200:
                    return await resp.json()
                logger.warning("todoist_user_info_failed", status=resp.status)
                return None
    except Exception:
        logger.exception("todoist_user_info_error")
        return None


async def get_inbox_project_id() -> str | None:
    """Получить ID Inbox-проекта через Sync API (содержит inbox_project_id)."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://api.todoist.com/api/v1/sync",
                headers=_headers(),
                data={"sync_token": "*", "resource_types": '["user"]'},
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("user", {}).get("inbox_project_id")
                return None
    except Exception:
        logger.exception("todoist_inbox_id_error")
        return None


async def get_tasks(project_id: str | None = None) -> list[dict]:
    """Получить активные задачи (все или по проекту)."""
    try:
        params: dict[str, str] = {}
        if project_id:
            params["project_id"] = project_id
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{BASE_URL}/tasks", headers=_headers(), params=params,
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("results", [])
                logger.warning("todoist_get_tasks_failed", status=resp.status)
                return []
    except Exception:
        logger.exception("todoist_get_tasks_error")
        return []


async def get_inbox_tasks() -> list[dict]:
    """Получить задачи из Inbox-проекта Todoist."""
    inbox_id = await get_inbox_project_id()
    if not inbox_id:
        return []
    return await get_tasks(project_id=inbox_id)


async def create_task(content: str, project_id: str | None = None,
                      labels: list[str] | None = None,
                      due_string: str | None = None) -> dict | None:
    """Создать задачу в Todoist."""
    try:
        body: dict = {"content": content}
        if project_id:
            body["project_id"] = project_id
        if labels:
            body["labels"] = labels
        if due_string:
            body["due_string"] = due_string
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{BASE_URL}/tasks", headers=_headers(), json=body,
            ) as resp:
                if resp.status == 200:
                    return await resp.json()
                text = await resp.text()
                logger.warning("todoist_create_task_failed", status=resp.status, body=text)
                return None
    except Exception:
        logger.exception("todoist_create_task_error")
        return None


async def close_task(task_id: str) -> bool:
    """Завершить задачу в Todoist."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                f"{BASE_URL}/tasks/{task_id}/close", headers=_headers(),
            ) as resp:
                return resp.status == 200
    except Exception:
        logger.exception("todoist_close_task_error")
        return False


async def get_projects() -> list[dict]:
    """Получить список проектов."""
    try:
        async with aiohttp.ClientSession() as session:
            async with session.get(
                f"{BASE_URL}/projects", headers=_headers(),
            ) as resp:
                if resp.status == 200:
                    data = await resp.json()
                    return data.get("results", [])
                return []
    except Exception:
        logger.exception("todoist_get_projects_error")
        return []
