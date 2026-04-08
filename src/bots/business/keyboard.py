"""Reply- и Inline-клавиатуры бота Business."""

import contextvars
from enum import StrEnum

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

_user_modes: dict[int, "Mode"] = {}

# Временное хранилище pending-текста для привязки к проекту
_pending_text: dict[int, str] = {}

# ContextVar — user_id текущего запроса (ставится middleware в handlers.py)
_kb_user: contextvars.ContextVar[int] = contextvars.ContextVar("kb_user", default=0)


def set_keyboard_user(user_id: int) -> None:
    """Установить user_id для текущего asyncio-контекста (middleware)."""
    _kb_user.set(user_id)


class Mode(StrEnum):
    IDEA = "idea"
    TASK = "task"
    PROJECTS = "projects"
    REPORT = "report"
    ADD_PROJECT = "add_project"
    TIMER = "timer"
    TIMER_SET_START = "timer_set_start"
    TIMER_SET_STOP = "timer_set_stop"


def main_keyboard() -> ReplyKeyboardMarkup:
    from src.config import settings

    user_id = _kb_user.get()
    is_admin = (user_id == 0) or (user_id == settings.admin_user_id)

    rows = [
        [KeyboardButton(text="💡 Идея"), KeyboardButton(text="📋 Задача")],
        [KeyboardButton(text="📁 Проекты"), KeyboardButton(text="📊 Отчёт")],
    ]
    if is_admin:
        rows.append([KeyboardButton(text="⏱ Таймер"), KeyboardButton(text="➕ Новый проект")])
    else:
        rows.append([KeyboardButton(text="➕ Новый проект")])
    from src.bots.hub.keyboard import is_unified, MENU_BUTTON_TEXT
    if is_unified():
        rows.append([KeyboardButton(text=MENU_BUTTON_TEXT)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def projects_inline(projects: list[dict], action: str = "select") -> InlineKeyboardMarkup:
    """Инлайн-кнопки с проектами для выбора.

    action: "select" — привязка идеи/задачи,
            "report" — финансовый отчёт,
            "archive" — архивировать проект.
    """
    buttons = []
    for p in projects:
        buttons.append([
            InlineKeyboardButton(
                text=p["name"],
                callback_data=f"biz:{action}:{p['project_id']}",
            )
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def get_user_mode(user_id: int) -> Mode:
    return _user_modes.get(user_id, Mode.IDEA)


def set_user_mode(user_id: int, mode: Mode) -> None:
    _user_modes[user_id] = mode


def set_pending(user_id: int, text: str) -> None:
    _pending_text[user_id] = text


def pop_pending(user_id: int) -> str | None:
    return _pending_text.pop(user_id, None)
