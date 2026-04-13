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


async def get_obsidian_note_events(user_id: int, source_file: str) -> list[dict]:
    """Найти ВСЕ events (чанки) для obsidian_note по source_file."""
    rows = await get_pool().fetch(
        """SELECT * FROM events
           WHERE user_id = $1
             AND event_type = 'obsidian_note'
             AND json_data->>'source_file' = $2
           ORDER BY (json_data->>'chunk_index')::int NULLS FIRST""",
        user_id, source_file,
    )
    return [dict(r) for r in rows]


async def delete_event(event_id: int) -> None:
    """Удалить event по id."""
    await get_pool().execute("DELETE FROM events WHERE id = $1", event_id)


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


async def get_today_water(user_id: int) -> list[dict]:
    """Записи воды за сегодня (по MSK-дню)."""
    rows = await get_pool().fetch(
        """SELECT * FROM events
           WHERE user_id = $1 AND event_type = 'water' AND bot_source = 'health'
             AND timestamp >= (NOW() AT TIME ZONE 'Europe/Moscow')::date
           ORDER BY timestamp ASC""",
        user_id,
    )
    return [dict(r) for r in rows]


async def get_weight_history(user_id: int, limit: int = 30) -> list[dict]:
    """Последние записи веса/замеров за N записей."""
    rows = await get_pool().fetch(
        """SELECT * FROM events
           WHERE user_id = $1 AND event_type = 'weight' AND bot_source = 'health'
           ORDER BY timestamp DESC LIMIT $2""",
        user_id, limit,
    )
    return [dict(r) for r in rows]


async def get_gratitude_today(user_id: int) -> list[dict]:
    """Записи благодарностей за сегодня."""
    rows = await get_pool().fetch(
        """SELECT * FROM events
           WHERE user_id = $1 AND event_type = 'gratitude' AND bot_source = 'psychology'
             AND timestamp >= (NOW() AT TIME ZONE 'Europe/Moscow')::date
           ORDER BY timestamp ASC""",
        user_id,
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
    from datetime import date as _date
    d_from = _date.fromisoformat(date_from) if isinstance(date_from, str) else date_from
    d_to = _date.fromisoformat(date_to) if isinstance(date_to, str) else date_to
    rows = await get_pool().fetch(
        """SELECT * FROM events
           WHERE user_id = $1 AND event_type = 'meal' AND bot_source = $2
             AND timestamp >= $3::date
             AND timestamp < ($4::date + INTERVAL '1 day')
           ORDER BY timestamp ASC""",
        user_id, bot_source, d_from, d_to,
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


async def delete_finance(finance_id: int, user_id: int) -> bool:
    """Удалить транзакцию (ACL: только владелец)."""
    result = await get_pool().execute(
        "DELETE FROM finances WHERE id = $1 AND user_id = $2",
        finance_id, user_id,
    )
    return result != "DELETE 0"


async def get_recent_finances(user_id: int, project_id: int | None = None, limit: int = 10) -> list[dict]:
    """Последние транзакции пользователя."""
    if project_id:
        rows = await get_pool().fetch(
            """SELECT * FROM finances
               WHERE user_id = $1 AND project_id = $2
               ORDER BY timestamp DESC LIMIT $3""",
            user_id, project_id, limit,
        )
    else:
        rows = await get_pool().fetch(
            """SELECT * FROM finances
               WHERE user_id = $1
               ORDER BY timestamp DESC LIMIT $2""",
            user_id, limit,
        )
    return [dict(r) for r in rows]


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


async def get_finances_for_export(user_id: int) -> list[dict]:
    """Все транзакции пользователя для CSV-экспорта."""
    rows = await get_pool().fetch(
        """SELECT f.id, f.transaction_type, f.amount, f.category, f.description,
                  f.timestamp, p.name AS project_name
           FROM finances f
           LEFT JOIN projects p ON f.project_id = p.project_id
           WHERE f.user_id = $1
           ORDER BY f.timestamp DESC""",
        user_id,
    )
    return [dict(r) for r in rows]


async def get_month_finance_by_category(project_id: int, year: int, month: int) -> list[dict]:
    """Расходы/доходы за конкретный месяц по категориям (для бюджета план/факт)."""
    rows = await get_pool().fetch(
        """SELECT transaction_type, category, SUM(amount)::numeric(12,2) AS total
           FROM finances
           WHERE project_id = $1
             AND EXTRACT(YEAR FROM timestamp) = $2
             AND EXTRACT(MONTH FROM timestamp) = $3
           GROUP BY transaction_type, category
           ORDER BY transaction_type, total DESC""",
        project_id, year, month,
    )
    return [dict(r) for r in rows]


async def get_monthly_totals(project_id: int, months: int = 6) -> list[dict]:
    """Итоги расходов/доходов по месяцам за последние N месяцев (SQL only)."""
    rows = await get_pool().fetch(
        """SELECT
               EXTRACT(YEAR FROM timestamp)::int AS year,
               EXTRACT(MONTH FROM timestamp)::int AS month,
               transaction_type,
               SUM(amount)::numeric(12,2) AS total
           FROM finances
           WHERE project_id = $1
             AND timestamp >= (NOW() - ($2 || ' months')::interval)
           GROUP BY year, month, transaction_type
           ORDER BY year, month""",
        project_id, str(months),
    )
    return [dict(r) for r in rows]


async def get_project_events(project_id: int, limit: int = 10) -> list[dict]:
    """Последние события проекта."""
    rows = await get_pool().fetch(
        """SELECT * FROM events
           WHERE project_id = $1
           ORDER BY timestamp DESC LIMIT $2""",
        project_id, limit,
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


async def get_project_by_name(name: str) -> dict | None:
    """Получить активный проект по имени (для маппинга Obsidian → project_id)."""
    row = await get_pool().fetchrow(
        "SELECT * FROM projects WHERE LOWER(name) = LOWER($1) AND status = 'active' LIMIT 1",
        name,
    )
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


async def get_weekly_finance_summary(project_id: int, weeks: int = 8) -> list[dict]:
    """Расходы и доходы по неделям за последние N недель."""
    rows = await get_pool().fetch(
        """SELECT
             date_trunc('week', timestamp)::date AS week_start,
             transaction_type,
             SUM(amount) AS total
           FROM finances
           WHERE project_id = $1
             AND timestamp >= NOW() - make_interval(weeks => $2)
           GROUP BY week_start, transaction_type
           ORDER BY week_start""",
        project_id, weeks,
    )
    return [dict(r) for r in rows]


async def get_monthly_mood_data(user_id: int, year: int, month: int) -> list[dict]:
    """Настроения за указанный месяц для психологического отчёта."""
    rows = await get_pool().fetch(
        """SELECT
             timestamp::date AS day,
             (json_data->>'score')::int AS score
           FROM events
           WHERE user_id = $1
             AND event_type = 'mood'
             AND EXTRACT(YEAR FROM timestamp) = $2
             AND EXTRACT(MONTH FROM timestamp) = $3
           ORDER BY timestamp""",
        user_id, year, month,
    )
    return [dict(r) for r in rows]


async def get_monthly_diary_entries(user_id: int, year: int, month: int) -> list[dict]:
    """Дневниковые записи за месяц."""
    rows = await get_pool().fetch(
        """SELECT timestamp, raw_text
           FROM events
           WHERE user_id = $1
             AND bot_source = 'psychology'
             AND event_type = 'diary'
             AND EXTRACT(YEAR FROM timestamp) = $2
             AND EXTRACT(MONTH FROM timestamp) = $3
           ORDER BY timestamp""",
        user_id, year, month,
    )
    return [dict(r) for r in rows]


async def get_monthly_habit_stats(user_id: int, year: int, month: int) -> list[dict]:
    """Статистика привычек за месяц: сколько раз отмечено."""
    rows = await get_pool().fetch(
        """SELECT
             g.title,
             COUNT(CASE WHEN json_data->>'status' = 'done' THEN 1 END) AS done_count,
             COUNT(*) AS total_count
           FROM events e
           JOIN goals g ON g.id = (e.json_data->>'goal_id')::int
           WHERE e.user_id = $1
             AND e.event_type = 'habit_check'
             AND EXTRACT(YEAR FROM e.timestamp) = $2
             AND EXTRACT(MONTH FROM e.timestamp) = $3
           GROUP BY g.title
           ORDER BY done_count DESC""",
        user_id, year, month,
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
    recurrence: str | None = None,
    parent_task_id: int | None = None,
    goal_id: int | None = None,
    tags: list[str] | None = None,
) -> dict:
    """Create a task, optionally recurring, with subtask/goal/tag support."""
    row = await get_pool().fetchrow(
        """INSERT INTO tasks (user_id, task_text, due_date, due_time, priority,
                              project_id, source, source_file, recurrence,
                              parent_task_id, goal_id, tags)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10, $11, $12) RETURNING *""",
        user_id, task_text, _parse_date(due_date), _parse_time(due_time), priority,
        project_id, source, source_file, recurrence,
        parent_task_id, goal_id, tags or [],
    )
    return dict(row)


async def get_tasks_by_date(user_id: int, date: str) -> list[dict]:
    """Задачи на конкретную дату (YYYY-MM-DD), без подзадач."""
    rows = await get_pool().fetch(
        """SELECT t.*, p.name AS project_name, g.title AS goal_title,
                  (SELECT COUNT(*) FROM tasks st WHERE st.parent_task_id = t.id) AS subtask_count,
                  (SELECT COUNT(*) FROM tasks st WHERE st.parent_task_id = t.id AND st.is_done = TRUE) AS subtask_done
           FROM tasks t
           LEFT JOIN projects p ON t.project_id = p.project_id
           LEFT JOIN goals g ON t.goal_id = g.id
           WHERE t.user_id = $1 AND t.due_date = $2 AND t.parent_task_id IS NULL
           ORDER BY t.sort_order ASC, t.is_done ASC, t.due_time ASC NULLS LAST, t.priority DESC""",
        user_id, _parse_date(date),
    )
    return [dict(r) for r in rows]


async def get_today_tasks(user_id: int) -> list[dict]:
    """Задачи на сегодня (MSK), без подзадач."""
    rows = await get_pool().fetch(
        """SELECT t.*, p.name AS project_name, g.title AS goal_title,
                  (SELECT COUNT(*) FROM tasks st WHERE st.parent_task_id = t.id) AS subtask_count,
                  (SELECT COUNT(*) FROM tasks st WHERE st.parent_task_id = t.id AND st.is_done = TRUE) AS subtask_done
           FROM tasks t
           LEFT JOIN projects p ON t.project_id = p.project_id
           LEFT JOIN goals g ON t.goal_id = g.id
           WHERE t.user_id = $1
             AND t.due_date = (NOW() AT TIME ZONE 'Europe/Moscow')::date
             AND t.parent_task_id IS NULL
           ORDER BY t.sort_order ASC, t.is_done ASC, t.due_time ASC NULLS LAST, t.priority DESC""",
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


async def get_quarter_summary(user_id: int) -> dict:
    """Сводка за текущий квартал: задачи, финансы, цели."""
    pool = get_pool()
    q_start = "date_trunc('quarter', (NOW() AT TIME ZONE 'Europe/Moscow'))"

    completed = await pool.fetchval(
        f"""SELECT COUNT(*) FROM tasks
           WHERE user_id = $1 AND is_done = TRUE
             AND done_at >= {q_start}""",
        user_id,
    ) or 0

    created = await pool.fetchval(
        f"""SELECT COUNT(*) FROM tasks
           WHERE user_id = $1
             AND created_at >= {q_start}""",
        user_id,
    ) or 0

    overdue = await pool.fetchval(
        f"""SELECT COUNT(*) FROM tasks
           WHERE user_id = $1 AND is_done = FALSE
             AND due_date < (NOW() AT TIME ZONE 'Europe/Moscow')::date
             AND created_at >= {q_start}""",
        user_id,
    ) or 0

    fin_rows = await pool.fetch(
        f"""SELECT transaction_type, COALESCE(SUM(amount), 0)::numeric(12,2) AS total
           FROM finances
           WHERE user_id = $1
             AND timestamp >= {q_start}
           GROUP BY transaction_type""",
        user_id,
    )
    q_income = 0.0
    q_expense = 0.0
    for r in fin_rows:
        if r["transaction_type"] == "income":
            q_income = float(r["total"])
        else:
            q_expense = float(r["total"])

    return {
        "completed": completed,
        "created": created,
        "overdue": overdue,
        "quarter_income": q_income,
        "quarter_expense": q_expense,
    }


async def get_uncompleted_tasks_for_matrix(user_id: int) -> list[dict]:
    """Все незавершённые задачи пользователя (для матрицы Эйзенхауэра)."""
    rows = await get_pool().fetch(
        """SELECT t.id, t.task_text, t.due_date, t.due_time, t.priority,
                  t.goal_id, g.title AS goal_title, t.tags
           FROM tasks t
           LEFT JOIN goals g ON t.goal_id = g.id
           WHERE t.user_id = $1 AND t.is_done = FALSE
             AND t.parent_task_id IS NULL
           ORDER BY t.due_date ASC NULLS LAST, t.priority DESC""",
        user_id,
    )
    return [dict(r) for r in rows]


async def get_week_summary(user_id: int) -> dict:
    """Сводка за текущую неделю: выполнено/создано задач, финансы."""
    pool = get_pool()

    # Задачи: выполнено за неделю
    completed = await pool.fetchval(
        """SELECT COUNT(*) FROM tasks
           WHERE user_id = $1 AND is_done = TRUE
             AND done_at >= date_trunc('week', (NOW() AT TIME ZONE 'Europe/Moscow'))""",
        user_id,
    ) or 0

    # Задачи: создано за неделю
    created = await pool.fetchval(
        """SELECT COUNT(*) FROM tasks
           WHERE user_id = $1
             AND created_at >= date_trunc('week', (NOW() AT TIME ZONE 'Europe/Moscow'))""",
        user_id,
    ) or 0

    # Финансы за неделю
    fin_rows = await pool.fetch(
        """SELECT transaction_type, COALESCE(SUM(amount), 0)::numeric(12,2) AS total
           FROM finances
           WHERE user_id = $1
             AND timestamp >= date_trunc('week', (NOW() AT TIME ZONE 'Europe/Moscow'))
           GROUP BY transaction_type""",
        user_id,
    )
    week_income = 0.0
    week_expense = 0.0
    for r in fin_rows:
        if r["transaction_type"] == "income":
            week_income = float(r["total"])
        else:
            week_expense = float(r["total"])

    return {
        "completed": completed,
        "created": created,
        "week_income": week_income,
        "week_expense": week_expense,
    }


async def get_week_events_by_type(user_id: int) -> dict:
    """Сводка событий за неделю по типам (для Weekly Notes)."""
    pool = get_pool()
    rows = await pool.fetch(
        """SELECT event_type, COUNT(*) AS cnt
           FROM events
           WHERE user_id = $1
             AND timestamp >= date_trunc('week', (NOW() AT TIME ZONE 'Europe/Moscow'))
           GROUP BY event_type""",
        user_id,
    )
    return {r["event_type"]: r["cnt"] for r in rows}


async def get_today_focus(user_id: int) -> dict | None:
    """Получить фокус дня (последний за сегодня)."""
    row = await get_pool().fetchrow(
        """SELECT * FROM events
           WHERE user_id = $1 AND event_type = 'focus' AND bot_source = 'master'
             AND timestamp >= (NOW() AT TIME ZONE 'Europe/Moscow')::date
           ORDER BY timestamp DESC LIMIT 1""",
        user_id,
    )
    return dict(row) if row else None


async def complete_task(task_id: int, user_id: int) -> bool:
    """Отметить задачу выполненной (ACL: только владелец)."""
    result = await get_pool().execute(
        """UPDATE tasks SET is_done = TRUE, done_at = NOW(), updated_at = NOW(),
                           kanban_status = 'done'
           WHERE id = $1 AND user_id = $2""",
        task_id, user_id,
    )
    return result != "UPDATE 0"


async def uncomplete_task(task_id: int, user_id: int) -> bool:
    """Снять отметку выполненной."""
    result = await get_pool().execute(
        """UPDATE tasks SET is_done = FALSE, done_at = NULL, updated_at = NOW(),
                           kanban_status = 'todo'
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


async def get_recurring_tasks_due(target_date: str) -> list[dict]:
    """Повторяющиеся задачи, которые нужно создать на target_date."""
    d = _parse_date(target_date)
    dow = d.weekday() if d else 0  # 0=Mon ... 6=Sun
    rows = await get_pool().fetch(
        """SELECT * FROM tasks
           WHERE recurrence IS NOT NULL
             AND recurrence_parent_id IS NULL
             AND is_done = FALSE
             AND NOT EXISTS (
                 SELECT 1 FROM tasks t2
                 WHERE t2.recurrence_parent_id = tasks.id
                   AND t2.due_date = $1
             )""",
        d,
    )
    result = []
    for r in rows:
        rec = r["recurrence"]
        if rec == "daily":
            result.append(dict(r))
        elif rec == "weekdays" and dow < 5:
            result.append(dict(r))
        elif rec == "weekly" and r["due_date"] and r["due_date"].weekday() == dow:
            result.append(dict(r))
        elif rec == "monthly" and r["due_date"] and r["due_date"].day == d.day:
            result.append(dict(r))
    return result


async def spawn_recurring_task(parent: dict, target_date: str) -> dict:
    """Создать экземпляр повторяющейся задачи."""
    row = await get_pool().fetchrow(
        """INSERT INTO tasks (user_id, task_text, due_date, due_time, priority,
                              project_id, source, recurrence_parent_id)
           VALUES ($1, $2, $3, $4, $5, $6, 'telegram', $7) RETURNING *""",
        parent["user_id"], parent["task_text"], _parse_date(target_date),
        parent.get("due_time"), parent.get("priority", "normal"),
        parent.get("project_id"), parent["id"],
    )
    return dict(row)


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


# ── Debts / Credits ──────────────────────────────────────────────

async def create_debt(
    user_id: int,
    debt_type: str,
    title: str,
    total_amount: float,
    remaining: float | None = None,
    monthly_payment: float | None = None,
    interest_rate: float | None = None,
    due_date: str | None = None,
    creditor: str | None = None,
    notes: str | None = None,
) -> dict:
    """Создать запись о долге или кредите."""
    from datetime import date as _date
    if remaining is None:
        remaining = total_amount
    # asyncpg требует datetime.date, не строку
    parsed_due: _date | None = None
    if due_date:
        try:
            parsed_due = _date.fromisoformat(str(due_date)[:10])
        except (ValueError, TypeError):
            parsed_due = None
    row = await get_pool().fetchrow(
        """INSERT INTO debts
               (user_id, debt_type, title, total_amount, remaining,
                monthly_payment, interest_rate, due_date, creditor, notes)
           VALUES ($1, $2, $3, $4, $5, $6, $7, $8, $9, $10)
           RETURNING *""",
        user_id, debt_type, title, total_amount, remaining,
        monthly_payment, interest_rate, parsed_due, creditor, notes,
    )
    return dict(row)


async def get_user_debts(user_id: int, active_only: bool = True) -> list[dict]:
    """Список долгов/кредитов пользователя."""
    condition = " AND is_active = TRUE" if active_only else ""
    rows = await get_pool().fetch(
        f"""SELECT * FROM debts
            WHERE user_id = $1{condition}
            ORDER BY debt_type, created_at DESC""",
        user_id,
    )
    return [dict(r) for r in rows]


async def get_debt(debt_id: int, user_id: int) -> dict | None:
    """Получить один долг по ID (ACL: владелец)."""
    row = await get_pool().fetchrow(
        "SELECT * FROM debts WHERE id = $1 AND user_id = $2",
        debt_id, user_id,
    )
    return dict(row) if row else None


async def update_debt(debt_id: int, user_id: int, **fields) -> dict | None:
    """Обновить поля долга (ACL: владелец)."""
    from datetime import date as _date
    allowed = {
        "title", "total_amount", "remaining", "monthly_payment",
        "interest_rate", "due_date", "creditor", "notes", "is_active",
    }
    parts, vals = [], []
    idx = 3
    for k, v in fields.items():
        if k not in allowed:
            continue
        if k == "due_date" and isinstance(v, str):
            try:
                v = _date.fromisoformat(v[:10])
            except (ValueError, TypeError):
                v = None
        parts.append(f"{k} = ${idx}")
        vals.append(v)
        idx += 1
    if not parts:
        return await get_debt(debt_id, user_id)
    row = await get_pool().fetchrow(
        f"UPDATE debts SET {', '.join(parts)} WHERE id = $1 AND user_id = $2 RETURNING *",
        debt_id, user_id, *vals,
    )
    return dict(row) if row else None


async def pay_debt(debt_id: int, user_id: int, amount: float) -> dict | None:
    """Внести платёж по долгу/кредиту — уменьшить остаток."""
    row = await get_pool().fetchrow(
        """UPDATE debts
           SET remaining = GREATEST(remaining - $3, 0)
           WHERE id = $1 AND user_id = $2 AND is_active = TRUE
           RETURNING *""",
        debt_id, user_id, amount,
    )
    if row and float(row["remaining"]) <= 0:
        await get_pool().execute(
            "UPDATE debts SET is_active = FALSE WHERE id = $1", debt_id,
        )
        return {**dict(row), "is_active": False}
    return dict(row) if row else None


async def close_debt(debt_id: int, user_id: int) -> bool:
    """Закрыть долг/кредит вручную."""
    result = await get_pool().execute(
        "UPDATE debts SET is_active = FALSE, remaining = 0 WHERE id = $1 AND user_id = $2",
        debt_id, user_id,
    )
    return result != "UPDATE 0"


async def delete_debt(debt_id: int, user_id: int) -> bool:
    """Удалить долг/кредит (ACL: владелец)."""
    result = await get_pool().execute(
        "DELETE FROM debts WHERE id = $1 AND user_id = $2",
        debt_id, user_id,
    )
    return result != "DELETE 0"


async def get_debts_summary(user_id: int) -> dict:
    """Сводка по активным долгам и кредитам."""
    rows = await get_pool().fetch(
        """SELECT debt_type,
                  COUNT(*) AS cnt,
                  COALESCE(SUM(remaining), 0) AS total_remaining,
                  COALESCE(SUM(monthly_payment), 0) AS total_monthly
           FROM debts
           WHERE user_id = $1 AND is_active = TRUE
           GROUP BY debt_type""",
        user_id,
    )
    result = {"debt": {"count": 0, "remaining": 0.0, "monthly": 0.0},
              "credit": {"count": 0, "remaining": 0.0, "monthly": 0.0}}
    for r in rows:
        dt = r["debt_type"]
        result[dt] = {
            "count": r["cnt"],
            "remaining": float(r["total_remaining"]),
            "monthly": float(r["total_monthly"]),
        }
    return result


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


# === Subtasks, Tags, Kanban ===

async def get_subtasks(parent_task_id: int, user_id: int) -> list[dict]:
    """Подзадачи конкретной задачи."""
    rows = await get_pool().fetch(
        """SELECT * FROM tasks
           WHERE parent_task_id = $1 AND user_id = $2
           ORDER BY sort_order ASC, is_done ASC, id ASC""",
        parent_task_id, user_id,
    )
    return [dict(r) for r in rows]


async def get_kanban_tasks(user_id: int) -> dict[str, list[dict]]:
    """Задачи в формате Kanban (backlog / todo / in_progress / done)."""
    rows = await get_pool().fetch(
        """SELECT t.*, p.name AS project_name, g.title AS goal_title
           FROM tasks t
           LEFT JOIN projects p ON t.project_id = p.project_id
           LEFT JOIN goals g ON t.goal_id = g.id
           WHERE t.user_id = $1
             AND t.parent_task_id IS NULL
             AND (t.kanban_status != 'done' OR t.done_at >= NOW() - INTERVAL '7 days')
           ORDER BY t.sort_order ASC, t.priority DESC, t.due_date ASC NULLS LAST""",
        user_id,
    )
    result: dict[str, list[dict]] = {"backlog": [], "todo": [], "in_progress": [], "done": []}
    for r in rows:
        status = r.get("kanban_status") or "todo"
        if status in result:
            result[status].append(dict(r))
    return result


async def update_kanban_status(task_id: int, user_id: int, status: str) -> bool:
    """Обновить kanban-статус задачи."""
    result = await get_pool().execute(
        """UPDATE tasks SET kanban_status = $3, updated_at = NOW()
           WHERE id = $1 AND user_id = $2""",
        task_id, user_id, status,
    )
    return result != "UPDATE 0"


async def get_tasks_by_tag(user_id: int, tag: str) -> list[dict]:
    """Задачи по тэгу."""
    rows = await get_pool().fetch(
        """SELECT t.*, p.name AS project_name, g.title AS goal_title
           FROM tasks t
           LEFT JOIN projects p ON t.project_id = p.project_id
           LEFT JOIN goals g ON t.goal_id = g.id
           WHERE t.user_id = $1 AND $2 = ANY(t.tags)
           ORDER BY t.is_done ASC, t.due_date ASC NULLS LAST""",
        user_id, tag,
    )
    return [dict(r) for r in rows]


async def get_all_tags(user_id: int) -> list[str]:
    """Все уникальные тэги пользователя."""
    rows = await get_pool().fetch(
        """SELECT DISTINCT unnest(tags) AS tag FROM tasks
           WHERE user_id = $1 AND array_length(tags, 1) > 0
           ORDER BY tag""",
        user_id,
    )
    return [r["tag"] for r in rows]


async def update_task_tags(task_id: int, user_id: int, tags: list[str]) -> bool:
    """Обновить тэги задачи."""
    result = await get_pool().execute(
        """UPDATE tasks SET tags = $3, updated_at = NOW()
           WHERE id = $1 AND user_id = $2""",
        task_id, user_id, tags,
    )
    return result != "UPDATE 0"


async def update_task_goal(task_id: int, user_id: int, goal_id: int | None) -> bool:
    """Привязать задачу к цели."""
    result = await get_pool().execute(
        """UPDATE tasks SET goal_id = $3, updated_at = NOW()
           WHERE id = $1 AND user_id = $2""",
        task_id, user_id, goal_id,
    )
    return result != "UPDATE 0"


async def reorder_task(task_id: int, user_id: int, new_order: int) -> bool:
    """Обновить sort_order задачи."""
    result = await get_pool().execute(
        """UPDATE tasks SET sort_order = $3, updated_at = NOW()
           WHERE id = $1 AND user_id = $2""",
        task_id, user_id, new_order,
    )
    return result != "UPDATE 0"


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


async def get_ideas_for_mindmap(user_id: int, limit: int = 200) -> list[dict]:
    """Идеи пользователя сгруппированные по проектам для Mind Map."""
    rows = await get_pool().fetch(
        """SELECT e.id, e.raw_text, e.timestamp, e.project_id,
                  COALESCE(p.name, 'Без проекта') AS project_name,
                  e.bot_source
           FROM events e
           LEFT JOIN projects p ON e.project_id = p.project_id
           WHERE e.user_id = $1
             AND e.event_type = 'idea'
           ORDER BY e.timestamp DESC
           LIMIT $2""",
        user_id, limit,
    )
    return [dict(r) for r in rows]


# ── Work Sessions ─────────────────────────────────────────────────

async def start_work_session(user_id: int, custom_time: "datetime | None" = None) -> dict:
    """Начать рабочую сессию (закрывает предыдущую незавершённую)."""
    # Закрываем незавершённую
    active = await get_active_work_session(user_id)
    if active:
        await stop_work_session(user_id)

    if custom_time:
        row = await get_pool().fetchrow(
            """INSERT INTO work_sessions (user_id, start_time)
               VALUES ($1, $2)
               RETURNING *""",
            user_id, custom_time,
        )
    else:
        row = await get_pool().fetchrow(
            """INSERT INTO work_sessions (user_id, start_time)
               VALUES ($1, NOW())
               RETURNING *""",
            user_id,
        )
    return dict(row)


async def stop_work_session(user_id: int, custom_time: "datetime | None" = None) -> dict | None:
    """Остановить активную рабочую сессию, посчитать длительность."""
    if custom_time:
        row = await get_pool().fetchrow(
            """UPDATE work_sessions
               SET end_time = $2,
                   duration_minutes = EXTRACT(EPOCH FROM ($2 - start_time))::int / 60
               WHERE user_id = $1 AND end_time IS NULL
               RETURNING *""",
            user_id, custom_time,
        )
    else:
        row = await get_pool().fetchrow(
            """UPDATE work_sessions
               SET end_time = NOW(),
                   duration_minutes = EXTRACT(EPOCH FROM (NOW() - start_time))::int / 60
               WHERE user_id = $1 AND end_time IS NULL
               RETURNING *""",
            user_id,
        )
    return dict(row) if row else None


async def get_active_work_session(user_id: int) -> dict | None:
    """Получить активную (незавершённую) сессию."""
    row = await get_pool().fetchrow(
        "SELECT * FROM work_sessions WHERE user_id = $1 AND end_time IS NULL ORDER BY start_time DESC LIMIT 1",
        user_id,
    )
    return dict(row) if row else None


async def get_work_sessions(user_id: int, days: int = 30) -> list[dict]:
    """Рабочие сессии за последние N дней."""
    rows = await get_pool().fetch(
        """SELECT * FROM work_sessions
           WHERE user_id = $1
             AND start_time >= NOW() - ($2 || ' days')::interval
             AND end_time IS NOT NULL
           ORDER BY start_time DESC""",
        user_id, str(days),
    )
    return [dict(r) for r in rows]


async def get_work_stats(user_id: int, days: int = 7) -> dict:
    """Статистика рабочего времени за N дней."""
    row = await get_pool().fetchrow(
        """SELECT
               COUNT(*) AS sessions,
               COALESCE(SUM(duration_minutes), 0) AS total_minutes,
               COALESCE(AVG(duration_minutes), 0) AS avg_minutes,
               COALESCE(MAX(duration_minutes), 0) AS max_minutes,
               COUNT(DISTINCT start_time::date) AS work_days
           FROM work_sessions
           WHERE user_id = $1
             AND start_time >= NOW() - ($2 || ' days')::interval
             AND end_time IS NOT NULL""",
        user_id, str(days),
    )
    return dict(row) if row else {
        "sessions": 0, "total_minutes": 0, "avg_minutes": 0,
        "max_minutes": 0, "work_days": 0,
    }


async def get_work_summary_text(user_id: int, days: int = 7) -> str:
    """Текстовая сводка рабочего времени для контекста других ботов."""
    stats = await get_work_stats(user_id, days)
    sessions = await get_work_sessions(user_id, days=days)

    if stats["sessions"] == 0:
        return ""

    total_h = int(stats["total_minutes"]) // 60
    total_m = int(stats["total_minutes"]) % 60
    avg_m = int(stats["avg_minutes"])

    lines = [
        f"⏱ РАБОЧЕЕ ВРЕМЯ (последние {days} дней):",
        f"  Сессий: {stats['sessions']}, рабочих дней: {stats['work_days']}",
        f"  Всего: {total_h}ч {total_m}мин, среднее: {avg_m} мин/сессия",
    ]

    # Последние 5 сессий
    for s in sessions[:5]:
        st = s["start_time"]
        dur = s.get("duration_minutes") or 0
        if hasattr(st, "astimezone"):
            from zoneinfo import ZoneInfo
            st = st.astimezone(ZoneInfo("Europe/Moscow")).strftime("%d.%m %H:%M")
        elif hasattr(st, "strftime"):
            st = st.strftime("%d.%m %H:%M")
        lines.append(f"  [{st}] {dur} мин")

    return "\n".join(lines)


# === Watch Tokens (Amazfit Balance 2 — push API) ===

async def get_watch_token(user_id: int) -> dict | None:
    """Получить API-ключ часов для пользователя."""
    row = await get_pool().fetchrow(
        "SELECT * FROM watch_tokens WHERE user_id = $1", user_id,
    )
    return dict(row) if row else None


async def get_watch_user_by_api_key(api_key: str) -> dict | None:
    """Найти пользователя по API-ключу часов (для push-эндпоинта)."""
    row = await get_pool().fetchrow(
        "SELECT * FROM watch_tokens WHERE api_key = $1 AND is_active = TRUE", api_key,
    )
    return dict(row) if row else None


async def save_watch_token(
    user_id: int,
    api_key: str,
    device_name: str = "Amazfit Balance 2",
    push_interval_min: int = 15,
) -> None:
    """Сохранить или обновить API-ключ часов."""
    await get_pool().execute(
        """INSERT INTO watch_tokens (user_id, api_key, device_name, push_interval_min, updated_at)
        VALUES ($1, $2, $3, $4, NOW())
        ON CONFLICT (user_id) DO UPDATE
        SET api_key = $2, device_name = $3, push_interval_min = $4, updated_at = NOW()""",
        user_id, api_key, device_name, push_interval_min,
    )


async def update_watch_last_push(user_id: int) -> None:
    """Обновить время последнего push от часов."""
    await get_pool().execute(
        "UPDATE watch_tokens SET last_push_at = NOW() WHERE user_id = $1", user_id,
    )


async def delete_watch_token(user_id: int) -> None:
    """Удалить API-ключ часов (отвязать)."""
    await get_pool().execute("DELETE FROM watch_tokens WHERE user_id = $1", user_id)


async def get_all_watch_users() -> list[dict]:
    """Все пользователи с подключёнными часами."""
    rows = await get_pool().fetch(
        "SELECT * FROM watch_tokens WHERE is_active = TRUE ORDER BY user_id",
    )
    return [dict(r) for r in rows]


# === Webapp aggregate queries ===


async def get_projects_with_stats(user_id: int) -> list[dict]:
    """Проекты с кол-вом задач и финансовым балансом."""
    rows = await get_pool().fetch(
        """SELECT p.*,
               COALESCE(t.active_count, 0)::int AS active_tasks,
               COALESCE(t.done_count, 0)::int   AS done_tasks,
               COALESCE(f.total_income, 0)       AS total_income,
               COALESCE(f.total_expense, 0)      AS total_expense
           FROM projects p
           LEFT JOIN LATERAL (
               SELECT COUNT(*) FILTER (WHERE NOT is_done) AS active_count,
                      COUNT(*) FILTER (WHERE is_done)     AS done_count
               FROM tasks WHERE project_id = p.project_id AND user_id = $1
           ) t ON TRUE
           LEFT JOIN LATERAL (
               SELECT
                   COALESCE(SUM(amount) FILTER (WHERE transaction_type = 'income'), 0)  AS total_income,
                   COALESCE(SUM(amount) FILTER (WHERE transaction_type = 'expense'), 0) AS total_expense
               FROM finances WHERE project_id = p.project_id
           ) f ON TRUE
           WHERE p.status = 'active'
             AND (p.owner_id = $1 OR $1 = ANY(p.collaborators))
           ORDER BY t.active_count DESC NULLS LAST, p.created_at""",
        user_id,
    )
    return [dict(r) for r in rows]


async def get_overdue_tasks(user_id: int) -> list[dict]:
    """Просроченные незавершённые задачи."""
    rows = await get_pool().fetch(
        """SELECT t.*, p.name AS project_name
           FROM tasks t
           LEFT JOIN projects p ON t.project_id = p.project_id
           WHERE t.user_id = $1 AND t.is_done = FALSE
             AND t.due_date < CURRENT_DATE
           ORDER BY t.due_date, t.due_time NULLS LAST""",
        user_id,
    )
    return [dict(r) for r in rows]


async def get_today_tasks_ext(user_id: int) -> list[dict]:
    """Задачи на сегодня с именем проекта."""
    rows = await get_pool().fetch(
        """SELECT t.*, p.name AS project_name
           FROM tasks t
           LEFT JOIN projects p ON t.project_id = p.project_id
           WHERE t.user_id = $1
             AND t.due_date = CURRENT_DATE
           ORDER BY t.is_done, t.due_time NULLS LAST, t.priority""",
        user_id,
    )
    return [dict(r) for r in rows]


async def get_tomorrow_tasks(user_id: int) -> list[dict]:
    """Задачи на завтра."""
    rows = await get_pool().fetch(
        """SELECT t.*, p.name AS project_name
           FROM tasks t
           LEFT JOIN projects p ON t.project_id = p.project_id
           WHERE t.user_id = $1
             AND t.due_date = CURRENT_DATE + 1
           ORDER BY t.due_time NULLS LAST, t.priority""",
        user_id,
    )
    return [dict(r) for r in rows]


async def get_goals_with_tasks(user_id: int) -> list[dict]:
    """Активные цели с кол-вом привязанных задач."""
    rows = await get_pool().fetch(
        """SELECT g.*,
               COALESCE(t.total_count, 0)::int AS total_tasks,
               COALESCE(t.done_count, 0)::int  AS done_tasks
           FROM goals g
           LEFT JOIN LATERAL (
               SELECT COUNT(*)                          AS total_count,
                      COUNT(*) FILTER (WHERE is_done)   AS done_count
               FROM tasks WHERE goal_id = g.id AND user_id = $1
           ) t ON TRUE
           WHERE g.user_id = $1 AND g.status = 'active'
           ORDER BY g.created_at""",
        user_id,
    )
    return [dict(r) for r in rows]


async def get_monthly_finance_summary(user_id: int) -> dict:
    """Сводка доходов/расходов за текущий месяц."""
    row = await get_pool().fetchrow(
        """SELECT
               COALESCE(SUM(amount) FILTER (WHERE transaction_type = 'income'), 0)  AS income,
               COALESCE(SUM(amount) FILTER (WHERE transaction_type = 'expense'), 0) AS expense
           FROM finances
           WHERE user_id = $1
             AND date_trunc('month', timestamp) = date_trunc('month', CURRENT_DATE)""",
        user_id,
    )
    return dict(row) if row else {"income": 0, "expense": 0}


async def get_category_breakdown(user_id: int) -> list[dict]:
    """Расходы по категориям за текущий месяц."""
    rows = await get_pool().fetch(
        """SELECT category, SUM(amount)::numeric(12,2) AS total
           FROM finances
           WHERE user_id = $1 AND transaction_type = 'expense'
             AND date_trunc('month', timestamp) = date_trunc('month', CURRENT_DATE)
           GROUP BY category
           ORDER BY total DESC""",
        user_id,
    )
    return [dict(r) for r in rows]


async def get_today_watch_metrics(user_id: int) -> list[dict]:
    """Получить сегодняшние метрики с часов."""
    rows = await get_pool().fetch(
        """SELECT json_data, timestamp, raw_text FROM events
        WHERE user_id = $1
          AND event_type = 'watch_metrics'
          AND bot_source = 'health'
          AND timestamp >= CURRENT_DATE
        ORDER BY timestamp DESC""",
        user_id,
    )
    return [dict(r) for r in rows]


async def get_project_tasks(user_id: int, project_id: int) -> list[dict]:
    """Все задачи проекта (невыполненные сначала)."""
    rows = await get_pool().fetch(
        """SELECT * FROM tasks
           WHERE user_id = $1 AND project_id = $2
           ORDER BY is_done, due_date NULLS LAST, due_time NULLS LAST""",
        user_id, project_id,
    )
    return [dict(r) for r in rows]
