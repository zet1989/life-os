"""Хэндлеры Hub — /start, главное меню, переключение секций."""

import structlog
from aiogram import F, Router
from aiogram.filters import BaseFilter, Command
from aiogram.types import Message

from src.bots.hub.keyboard import (
    LABEL_TO_SECTION,
    MENU_BUTTON_TEXT,
    Section,
    get_allowed_sections,
    get_current_section,
    main_menu_keyboard,
    set_current_section,
)
from src.utils.telegram import safe_answer

logger = structlog.get_logger()

router = Router(name="hub")


class _NoSectionFilter(BaseFilter):
    """Пропускает только если пользователь НЕ в секции (в главном меню)."""

    async def __call__(self, event: Message, **kwargs) -> bool:
        if event.from_user:
            return get_current_section(event.from_user.id) is None
        return False


# Импорт клавиатур секций (ленивый, чтобы не циклить импорты)
_SECTION_KEYBOARDS = {}


def _get_section_keyboard(section: Section):
    """Получить клавиатуру секции с кнопкой 🏠 Меню."""
    if section not in _SECTION_KEYBOARDS:
        from aiogram.types import KeyboardButton

        if section == Section.HEALTH:
            from src.bots.health.keyboard import main_keyboard
        elif section == Section.ASSETS:
            from src.bots.assets.keyboard import main_keyboard
        elif section == Section.BUSINESS:
            from src.bots.business.keyboard import main_keyboard
        elif section == Section.PARTNER:
            from src.bots.partner.keyboard import main_keyboard
        elif section == Section.MENTOR:
            from src.bots.mentor.keyboard import main_keyboard
        elif section == Section.FAMILY:
            from src.bots.family.keyboard import main_keyboard
        elif section == Section.PSYCHOLOGY:
            from src.bots.psychology.keyboard import main_keyboard
        elif section == Section.MASTER:
            from src.bots.master.keyboard import main_keyboard
        else:
            return None

        kb = main_keyboard()
        # Добавляем кнопку "🏠 Меню" в последний ряд
        kb.keyboard.append([KeyboardButton(text=MENU_BUTTON_TEXT)])
        _SECTION_KEYBOARDS[section] = kb

    return _SECTION_KEYBOARDS[section]


# --- /start ---

@router.message(Command("start"))
async def cmd_start(message: Message, db_user: dict) -> None:
    """Приветствие и главное меню."""
    allowed = get_allowed_sections(db_user)
    set_current_section(message.from_user.id, None)

    name = message.from_user.first_name or "Пользователь"
    await safe_answer(
        message,
        f"👋 Привет, {name}!\n\n"
        "Я — <b>Life OS</b>, твой персональный ассистент.\n"
        "Выбери раздел:",
        reply_markup=main_menu_keyboard(allowed),
    )


# --- 🏠 Меню (возврат в главное меню) ---

@router.message(F.text == MENU_BUTTON_TEXT)
async def cmd_menu(message: Message, db_user: dict) -> None:
    """Возврат в главное меню из любой секции."""
    allowed = get_allowed_sections(db_user)
    set_current_section(message.from_user.id, None)

    await safe_answer(
        message,
        "🏠 <b>Главное меню</b>\n\nВыбери раздел:",
        reply_markup=main_menu_keyboard(allowed),
    )


# --- Переключение секции ---

@router.message(F.text.in_(LABEL_TO_SECTION.keys()))
async def switch_section(message: Message, db_user: dict) -> None:
    """Переключение в выбранную секцию."""
    section = LABEL_TO_SECTION[message.text]
    user_id = message.from_user.id

    # Проверка доступа
    allowed = get_allowed_sections(db_user)
    if section not in allowed:
        await safe_answer(message, "🔒 У вас нет доступа к этому разделу.")
        return

    set_current_section(user_id, section)

    from src.bots.hub.keyboard import SECTION_LABELS
    label = SECTION_LABELS[section]

    kb = _get_section_keyboard(section)
    await safe_answer(
        message,
        f"{label}\n\nВыберите действие:",
        reply_markup=kb,
    )
    logger.info("section_switched", user_id=user_id, section=section.value)


# --- Catch-all: текст без выбранной секции ---

@router.message(_NoSectionFilter())
async def no_section_fallback(message: Message, db_user: dict) -> None:
    """Пользователь пишет текст, но не выбрал секцию."""
    allowed = get_allowed_sections(db_user)
    await safe_answer(
        message,
        "👆 Сначала выберите раздел из меню:",
        reply_markup=main_menu_keyboard(allowed),
    )
