"""Reply- и Inline-клавиатуры бота Business."""

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


class Mode(StrEnum):
    IDEA = "idea"
    TASK = "task"
    PROJECTS = "projects"
    REPORT = "report"
    ADD_PROJECT = "add_project"


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="💡 Идея"), KeyboardButton(text="📋 Задача")],
            [KeyboardButton(text="📁 Проекты"), KeyboardButton(text="📊 Отчёт")],
            [KeyboardButton(text="➕ Новый проект")],
        ],
        resize_keyboard=True,
    )


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
