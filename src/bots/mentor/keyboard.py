"""Reply- и Inline-клавиатуры бота Mentor."""

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
    DISCUSSION = "discussion"
    ANALYTICS = "analytics"
    PROJECTS = "projects"
    ASK = "ask"


def main_keyboard() -> ReplyKeyboardMarkup:
    rows = [
        [KeyboardButton(text="💡 Идея"), KeyboardButton(text="🎙 Обсуждение")],
        [KeyboardButton(text="📊 Аналитика"), KeyboardButton(text="📁 Проекты")],
        [KeyboardButton(text="❓ Спросить")],
    ]
    from src.bots.hub.keyboard import is_unified, MENU_BUTTON_TEXT
    if is_unified():
        rows.append([KeyboardButton(text=MENU_BUTTON_TEXT)])
    return ReplyKeyboardMarkup(keyboard=rows, resize_keyboard=True)


def projects_inline(projects: list[dict], action: str = "select") -> InlineKeyboardMarkup:
    """Инлайн-кнопки с проектами.

    action: "select" — привязка идеи/обсуждения,
            "analytics" — финансовая стратегия,
            "report" — отчёт за период.
    """
    buttons = []
    for p in projects:
        buttons.append([
            InlineKeyboardButton(
                text=p["name"],
                callback_data=f"mnt:{action}:{p['project_id']}",
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
