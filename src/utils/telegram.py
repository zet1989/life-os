"""Безопасная отправка сообщений в Telegram.

LLM может вернуть невалидный HTML (например, <название>).
safe_answer / safe_edit ловят TelegramBadRequest и повторяют без parse_mode.
"""

import structlog
from aiogram import types
from aiogram.exceptions import TelegramBadRequest

logger = structlog.get_logger()


async def safe_answer(message: types.Message, text: str, **kwargs) -> types.Message:
    """message.answer с fallback на plain text при невалидном HTML."""
    try:
        return await message.answer(text, **kwargs)
    except TelegramBadRequest as e:
        if "can't parse entities" in str(e):
            logger.warning("html_parse_fallback", error=str(e)[:100])
            return await message.answer(text, parse_mode=None, **kwargs)
        raise


async def safe_edit(message: types.Message, text: str, **kwargs) -> types.Message:
    """message.edit_text с fallback на plain text при невалидном HTML."""
    try:
        return await message.edit_text(text, **kwargs)
    except TelegramBadRequest as e:
        if "can't parse entities" in str(e):
            logger.warning("html_parse_fallback_edit", error=str(e)[:100])
            return await message.edit_text(text, parse_mode=None, **kwargs)
        raise
