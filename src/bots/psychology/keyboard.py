"""Клавиатура бота Psychology — дневник, привычки, ретроспектива."""

from enum import Enum

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    ReplyKeyboardMarkup,
    KeyboardButton,
)


class Mode(str, Enum):
    DIARY = "diary"
    HABITS = "habits"
    RETRO = "retro"
    MOOD = "mood"


# user_id → текущий режим
_user_modes: dict[int, Mode] = {}


def get_user_mode(user_id: int) -> Mode:
    return _user_modes.get(user_id, Mode.DIARY)


def set_user_mode(user_id: int, mode: Mode) -> None:
    _user_modes[user_id] = mode


def main_keyboard() -> ReplyKeyboardMarkup:
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📝 Дневник"), KeyboardButton(text="🎙 Голос")],
            [KeyboardButton(text="✅ Привычки"), KeyboardButton(text="😊 Настроение")],
            [KeyboardButton(text="🔮 Ретроспектива")],
        ],
        resize_keyboard=True,
    )


def habits_inline(habits: list[dict]) -> InlineKeyboardMarkup:
    """Inline-кнопки для списка привычек: отметить успех / срыв."""
    buttons = []
    for h in habits:
        goal_id = h["id"]
        title = h.get("title", "Привычка")
        buttons.append([
            InlineKeyboardButton(
                text=f"✅ {title}",
                callback_data=f"psy:ok:{goal_id}",
            ),
            InlineKeyboardButton(
                text=f"❌ {title}",
                callback_data=f"psy:fail:{goal_id}",
            ),
        ])
    return InlineKeyboardMarkup(inline_keyboard=buttons)


def mood_inline() -> InlineKeyboardMarkup:
    """Inline-кнопки для оценки настроения 1-5."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="😢 1", callback_data="psy:mood:1"),
                InlineKeyboardButton(text="😔 2", callback_data="psy:mood:2"),
                InlineKeyboardButton(text="😐 3", callback_data="psy:mood:3"),
                InlineKeyboardButton(text="😊 4", callback_data="psy:mood:4"),
                InlineKeyboardButton(text="🌟 5", callback_data="psy:mood:5"),
            ]
        ]
    )
