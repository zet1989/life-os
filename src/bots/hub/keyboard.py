"""Главное меню и управление секциями единого бота."""

from enum import StrEnum

from aiogram.types import KeyboardButton, ReplyKeyboardMarkup, WebAppInfo

from src.config import settings


class Section(StrEnum):
    """Секции единого бота (соответствуют прежним отдельным ботам)."""
    HEALTH = "health"
    ASSETS = "assets"
    BUSINESS = "business"
    PARTNER = "partner"
    MENTOR = "mentor"
    FAMILY = "family"
    PSYCHOLOGY = "psychology"
    MASTER = "master"


# Метки секций для кнопок
SECTION_LABELS: dict[Section, str] = {
    Section.HEALTH: "🏥 Здоровье",
    Section.ASSETS: "🏠 Дом и Авто",
    Section.BUSINESS: "💼 Бизнес",
    Section.PARTNER: "🤝 Партнёр",
    Section.MENTOR: "📈 Ментор",
    Section.FAMILY: "👨‍👩‍👧 Семья",
    Section.PSYCHOLOGY: "🧠 Психолог",
    Section.MASTER: "🎛 Мастер",
}

# Обратный маппинг: текст кнопки → секция
LABEL_TO_SECTION: dict[str, Section] = {v: k for k, v in SECTION_LABELS.items()}

# Кнопка возврата в главное меню (добавляется в каждую секционную клавиатуру)
MENU_BUTTON_TEXT = "🏠 Меню"

# Флаг единого бота (включается в main.py)
_unified_mode = False


def is_unified() -> bool:
    """Работает ли бот в unified-режиме."""
    return _unified_mode


def set_unified_mode() -> None:
    """Включить unified-режим (добавляет кнопку Меню в клавиатуры)."""
    global _unified_mode
    _unified_mode = True


# In-memory: текущая секция пользователя (None = главное меню)
_user_sections: dict[int, Section | None] = {}


def get_current_section(user_id: int) -> Section | None:
    """Текущая секция пользователя (None = главное меню)."""
    return _user_sections.get(user_id)


def set_current_section(user_id: int, section: Section | None) -> None:
    """Установить текущую секцию."""
    _user_sections[user_id] = section


def main_menu_keyboard(allowed_sections: list[Section] | None = None) -> ReplyKeyboardMarkup:
    """Главное меню с секциями.

    allowed_sections: если задано - показать только разрешённые.
    Если None - показать все.
    """
    sections = allowed_sections or list(Section)
    buttons: list[list[KeyboardButton]] = []

    # По 2 кнопки в ряд
    row: list[KeyboardButton] = []
    for section in sections:
        row.append(KeyboardButton(text=SECTION_LABELS[section]))
        if len(row) == 2:
            buttons.append(row)
            row = []
    if row:
        buttons.append(row)

    # Кнопка Web App (если webhook_host задан — есть куда открывать)
    if settings.webhook_host:
        webapp_url = f"{settings.webhook_host}/webapp"
        buttons.append([KeyboardButton(text="📊 Дашборд", web_app=WebAppInfo(url=webapp_url))])

    return ReplyKeyboardMarkup(keyboard=buttons, resize_keyboard=True)


def get_allowed_sections(user: dict) -> list[Section]:
    """Определить разрешённые секции по роли и permissions."""
    role = user.get("role", "")
    if role == "admin":
        return list(Section)

    permissions = user.get("permissions") or {}
    allowed_bots: list[str] = permissions.get("bots", [])

    if not allowed_bots:
        return list(Section)  # обратная совместимость

    return [s for s in Section if s.value in allowed_bots]
