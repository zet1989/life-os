"""SQL-запросы к Supabase — базовые CRUD операции.

Все запросы фильтруются по user_id (ACL).
Финансы считаются ТОЛЬКО через SQL, НИКОГДА через LLM.
"""

from datetime import datetime, timezone
from typing import Any

from src.db.supabase_client import get_supabase


# === Users ===

async def get_user(user_id: int) -> dict | None:
    """Получить пользователя по Telegram ID."""
    result = (
        get_supabase()
        .table("users")
        .select("*")
        .eq("user_id", user_id)
        .maybe_single()
        .execute()
    )
    return result.data


async def update_last_active(user_id: int) -> None:
    """Обновить last_active_at при каждом сообщении."""
    get_supabase().table("users").update(
        {"last_active_at": datetime.now(timezone.utc).isoformat()}
    ).eq("user_id", user_id).execute()


async def update_user_settings(user_id: int, overrides: str) -> None:
    """Обновить system_prompt_overrides для конкретного юзера."""
    get_supabase().table("users").update(
        {"system_prompt_overrides": overrides}
    ).eq("user_id", user_id).execute()


# === Events ===

async def create_event(
    user_id: int,
    event_type: str,
    bot_source: str,
    raw_text: str | None = None,
    json_data: dict | None = None,
    media_url: str | None = None,
    project_id: int | None = None,
) -> dict:
    """Создать событие в единой шине данных."""
    row: dict[str, Any] = {
        "user_id": user_id,
        "event_type": event_type,
        "bot_source": bot_source,
        "raw_text": raw_text,
        "json_data": json_data,
        "media_url": media_url,
        "project_id": project_id,
    }
    result = get_supabase().table("events").insert(row).execute()
    return result.data[0]


# === Finances (строгая математика — SQL only) ===

async def create_finance(
    user_id: int,
    project_id: int,
    transaction_type: str,
    amount: float,
    category: str,
    description: str | None = None,
    receipt_url: str | None = None,
    source_event_id: int | None = None,
) -> dict:
    """Записать финансовую транзакцию."""
    row: dict[str, Any] = {
        "user_id": user_id,
        "project_id": project_id,
        "transaction_type": transaction_type,
        "amount": amount,
        "category": category,
        "description": description,
        "receipt_url": receipt_url,
        "source_event_id": source_event_id,
    }
    result = get_supabase().table("finances").insert(row).execute()
    return result.data[0]


async def get_finance_summary(project_id: int) -> list[dict]:
    """Сводка расходов/доходов по категориям для проекта.

    Возвращает результат SQL: SUM(amount) GROUP BY category, transaction_type.
    """
    result = (
        get_supabase()
        .rpc(
            "finance_summary",
            {"p_project_id": project_id},
        )
        .execute()
    )
    return result.data


# === Goals ===

async def get_active_goals(user_id: int) -> list[dict]:
    """Активные цели и мечты пользователя."""
    result = (
        get_supabase()
        .table("goals")
        .select("*")
        .eq("user_id", user_id)
        .eq("status", "active")
        .order("created_at", desc=False)
        .execute()
    )
    return result.data


# === Conversations (контекст диалога) ===

async def save_message(
    user_id: int,
    bot_source: str,
    role: str,
    content: str,
    tokens_used: int | None = None,
) -> None:
    """Сохранить сообщение в историю диалога."""
    get_supabase().table("conversations").insert({
        "user_id": user_id,
        "bot_source": bot_source,
        "role": role,
        "content": content,
        "tokens_used": tokens_used,
    }).execute()


async def get_recent_messages(
    user_id: int,
    bot_source: str,
    limit: int = 20,
) -> list[dict]:
    """Последние N сообщений для контекста LLM."""
    result = (
        get_supabase()
        .table("conversations")
        .select("role, content")
        .eq("user_id", user_id)
        .eq("bot_source", bot_source)
        .order("created_at", desc=True)
        .limit(limit)
        .execute()
    )
    # Возвращаем в хронологическом порядке (от старых к новым)
    return list(reversed(result.data))


# === Projects ===

async def get_user_projects(user_id: int, status: str = "active") -> list[dict]:
    """Получить проекты пользователя по статусу (только owner)."""
    result = (
        get_supabase()
        .table("projects")
        .select("*")
        .eq("owner_id", user_id)
        .eq("status", status)
        .order("created_at", desc=False)
        .execute()
    )
    return result.data


async def get_projects_by_type(
    user_id: int, project_type: str,
) -> list[dict]:
    """Получить доступные проекты по типу (owner ИЛИ collaborator).

    Использует RPC get_accessible_projects для учёта collaborators.
    """
    result = (
        get_supabase()
        .rpc("get_accessible_projects", {"p_user_id": user_id, "p_type": project_type})
        .execute()
    )
    return result.data


async def create_project(
    user_id: int,
    name: str,
    project_type: str = "solo",
    collaborators: list[int] | None = None,
    metadata: dict | None = None,
) -> dict:
    """Создать новый проект."""
    row: dict[str, Any] = {
        "name": name,
        "type": project_type,
        "owner_id": user_id,
        "collaborators": collaborators or [],
        "status": "active",
        "metadata": metadata or {},
    }
    result = get_supabase().table("projects").insert(row).execute()
    return result.data[0]


async def archive_project(project_id: int, user_id: int) -> bool:
    """Архивировать проект (ACL: только владелец)."""
    result = (
        get_supabase()
        .table("projects")
        .update({"status": "archived"})
        .eq("project_id", project_id)
        .eq("owner_id", user_id)
        .execute()
    )
    return len(result.data) > 0


async def add_collaborator(project_id: int, owner_id: int, partner_id: int) -> bool:
    """Добавить партнёра к проекту (ACL: только владелец).

    Добавляет partner_id в массив collaborators.
    """
    # Сначала проверяем что юзер — владелец
    proj = (
        get_supabase()
        .table("projects")
        .select("collaborators")
        .eq("project_id", project_id)
        .eq("owner_id", owner_id)
        .maybe_single()
        .execute()
    )
    if not proj.data:
        return False

    current: list[int] = proj.data.get("collaborators") or []
    if partner_id in current:
        return True  # уже есть

    current.append(partner_id)
    get_supabase().table("projects").update(
        {"collaborators": current}
    ).eq("project_id", project_id).execute()
    return True
