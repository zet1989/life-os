"""Экспорт данных пользователя в JSON.

Команда /export — выгрузка всех данных юзера для бэкапа и портативности.
Результат отправляется как документ в чат.
"""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import structlog

from src.db.queries import (
    get_accessible_projects,
    get_active_goals,
    get_user,
    get_user_api_costs,
    get_user_conversations,
    get_user_events_export,
    get_user_finances,
)

logger = structlog.get_logger()


async def export_user_data(user_id: int) -> Path:
    """Экспортировать все данные пользователя в JSON-файл."""
    data: dict = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
    }

    data["user"] = await get_user(user_id)
    data["goals"] = await get_active_goals(user_id)
    data["events"] = await get_user_events_export(user_id)
    data["finances"] = await get_user_finances(user_id)
    data["projects"] = await get_accessible_projects(user_id)
    data["conversations"] = await get_user_conversations(user_id, limit=500)
    data["api_costs"] = await get_user_api_costs(user_id, limit=200)

    tmp = tempfile.NamedTemporaryFile(
        mode="w",
        suffix=".json",
        prefix=f"life-os-export-{user_id}-",
        delete=False,
        encoding="utf-8",
    )
    json.dump(data, tmp, ensure_ascii=False, indent=2, default=str)
    tmp.close()

    logger.info("user_data_exported", user_id=user_id, path=tmp.name)
    return Path(tmp.name)
