"""Инлайн- и Reply-клавиатуры бота Assets."""

from enum import StrEnum

from aiogram.types import (
    InlineKeyboardButton,
    InlineKeyboardMarkup,
    KeyboardButton,
    ReplyKeyboardMarkup,
)

# In-memory store режимов (per-user)
_user_modes: dict[int, "Mode"] = {}


class Mode(StrEnum):
    MEASUREMENT = "measurement"   # замер
    RECEIPT = "receipt"           # чек стройматериалов
    MAINTENANCE = "maintenance"  # ТО / бортжурнал
    PART = "part"                # запчасть / заказ-наряд
    QUESTION = "question"        # RAG-запрос
    BLUEPRINT = "blueprint"      # план/чертёж дома


def main_keyboard() -> ReplyKeyboardMarkup:
    """Основная Reply-клавиатура бота Assets."""
    return ReplyKeyboardMarkup(
        keyboard=[
            [KeyboardButton(text="📐 Замер"), KeyboardButton(text="🧾 Чек")],
            [KeyboardButton(text="🔧 ТО"), KeyboardButton(text="⚙️ Запчасть")],
            [KeyboardButton(text="🗓 План дома"), KeyboardButton(text="❓ Спросить")],
        ],
        resize_keyboard=True,
    )


def inline_category() -> InlineKeyboardMarkup:
    """Инлайн-кнопки выбора категории (для быстрого ввода без Reply)."""
    return InlineKeyboardMarkup(
        inline_keyboard=[
            [
                InlineKeyboardButton(text="📐 Замер", callback_data="asset_mode:measurement"),
                InlineKeyboardButton(text="🧾 Чек", callback_data="asset_mode:receipt"),
            ],
            [
                InlineKeyboardButton(text="🔧 ТО", callback_data="asset_mode:maintenance"),
                InlineKeyboardButton(text="⚙️ Запчасть", callback_data="asset_mode:part"),
            ],
        ],
    )


def get_user_mode(user_id: int) -> Mode:
    return _user_modes.get(user_id, Mode.QUESTION)


def set_user_mode(user_id: int, mode: Mode) -> None:
    _user_modes[user_id] = mode
