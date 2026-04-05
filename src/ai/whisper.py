"""Транскрипция голосовых сообщений через Groq Whisper API."""

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

_groq_client: AsyncOpenAI | None = None


def _get_groq() -> AsyncOpenAI:
    global _groq_client
    if _groq_client is None:
        _groq_client = AsyncOpenAI(
            api_key=settings.groq_api_key,
            base_url="https://api.groq.com/openai/v1",
        )
    return _groq_client


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
async def transcribe_voice(
    bot: Bot,
    voice: Voice,
    user_id: int | None = None,
    bot_source: str | None = None,
) -> str:
    """Скачать voice-сообщение из Telegram и транскрибировать через Groq Whisper.

    Возвращает текст транскрипции.
    """
    # Скачиваем .ogg файл во временную директорию
    file = await bot.get_file(voice.file_id)
    assert file.file_path is not None

    with tempfile.TemporaryDirectory() as tmp:
        local_path = Path(tmp) / "voice.ogg"
        await bot.download_file(file.file_path, destination=local_path)

        # Отправляем в Groq Whisper API
        with open(local_path, "rb") as audio_file:
            transcription = await _get_groq().audio.transcriptions.create(
                model="whisper-large-v3",
                file=audio_file,
                language="ru",
            )

    text = transcription.text.strip()

    # Логируем расход
    duration = voice.duration or 0
    await log_api_cost(
        user_id=user_id,
        bot_source=bot_source,
        model="whisper-large-v3",
        tokens_in=duration,
        tokens_out=0,
        task_type="transcription",
    )

    logger.info("whisper_transcribed", duration=duration, chars=len(text))
    return text
