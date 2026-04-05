"""ACL middleware — проверка прав доступа.

Цепочка: user_id → есть в users? → is_active? → есть права на этого бота?
Незнакомцам бот не отвечает (молчит).
"""

from typing import Any, Awaitable, Callable

from aiogram import BaseMiddleware
from aiogram.types import TelegramObject, Update
import structlog

from src.db.queries import get_user

logger = structlog.get_logger()


class ACLMiddleware(BaseMiddleware):
    """Пропускает только зарегистрированных и активных пользователей."""

    def __init__(self, bot_name: str) -> None:
        self.bot_name = bot_name

    async def __call__(
        self,
        handler: Callable[[TelegramObject, dict[str, Any]], Awaitable[Any]],
        event: TelegramObject,
        data: dict[str, Any],
    ) -> Any:
        # Извлекаем user_id из update
        update: Update = event  # type: ignore[assignment]
        user_id: int | None = None

        if update.message and update.message.from_user:
            user_id = update.message.from_user.id
        elif update.callback_query and update.callback_query.from_user:
            user_id = update.callback_query.from_user.id

        if user_id is None:
            return  # нет юзера — молчим

        # Проверяем в БД
        user = await get_user(user_id)
        if user is None or not user.get("is_active", False):
            logger.warning("acl_denied", user_id=user_id, reason="unknown_or_inactive")
            return  # молчим

        # Проверяем доступ к конкретному боту
        permissions = user.get("permissions") or {}
        allowed_bots: list[str] = permissions.get("bots", [])

        # admin видит всё; если bots не заданы — тоже всё (обратная совместимость)
        if user.get("role") != "admin" and allowed_bots and self.bot_name not in allowed_bots:
            logger.warning("acl_denied", user_id=user_id, bot=self.bot_name, reason="no_bot_access")
            return  # молчим

        # Прокидываем данные юзера в хэндлер
        data["db_user"] = user
        return await handler(event, data)
