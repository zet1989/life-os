"""Клавиатура бота Master Intelligence — главный пульт Life OS."""

from enum import Enum

from aiogram.types import (
    ReplyKeyboardMarkup,
    KeyboardButton,
)


class Mode(str, Enum):
    DIARY = "diary"
    GOALS = "goals"
    PROJECTS = "projects"
    REPORT = "report"
    PANORAMA = "panorama"
    TALK = "talk"


# user_id → текущий режим
_user_modes: dict[int, Mode] = {}


def get_user_mode(user_id: int) -> Mode:
    return _user_modes.get(user_id, Mode.TALK)


def set_user_mode(user_id: int, mode: Mode) -> None:
    _user_modes[user_id] = mode


def main_keyboard() -> ReplyKeyboardMarkup:
    """Главная клавиатура Master-бота."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Дневник"), KeyboardButton(text="🎯 Цели и Мечты")],
            [KeyboardButton(text="⚙️ Проекты"), KeyboardButton(text="📊 Сводный отчёт")],
            [KeyboardButton(text="💰 Финансовая панорама")],
            [KeyboardButton(text="➕ Цель"), KeyboardButton(text="📊 Графики"), KeyboardButton(text="ℹ️ Статус")],
        ],
        resize_keyboard=True,
    )
