"""Экспорт данных пользователя в JSON.

Команда /export — выгрузка всех данных юзера для бэкапа и портативности.
Результат отправляется как документ в чат.
"""

import json
import tempfile
from datetime import datetime, timezone
from pathlib import Path

import structlog

from src.db.supabase_client import get_supabase

logger = structlog.get_logger()


async def export_user_data(user_id: int) -> Path:
    """Экспортировать все данные пользователя в JSON-файл.

    Возвращает путь к временному файлу.
    """
    data: dict = {
        "exported_at": datetime.now(timezone.utc).isoformat(),
        "user_id": user_id,
    }

    sb = get_supabase()

    # Users
    user = sb.table("users").select("*").eq("user_id", user_id).maybe_single().execute()
    data["user"] = user.data

    # Goals
    goals = sb.table("goals").select("*").eq("user_id", user_id).order("created_at").execute()
    data["goals"] = goals.data

    # Events
    events = (
        sb.table("events")
        .select("id, timestamp, bot_source, event_type, raw_text, json_data, media_url, project_id")
        .eq("user_id", user_id)
        .order("timestamp")
        .execute()
    )
    data["events"] = events.data

    # Finances
    finances = (
        sb.table("finances")
        .select("*")
        .eq("user_id", user_id)
        .order("created_at")
        .execute()
    )
    data["finances"] = finances.data

    # Projects (owner or collaborator)
    projects = sb.rpc("get_accessible_projects", {"p_user_id": user_id}).execute()
    data["projects"] = projects.data

    # Conversations (last 500)
    convos = (
        sb.table("conversations")
        .select("bot_source, role, content, created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(500)
        .execute()
    )
    data["conversations"] = list(reversed(convos.data))

    # API costs summary
    costs = (
        sb.table("api_costs")
        .select("bot_source, model, tokens_in, tokens_out, cost_usd, created_at")
        .eq("user_id", user_id)
        .order("created_at", desc=True)
        .limit(200)
        .execute()
    )
    data["api_costs"] = list(reversed(costs.data))

    # Записать во временный файл
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
