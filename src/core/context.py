"""Управление контекстом диалога для LLM.

Sliding window: последние N сообщений из таблицы conversations.
Формирует messages[] для отправки в LLM.
"""

from src.db.queries import get_recent_messages, get_today_messages, save_message, get_user


async def build_messages(
    user_id: int,
    bot_source: str,
    system_prompt: str,
    user_text: str,
    limit: int = 20,
) -> list[dict[str, str]]:
    """Собрать messages[] для LLM: system + история + текущее сообщение.

    1. System prompt (базовый + system_prompt_overrides из БД).
    2. Последние N сообщений из conversations.
    3. Текущее сообщение пользователя.
    """
    # Подгружаем динамические настройки юзера
    user = await get_user(user_id)
    overrides = (user or {}).get("system_prompt_overrides") or ""

    full_system = system_prompt
    if overrides:
        full_system += f"\n\nДополнительные настройки пользователя:\n{overrides}"

    messages: list[dict[str, str]] = [{"role": "system", "content": full_system}]

    # История диалога
    history = await get_recent_messages(user_id, bot_source, limit=limit)
    messages.extend(history)

    # Текущее сообщение
    messages.append({"role": "user", "content": user_text})

    # Сохраняем сообщение юзера в историю
    await save_message(user_id, bot_source, "user", user_text)

    return messages


async def build_messages_today(
    user_id: int,
    bot_source: str,
    system_prompt: str,
    user_text: str,
    limit: int = 20,
) -> list[dict[str, str]]:
    """Как build_messages, но история ТОЛЬКО за сегодня (MSK).

    Используется для health бота, чтобы не тащить вчерашние итоги калорий.
    """
    user = await get_user(user_id)
    overrides = (user or {}).get("system_prompt_overrides") or ""

    full_system = system_prompt
    if overrides:
        full_system += f"\n\nДополнительные настройки пользователя:\n{overrides}"

    messages: list[dict[str, str]] = [{"role": "system", "content": full_system}]

    history = await get_today_messages(user_id, bot_source, limit=limit)
    messages.extend(history)

    messages.append({"role": "user", "content": user_text})

    await save_message(user_id, bot_source, "user", user_text)

    return messages


async def save_assistant_reply(
    user_id: int,
    bot_source: str,
    content: str,
    tokens_used: int | None = None,
) -> None:
    """Сохранить ответ бота в историю диалога."""
    await save_message(user_id, bot_source, "assistant", content, tokens_used)
