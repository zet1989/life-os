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
    AI_PANEL = "ai_panel"
    PROMPTS = "prompts"
    SET_PROMPT = "set_prompt"  # ожидаем текст промпта для выбранного проекта


# user_id → текущий режим
_user_modes: dict[int, Mode] = {}
_pending_prompt_project: dict[int, int] = {}  # user_id → project_id для SET_PROMPT


def get_user_mode(user_id: int) -> Mode:
    return _user_modes.get(user_id, Mode.TALK)


def set_user_mode(user_id: int, mode: Mode) -> None:
    _user_modes[user_id] = mode


def set_pending_prompt_project(user_id: int, project_id: int) -> None:
    _pending_prompt_project[user_id] = project_id


def pop_pending_prompt_project(user_id: int) -> int | None:
    return _pending_prompt_project.pop(user_id, None)


def main_keyboard() -> ReplyKeyboardMarkup:
    """Главная клавиатура Master-бота."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Дневник"), KeyboardButton(text="🎯 Цели и Мечты")],
            [KeyboardButton(text="⚙️ Проекты"), KeyboardButton(text="📊 Сводный отчёт")],
            [KeyboardButton(text="💰 Финансовая панорама"), KeyboardButton(text="🤖 AI Панель")],
            [KeyboardButton(text="📋 Промпты"), KeyboardButton(text="➕ Цель"), KeyboardButton(text="📊 Графики")],
            [KeyboardButton(text="ℹ️ Статус")],
        ],
        resize_keyboard=True,
    )
