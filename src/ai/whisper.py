"""Транскрипция голосовых сообщений через OpenAI Whisper API."""

import tempfile
from pathlib import Path

import structlog
from aiogram import Bot
from aiogram.types import Voice
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import settings
from src.utils.cost_tracker import log_api_cost

logger = structlog.get_logger()

_openai_client: AsyncOpenAI | None = None


def _get_openai() -> AsyncOpenAI:
    global _openai_client
    if _openai_client is None:
        _openai_client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _openai_client


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
async def transcribe_voice(
    bot: Bot,
    voice: Voice,
    user_id: int | None = None,
    bot_source: str | None = None,
) -> str:
    """Скачать voice-сообщение из Telegram и транскрибировать через Whisper.

    Возвращает текст транскрипции.
    """
    # Скачиваем .ogg файл во временную директорию
    file = await bot.get_file(voice.file_id)
    assert file.file_path is not None

    with tempfile.TemporaryDirectory() as tmp:
        local_path = Path(tmp) / "voice.ogg"
        await bot.download_file(file.file_path, destination=local_path)

        # Отправляем в Whisper API
        with open(local_path, "rb") as audio_file:
            transcription = await _get_openai().audio.transcriptions.create(
                model="whisper-1",
                file=audio_file,
                language="ru",
            )

    text = transcription.text.strip()

    # Логируем расход (Whisper считает по длительности, ~tokens_in = секунды)
    duration = voice.duration or 0
    await log_api_cost(
        user_id=user_id,
        bot_source=bot_source,
        model="whisper-1",
        tokens_in=duration,
        tokens_out=0,
        task_type="transcription",
    )

    logger.info("whisper_transcribed", duration=duration, chars=len(text))
    return text
