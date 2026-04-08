"""Фильтр секции — пропускает хэндлер только если пользователь в нужной секции."""

from aiogram.filters import BaseFilter
from aiogram.types import CallbackQuery, Message

from src.bots.hub.keyboard import get_current_section


class SectionFilter(BaseFilter):
    """Пропускает события только для пользователей в указанной секции.

    Используется на уровне роутера:
        router.message.filter(SectionFilter("health"))
        router.callback_query.filter(SectionFilter("health"))
    """

    def __init__(self, section: str) -> None:
        self.section = section

    async def __call__(self, event: Message | CallbackQuery, **kwargs) -> bool:
        user_id: int | None = None

        if isinstance(event, Message) and event.from_user:
            user_id = event.from_user.id
        elif isinstance(event, CallbackQuery) and event.from_user:
            user_id = event.from_user.id

        if user_id is None:
            return False

        current = get_current_section(user_id)
        return current is not None and current.value == self.section
