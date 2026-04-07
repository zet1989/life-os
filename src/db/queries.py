"""SQL-запросы к PostgreSQL — базовые CRUD операции.

Все запросы фильтруются по user_id (ACL).
Финансы считаются ТОЛЬКО через SQL, НИКОГДА через LLM.
"""

from datetime import date as date_type, datetime, time as time_type, timezone
from typing import Any

import numpy as np

from src.db.postgres import get_pool


# === Users ===

async def get_user(user_id: int) -> dict | None:
    """Получить пользователя по Telegram ID."""
    row = await get_pool().fetchrow("SELECT * FROM users WHERE user_id = $1", user_id)
    return dict(row) if row else None


async def update_last_active(user_id: int) -> None:
    """Обновить last_active_at при каждом сообщении."""
    await get_pool().execute(
        "UPDATE users SET last_active_at = $1 WHERE user_id = $2",
        datetime.now(timezone.utc), user_id,
    )


async def update_user_settings(user_id: int, overrides: str) -> None:
    """Обновить system_prompt_overrides для конкретного юзера."""
    await get_pool().execute(
        "UPDATE users SET system_prompt_overrides = $1 WHERE user_id = $2",
        overrides, user_id,
    )


async def get_admin_users() -> list[dict]:
    """Получить admin-пользователей."""
    rows = await get_pool().fetch(
        "SELECT user_id, display_name FROM users WHERE is_active = TRUE AND role = 'admin'"
    )
    return [dict(r) for r in rows]


async def get_active_user_ids() -> list[int]:
    """Получить ID всех активных пользователей."""
    rows = await get_pool().fetch("SELECT user_id FROM users WHERE is_active = TRUE")
    return [r["user_id"] for r in rows]


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
    row = await get_pool().fetchrow(
        """INSERT INTO events (user_id, event_type, bot_source, raw_text, json_data, media_url, project_id)
           VALUES ($1, $2, $3, $4, $5, $6, $7) RETURNING *""",
        user_id, event_type, bot_source, raw_text, json_data, media_url, project_id,
    )
    return dict(row)


async def update_event_embedding(event_id: int, embedding: list[float]) -> None:
    """Сохранить вектор эмбеддинга в events."""
    await get_pool().execute(
        "UPDATE events SET embedding = $1 WHERE id = $2",
        np.array(embedding, dtype=np.float32), event_id,
    )


async def update_event_raw_text(event_id: int, raw_text: str) -> None:
    """Обновить raw_text у существующего event."""
    await get_pool().execute(
        "UPDATE events SET raw_text = $1 WHERE id = $2",
        raw_text, event_id,
    )


async def get_obsidian_note_event(user_id: int, source_file: str) -> dict | None:
    """Найти event типа obsidian_note по source_file."""
    row = await get_pool().fetchrow(
        """SELECT * FROM events
           WHERE user_id = $1
             AND event_type = 'obsidian_note'
             AND json_data->>'source_file' = $2
           LIMIT 1""",
        user_id, source_file,
    )
    return dict(row) if row else None


async def get_recent_events(
    user_id: int,
    event_type: str,
    bot_source: str,
    limit: int = 20,
) -> list[dict]:
    """Последние события по типу."""
    rows = await get_pool().fetch(
        """SELECT * FROM events
           WHERE user_id = $1 AND event_type = $2 AND bot_source = $3
           ORDER BY timestamp DESC LIMIT $4""",
        user_id, event_type, bot_source, limit,
    )
    return [dict(r) for r in rows]


async def get_today_meals(user_id: int, bot_source: str = "health") -> list[dict]:
    """Приёмы пищи за сегодня (по серверному MSK-дню)."""
    rows = await get_pool().fetch(
        """SELECT * FROM events
           WHERE user_id = $1 AND event_type = 'meal' AND bot_source = $2
             AND timestamp >= (NOW() AT TIME ZONE 'Europe/Moscow')::date
           ORDER BY timestamp ASC""",
        user_id, bot_source,
    )
    return [dict(r) for r in rows]


async def get_today_workouts(user_id: int, bot_source: str = "health") -> list[dict]:
    """Тренировки за сегодня (по MSK-дню)."""
    rows = await get_pool().fetch(
        """SELECT * FROM events
           WHERE user_id = $1 AND event_type = 'workout' AND bot_source = $2
             AND timestamp >= (NOW() AT TIME ZONE 'Europe/Moscow')::date
           ORDER BY timestamp ASC""",
        user_id, bot_source,
    )
    return [dict(r) for r in rows]


async def get_cross_bot_summary(user_id: int, days: int = 7) -> list[dict]:
    """Последние события по ВСЕМ ботам за N дней (для кросс-бот контекста)."""
    rows = await get_pool().fetch(
        """SELECT bot_source, event_type, raw_text, json_data, timestamp
           FROM events
           WHERE user_id = $1 AND timestamp >= NOW() - ($2 || ' days')::interval
           ORDER BY timestamp DESC
           LIMIT 50""",
        user_id, str(days),
    )
    return [dict(r) for r in rows]


async def get_life_profile(user_id: int) -> list[dict]:
    """Ключевые события-профиль (авто, дом, здоровье) — без лимита по дате.

    Берём последние записи из assets-бота + ключевые типы из других.
    """
    rows = await get_pool().fetch(
        """SELECT bot_source, event_type, raw_text, json_data, timestamp
           FROM events
           WHERE user_id = $1
             AND (bot_source = 'assets'
                  OR event_type IN ('family_info', 'health_record'))
           ORDER BY timestamp DESC
           LIMIT 20""",
        user_id,
    )
    return [dict(r) for r in rows]


async def get_meals_range(
    user_id: int,
    date_from: str,
    date_to: str,
    bot_source: str = "health",
) -> list[dict]:
    """Приёмы пищи за диапазон дат (ISO-строки YYYY-MM-DD)."""
    rows = await get_pool().fetch(
        """SELECT * FROM events
           WHERE user_id = $1 AND event_type = 'meal' AND bot_source = $2
             AND timestamp >= $3::date
             AND timestamp < ($4::date + INTERVAL '1 day')
           ORDER BY timestamp ASC""",
        user_id, bot_source, date_from, date_to,
    )
    return [dict(r) for r in rows]


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
    row = await get_pool().fetchrow(
        """INSERT INTO finances (user_id, project_id, transaction_type, amount, category,
                                 description, receipt_url, source_event_id)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING *""",
        user_id, project_id, transaction_type, amount, category,
        description, receipt_url, source_event_id,
    )
    return dict(row)


async def get_finance_summary(project_id: int) -> list[dict]:
    """Сводка расходов/доходов по категориям для проекта (SQL only)."""
    rows = await get_pool().fetch(
        """SELECT transaction_type, category, SUM(amount)::numeric(12,2) AS total
           FROM finances WHERE project_id = $1
           GROUP BY transaction_type, category
           ORDER BY transaction_type, total DESC""",
        project_id,
    )
    return [dict(r) for r in rows]


# === Goals ===

async def get_active_goals(user_id: int) -> list[dict]:
    """Активные цели и мечты пользователя."""
    rows = await get_pool().fetch(
        "SELECT * FROM goals WHERE user_id = $1 AND status = 'active' ORDER BY created_at",
        user_id,
    )
    return [dict(r) for r in rows]


async def create_goal(
    user_id: int,
    goal_type: str,
    title: str,
    description: str = "",
    status: str = "active",
) -> dict:
    """Создать новую цель."""
    row = await get_pool().fetchrow(
        """INSERT INTO goals (user_id, type, title, description, status)
           VALUES ($1, $2, $3, $4, $5) RETURNING *""",
        user_id, goal_type, title, description, status,
    )
    return dict(row)


async def update_goal(goal_id: int, user_id: int, **kwargs: Any) -> None:
    """Обновить поля цели (ACL-filtered)."""
    if not kwargs:
        return
    sets = []
    vals: list[Any] = [goal_id, user_id]
    for i, (k, v) in enumerate(kwargs.items(), start=3):
        sets.append(f"{k} = ${i}")
        vals.append(v)
    sql = f"UPDATE goals SET {', '.join(sets)} WHERE id = $1 AND user_id = $2"
    await get_pool().execute(sql, *vals)


async def get_goal(goal_id: int) -> dict | None:
    """Получить цель по ID."""
    row = await get_pool().fetchrow("SELECT * FROM goals WHERE id = $1", goal_id)
    return dict(row) if row else None


# === Conversations (контекст диалога) ===

async def save_message(
    user_id: int,
    bot_source: str,
    role: str,
    content: str,
    tokens_used: int | None = None,
) -> None:
    """Сохранить сообщение в историю диалога."""
    await get_pool().execute(
        """INSERT INTO conversations (user_id, bot_source, role, content, tokens_used)
           VALUES ($1, $2, $3, $4, $5)""",
        user_id, bot_source, role, content, tokens_used,
    )


async def get_recent_messages(
    user_id: int,
    bot_source: str,
    limit: int = 20,
) -> list[dict]:
    """Последние N сообщений для контекста LLM."""
    rows = await get_pool().fetch(
        """SELECT role, content FROM conversations
           WHERE user_id = $1 AND bot_source = $2
           ORDER BY created_at DESC LIMIT $3""",
        user_id, bot_source, limit,
    )
    return [dict(r) for r in reversed(rows)]


async def get_today_messages(
    user_id: int,
    bot_source: str,
    limit: int = 20,
) -> list[dict]:
    """Сообщения только за СЕГОДНЯ (MSK) для health бота — не тащить вчерашние итоги."""
    rows = await get_pool().fetch(
        """SELECT role, content FROM conversations
           WHERE user_id = $1 AND bot_source = $2
             AND created_at >= (NOW() AT TIME ZONE 'Europe/Moscow')::date
                               AT TIME ZONE 'Europe/Moscow'
           ORDER BY created_at DESC LIMIT $3""",
        user_id, bot_source, limit,
    )
    return [dict(r) for r in reversed(rows)]


# === Projects ===

async def get_user_projects(user_id: int, status: str = "active") -> list[dict]:
    """Получить проекты пользователя по статусу (только owner)."""
    rows = await get_pool().fetch(
        "SELECT * FROM projects WHERE owner_id = $1 AND status = $2 ORDER BY created_at",
        user_id, status,
    )
    return [dict(r) for r in rows]


async def get_projects_by_type(user_id: int, project_type: str) -> list[dict]:
    """Получить доступные проекты по типу (owner ИЛИ collaborator)."""
    rows = await get_pool().fetch(
        """SELECT * FROM projects
           WHERE status = 'active' AND type = $2
             AND (owner_id = $1 OR $1 = ANY(collaborators))
           ORDER BY created_at""",
        user_id, project_type,
    )
    return [dict(r) for r in rows]


async def get_accessible_projects(user_id: int, project_type: str | None = None) -> list[dict]:
    """Все доступные проекты (owner или collaborator), опционально по типу."""
    if project_type:
        rows = await get_pool().fetch(
            """SELECT * FROM projects
               WHERE status = 'active' AND type = $2
                 AND (owner_id = $1 OR $1 = ANY(collaborators))
               ORDER BY created_at""",
            user_id, project_type,
        )
    else:
        rows = await get_pool().fetch(
            """SELECT * FROM projects
               WHERE status = 'active'
                 AND (owner_id = $1 OR $1 = ANY(collaborators))
               ORDER BY created_at""",
            user_id,
        )
    return [dict(r) for r in rows]


async def get_project(project_id: int) -> dict | None:
    """Получить проект по ID."""
    row = await get_pool().fetchrow("SELECT * FROM projects WHERE project_id = $1", project_id)
    return dict(row) if row else None


async def create_project(
    user_id: int,
    name: str,
    project_type: str = "solo",
    collaborators: list[int] | None = None,
    metadata: dict | None = None,
) -> dict:
    """Создать новый проект."""
    row = await get_pool().fetchrow(
        """INSERT INTO projects (name, type, owner_id, collaborators, status, metadata)
           VALUES ($1, $2, $3, $4, 'active', $5) RETURNING *""",
        name, project_type, user_id, collaborators or [], metadata or {},
    )
    return dict(row)


async def archive_project(project_id: int, user_id: int) -> bool:
    """Архивировать проект (ACL: только владелец)."""
    result = await get_pool().execute(
        "UPDATE projects SET status = 'archived' WHERE project_id = $1 AND owner_id = $2",
        project_id, user_id,
    )
    return result != "UPDATE 0"


async def update_project_metadata(project_id: int, user_id: int, metadata: dict) -> bool:
    """Обновить metadata проекта (ACL: только владелец)."""
    result = await get_pool().execute(
        "UPDATE projects SET metadata = $1 WHERE project_id = $2 AND owner_id = $3",
        metadata, project_id, user_id,
    )
    return result != "UPDATE 0"


async def add_collaborator(project_id: int, owner_id: int, partner_id: int) -> bool:
    """Добавить партнёра к проекту (ACL: только владелец)."""
    row = await get_pool().fetchrow(
        "SELECT collaborators FROM projects WHERE project_id = $1 AND owner_id = $2",
        project_id, owner_id,
    )
    if not row:
        return False
    current: list[int] = list(row["collaborators"] or [])
    if partner_id in current:
        return True
    current.append(partner_id)
    await get_pool().execute(
        "UPDATE projects SET collaborators = $1 WHERE project_id = $2",
        current, project_id,
    )
    return True


# === Model routing ===

async def get_model_config(task_type: str) -> dict | None:
    """Получить конфиг модели для task_type."""
    row = await get_pool().fetchrow(
        "SELECT * FROM model_routing WHERE task_type = $1", task_type,
    )
    return dict(row) if row else None


# === API Costs ===

async def insert_api_cost(
    user_id: int | None,
    bot_source: str | None,
    model: str,
    tokens_in: int,
    tokens_out: int,
    cost_usd: float,
    task_type: str | None = None,
) -> None:
    """Записать расход в api_costs."""
    await get_pool().execute(
        """INSERT INTO api_costs (user_id, bot_source, model, tokens_in, tokens_out, cost_usd, task_type)
           VALUES ($1, $2, $3, $4, $5, $6, $7)""",
        user_id, bot_source, model, tokens_in, tokens_out, cost_usd, task_type,
    )


async def sum_api_costs(since: datetime) -> float:
    """Сумма API-расходов с заданной даты."""
    val = await get_pool().fetchval(
        "SELECT COALESCE(SUM(cost_usd), 0) FROM api_costs WHERE timestamp >= $1", since,
    )
    return float(val)


# === RAG / pgvector ===

async def match_events(
    query_embedding: list[float],
    user_id: int,
    match_count: int = 5,
    project_id: int | None = None,
) -> list[dict]:
    """Семантический поиск по событиям (pgvector <=>)."""
    vec = np.array(query_embedding, dtype=np.float32)
    if project_id is not None:
        rows = await get_pool().fetch(
            """SELECT id, timestamp, user_id, project_id, bot_source, event_type,
                      raw_text, json_data, 1 - (embedding <=> $1) AS similarity
               FROM events
               WHERE embedding IS NOT NULL AND user_id = $2 AND project_id = $3
               ORDER BY embedding <=> $1 LIMIT $4""",
            vec, user_id, project_id, match_count,
        )
    else:
        rows = await get_pool().fetch(
            """SELECT id, timestamp, user_id, project_id, bot_source, event_type,
                      raw_text, json_data, 1 - (embedding <=> $1) AS similarity
               FROM events
               WHERE embedding IS NOT NULL AND user_id = $2
               ORDER BY embedding <=> $1 LIMIT $3""",
            vec, user_id, match_count,
        )
    return [dict(r) for r in rows]


# === Export helpers ===

async def get_user_finances(user_id: int) -> list[dict]:
    rows = await get_pool().fetch(
        "SELECT * FROM finances WHERE user_id = $1 ORDER BY timestamp", user_id,
    )
    return [dict(r) for r in rows]


async def get_user_events_export(user_id: int) -> list[dict]:
    rows = await get_pool().fetch(
        """SELECT id, timestamp, bot_source, event_type, raw_text, json_data, media_url, project_id
           FROM events WHERE user_id = $1 ORDER BY timestamp""",
        user_id,
    )
    return [dict(r) for r in rows]


async def get_user_conversations(user_id: int, limit: int = 500) -> list[dict]:
    rows = await get_pool().fetch(
        """SELECT bot_source, role, content, created_at
           FROM conversations WHERE user_id = $1
           ORDER BY created_at DESC LIMIT $2""",
        user_id, limit,
    )
    return [dict(r) for r in reversed(rows)]


async def get_user_api_costs(user_id: int, limit: int = 200) -> list[dict]:
    rows = await get_pool().fetch(
        """SELECT bot_source, model, tokens_in, tokens_out, cost_usd, timestamp
           FROM api_costs WHERE user_id = $1
           ORDER BY timestamp DESC LIMIT $2""",
        user_id, limit,
    )
    return [dict(r) for r in reversed(rows)]


# === Charts helpers ===

async def get_finance_data(user_id: int, project_id: int | None = None) -> list[dict]:
    """Финансовые данные для графика тренда."""
    if project_id:
        rows = await get_pool().fetch(
            """SELECT transaction_type, amount, timestamp FROM finances
               WHERE user_id = $1 AND project_id = $2 ORDER BY timestamp""",
            user_id, project_id,
        )
    else:
        rows = await get_pool().fetch(
            "SELECT transaction_type, amount, timestamp FROM finances WHERE user_id = $1 ORDER BY timestamp",
            user_id,
        )
    return [dict(r) for r in rows]


async def get_expense_data(user_id: int, project_id: int | None = None) -> list[dict]:
    """Данные расходов по категориям для pie chart."""
    if project_id:
        rows = await get_pool().fetch(
            """SELECT category, amount FROM finances
               WHERE user_id = $1 AND transaction_type = 'expense' AND project_id = $2""",
            user_id, project_id,
        )
    else:
        rows = await get_pool().fetch(
            "SELECT category, amount FROM finances WHERE user_id = $1 AND transaction_type = 'expense'",
            user_id,
        )
    return [dict(r) for r in rows]


# === Tasks (Планировщик) ===

def _parse_date(val: str | date_type | None) -> date_type | None:
    """Конвертировать строку YYYY-MM-DD в datetime.date для asyncpg."""
    if val is None:
        return None
    if isinstance(val, date_type):
        return val
    return date_type.fromisoformat(str(val)[:10])


def _parse_time(val: str | time_type | None) -> time_type | None:
    """Конвертировать строку HH:MM в datetime.time для asyncpg."""
    if val is None:
        return None
    if isinstance(val, time_type):
        return val
    parts = str(val).split(":")
    return time_type(int(parts[0]), int(parts[1]))


async def create_task(
    user_id: int,
    task_text: str,
    due_date: str | date_type | None = None,
    due_time: str | time_type | None = None,
    priority: str = "normal",
    project_id: int | None = None,
    source: str = "telegram",
    source_file: str | None = None,
) -> dict:
    """Создать задачу."""
    row = await get_pool().fetchrow(
        """INSERT INTO tasks (user_id, task_text, due_date, due_time, priority,
                              project_id, source, source_file)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8) RETURNING *""",
        user_id, task_text, _parse_date(due_date), _parse_time(due_time), priority,
        project_id, source, source_file,
    )
    return dict(row)


async def get_tasks_by_date(user_id: int, date: str) -> list[dict]:
    """Задачи на конкретную дату (YYYY-MM-DD)."""
    rows = await get_pool().fetch(
        """SELECT t.*, p.name AS project_name
           FROM tasks t
           LEFT JOIN projects p ON t.project_id = p.project_id
           WHERE t.user_id = $1 AND t.due_date = $2
           ORDER BY t.is_done ASC, t.due_time ASC NULLS LAST, t.priority DESC""",
        user_id, _parse_date(date),
    )
    return [dict(r) for r in rows]


async def get_today_tasks(user_id: int) -> list[dict]:
    """Задачи на сегодня (MSK)."""
    rows = await get_pool().fetch(
        """SELECT t.*, p.name AS project_name
           FROM tasks t
           LEFT JOIN projects p ON t.project_id = p.project_id
           WHERE t.user_id = $1
             AND t.due_date = (NOW() AT TIME ZONE 'Europe/Moscow')::date
           ORDER BY t.is_done ASC, t.due_time ASC NULLS LAST, t.priority DESC""",
        user_id,
    )
    return [dict(r) for r in rows]


async def get_overdue_tasks(user_id: int) -> list[dict]:
    """Просроченные невыполненные задачи."""
    rows = await get_pool().fetch(
        """SELECT t.*, p.name AS project_name
           FROM tasks t
           LEFT JOIN projects p ON t.project_id = p.project_id
           WHERE t.user_id = $1
             AND t.is_done = FALSE
             AND t.due_date < (NOW() AT TIME ZONE 'Europe/Moscow')::date
           ORDER BY t.due_date ASC""",
        user_id,
    )
    return [dict(r) for r in rows]


async def get_week_tasks(user_id: int) -> list[dict]:
    """Задачи на текущую неделю (MSK)."""
    rows = await get_pool().fetch(
        """SELECT t.*, p.name AS project_name
           FROM tasks t
           LEFT JOIN projects p ON t.project_id = p.project_id
           WHERE t.user_id = $1
             AND t.due_date >= date_trunc('week', (NOW() AT TIME ZONE 'Europe/Moscow')::date)
             AND t.due_date < date_trunc('week', (NOW() AT TIME ZONE 'Europe/Moscow')::date) + INTERVAL '7 days'
           ORDER BY t.due_date ASC, t.is_done ASC, t.due_time ASC NULLS LAST""",
        user_id,
    )
    return [dict(r) for r in rows]


async def complete_task(task_id: int, user_id: int) -> bool:
    """Отметить задачу выполненной (ACL: только владелец)."""
    result = await get_pool().execute(
        """UPDATE tasks SET is_done = TRUE, done_at = NOW(), updated_at = NOW()
           WHERE id = $1 AND user_id = $2""",
        task_id, user_id,
    )
    return result != "UPDATE 0"


async def uncomplete_task(task_id: int, user_id: int) -> bool:
    """Снять отметку выполненной."""
    result = await get_pool().execute(
        """UPDATE tasks SET is_done = FALSE, done_at = NULL, updated_at = NOW()
           WHERE id = $1 AND user_id = $2""",
        task_id, user_id,
    )
    return result != "UPDATE 0"


async def get_task_by_id(task_id: int, user_id: int) -> dict | None:
    """Получить задачу по ID (ACL: только владелец)."""
    row = await get_pool().fetchrow(
        "SELECT * FROM tasks WHERE id = $1 AND user_id = $2",
        task_id, user_id,
    )
    return dict(row) if row else None


async def reschedule_task(task_id: int, user_id: int, new_date: str) -> bool:
    """Перенести задачу на другую дату."""
    result = await get_pool().execute(
        """UPDATE tasks SET due_date = $3, reminder_sent = FALSE, updated_at = NOW()
           WHERE id = $1 AND user_id = $2""",
        task_id, user_id, _parse_date(new_date),
    )
    return result != "UPDATE 0"


async def delete_task(task_id: int, user_id: int) -> bool:
    """Удалить задачу (ACL: только владелец)."""
    result = await get_pool().execute(
        "DELETE FROM tasks WHERE id = $1 AND user_id = $2",
        task_id, user_id,
    )
    return result != "DELETE 0"


async def get_pending_task_reminders() -> list[dict]:
    """Задачи, у которых наступило время напоминания (для scheduler)."""
    rows = await get_pool().fetch(
        """SELECT t.*, u.display_name
           FROM tasks t
           JOIN users u ON t.user_id = u.user_id
           WHERE t.is_done = FALSE
             AND t.reminder_sent = FALSE
             AND t.due_date = (NOW() AT TIME ZONE 'Europe/Moscow')::date
             AND t.due_time IS NOT NULL
             AND t.due_time <= (NOW() AT TIME ZONE 'Europe/Moscow')::time
           ORDER BY t.due_time ASC""",
    )
    return [dict(r) for r in rows]


async def mark_reminder_sent(task_id: int) -> None:
    """Пометить, что напоминание отправлено."""
    await get_pool().execute(
        "UPDATE tasks SET reminder_sent = TRUE WHERE id = $1", task_id,
    )


async def get_unclosed_tasks(user_id: int) -> list[dict]:
    """Невыполненные задачи на сегодня (для вечернего обзора)."""
    rows = await get_pool().fetch(
        """SELECT * FROM tasks
           WHERE user_id = $1
             AND is_done = FALSE
             AND due_date = (NOW() AT TIME ZONE 'Europe/Moscow')::date
           ORDER BY due_time ASC NULLS LAST""",
        user_id,
    )
    return [dict(r) for r in rows]


async def get_completed_today_count(user_id: int) -> int:
    """Количество выполненных задач за сегодня."""
    val = await get_pool().fetchval(
        """SELECT COUNT(*) FROM tasks
           WHERE user_id = $1
             AND is_done = TRUE
             AND due_date = (NOW() AT TIME ZONE 'Europe/Moscow')::date""",
        user_id,
    )
    return int(val)


# === Obsidian Tasks ===

async def upsert_obsidian_task(
    user_id: int,
    task_text: str,
    source_file: str,
    due_date: str | None = None,
    due_time: str | None = None,
    is_done: bool = False,
) -> dict:
    """Создать или обновить задачу из Obsidian (дедупликация по source_file + task_text)."""
    dd = _parse_date(due_date) if due_date else None
    dt = _parse_time(due_time) if due_time else None
    row = await get_pool().fetchrow(
        """INSERT INTO obsidian_tasks (user_id, task_text, source_file, due_date, due_time, is_done, updated_at)
           VALUES ($1, $2, $3, $4, $5, $6, NOW())
           ON CONFLICT (source_file, task_text)
           DO UPDATE SET due_date = EXCLUDED.due_date,
                         due_time = EXCLUDED.due_time,
                         is_done  = EXCLUDED.is_done,
                         updated_at = NOW()
           RETURNING *""",
        user_id, task_text, source_file, dd, dt, is_done,
    )
    return dict(row)


async def get_obsidian_pending_reminders() -> list[dict]:
    """Obsidian-задачи, у которых наступило время напоминания."""
    rows = await get_pool().fetch(
        """SELECT * FROM obsidian_tasks
           WHERE is_done = FALSE
             AND reminder_sent = FALSE
             AND due_date = (NOW() AT TIME ZONE 'Europe/Moscow')::date
             AND due_time IS NOT NULL
             AND due_time <= (NOW() AT TIME ZONE 'Europe/Moscow')::time
           ORDER BY due_time ASC""",
    )
    return [dict(r) for r in rows]


async def mark_obsidian_reminder_sent(task_id: int) -> None:
    """Пометить obsidian-напоминание как отправленное."""
    await get_pool().execute(
        "UPDATE obsidian_tasks SET reminder_sent = TRUE WHERE id = $1", task_id,
    )


async def get_obsidian_today_tasks(user_id: int) -> list[dict]:
    """Все obsidian-задачи на сегодня."""
    rows = await get_pool().fetch(
        """SELECT * FROM obsidian_tasks
           WHERE user_id = $1
             AND due_date = (NOW() AT TIME ZONE 'Europe/Moscow')::date
           ORDER BY is_done ASC, due_time ASC NULLS LAST""",
        user_id,
    )
    return [dict(r) for r in rows]
