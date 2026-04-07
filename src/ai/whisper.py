"""Транскрипция голосовых сообщений через локальный faster-whisper."""

import asyncio
import tempfile
from pathlib import Path

import structlog
from aiogram import Bot
from aiogram.types import Voice
from faster_whisper import WhisperModel

from src.utils.cost_tracker import log_api_cost

logger = structlog.get_logger()

_model: WhisperModel | None = None


def _get_model() -> WhisperModel:
    global _model
    if _model is None:
        logger.info("whisper_loading_model", model="medium")
        _model = WhisperModel("medium", device="cpu", compute_type="int8")
        logger.info("whisper_model_ready")
    return _model


async def transcribe_voice(
    bot: Bot,
    voice: Voice,
    user_id: int | None = None,
    bot_source: str | None = None,
) -> str:
    """Скачать voice-сообщение из Telegram и транскрибировать локально.

    Возвращает текст транскрипции.
    """
    file = await bot.get_file(voice.file_id)
    assert file.file_path is not None

    with tempfile.TemporaryDirectory() as tmp:
        local_path = Path(tmp) / "voice.ogg"
        await bot.download_file(file.file_path, destination=local_path)

        # Запускаем в тредпуле чтобы не блокировать event loop
        loop = asyncio.get_running_loop()
        text = await loop.run_in_executor(None, _transcribe_sync, str(local_path))

    duration = voice.duration or 0
    await log_api_cost(
        user_id=user_id,
        bot_source=bot_source,
        model="whisper-large-v3-local",
        tokens_in=duration,
        tokens_out=0,
        task_type="transcription",
    )

    logger.info("whisper_transcribed", duration=duration, chars=len(text))
    return text


async def summarize_long_voice(
    text: str,
    duration: int,
    user_id: int | None = None,
    bot_source: str | None = None,
) -> str | None:
    """Саммаризация длинного голосового сообщения (>5 мин) через LLM.

    Возвращает краткое содержание или None если сообщение короткое.
    """
    if duration < 300:
        return None

    from src.ai.router import chat

    minutes = duration // 60
    messages = [
        {
            "role": "system",
            "content": (
                "Ты — AI-ассистент. Тебе дан текст транскрипции длинного голосового сообщения. "
                "Напиши краткое содержание (3-5 предложений), сохранив ключевые мысли, "
                "факты, цифры и решения. Не добавляй ничего от себя."
            ),
        },
        {
            "role": "user",
            "content": f"Транскрипция голосового ({minutes} мин):\n\n{text}",
        },
    ]

    summary = await chat(
        messages=messages,
        task_type="voice_summary",
        user_id=user_id,
        bot_source=bot_source,
    )

    logger.info("voice_summarized", duration=duration, summary_len=len(summary))
    return summary


def _transcribe_sync(audio_path: str) -> str:
    """Синхронная транскрипция (вызывается в executor)."""
    model = _get_model()
    segments, _info = model.transcribe(audio_path, language="ru", beam_size=1)
    return " ".join(seg.text.strip() for seg in segments).strip()
