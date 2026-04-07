"""Безопасная отправка сообщений в Telegram.

LLM может вернуть невалидный HTML (например, <название>).
safe_answer / safe_edit / safe_send ловят TelegramBadRequest и повторяют без parse_mode.
"""

import structlog
from aiogram import Bot, types
from aiogram.exceptions import TelegramBadRequest
from aiogram.types import FSInputFile

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


async def safe_send(bot: Bot, chat_id: int, text: str, **kwargs) -> types.Message:
    """bot.send_message с fallback на plain text при невалидном HTML."""
    try:
        return await bot.send_message(chat_id, text, **kwargs)
    except TelegramBadRequest as e:
        if "can't parse entities" in str(e):
            logger.warning("html_parse_fallback_send", error=str(e)[:100])
            return await bot.send_message(chat_id, text, parse_mode=None, **kwargs)
        raise


async def safe_answer_voice(message: types.Message, text: str, user_id: int, **kwargs) -> types.Message:
    """Ответить текстом + голосом (если voice mode включён)."""
    from src.ai.tts import is_voice_mode, text_to_voice

    msg = await safe_answer(message, text, **kwargs)

    if is_voice_mode(user_id):
        voice_path = await text_to_voice(text)
        if voice_path:
            try:
                await message.answer_voice(FSInputFile(str(voice_path)))
            except Exception:
                logger.exception("voice_send_failed")
            finally:
                voice_path.unlink(missing_ok=True)

    return msg
