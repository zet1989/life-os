"""Анализ фото через Vision API (OpenRouter).

Загрузка фото в Supabase Storage → отправка URL в LLM с vision.
"""

import uuid
from io import BytesIO

import structlog
from aiogram import Bot
from aiogram.types import PhotoSize

from src.ai.router import chat
from src.core.media import upload_to_storage

logger = structlog.get_logger()


async def analyze_photo(
    bot: Bot,
    photo: PhotoSize,
    prompt: str,
    task_type: str = "meal_photo",
    user_id: int | None = None,
    bot_source: str | None = None,
) -> str:
    """Скачать фото из Telegram, загрузить в Storage, отправить в Vision LLM.

    Args:
        prompt: системный промпт (что делать с фото — считать КБЖУ, OCR чека и т.д.)
        task_type: для выбора модели из model_routing
    """
    # Скачиваем фото
    file = await bot.get_file(photo.file_id)
    assert file.file_path is not None

    buf = BytesIO()
    await bot.download_file(file.file_path, destination=buf)
    buf.seek(0)

    # Загружаем в Supabase Storage
    filename = f"{user_id}/{uuid.uuid4().hex}.jpg"
    public_url = await upload_to_storage(buf.read(), filename, content_type="image/jpeg")

    logger.info("photo_uploaded", url=public_url, task=task_type)

    # Формируем messages с image_url для Vision
    messages = [
        {"role": "system", "content": prompt},
        {
            "role": "user",
            "content": [
                {
                    "type": "image_url",
                    "image_url": {"url": public_url},
                },
            ],
        },
    ]

    result = await chat(
        messages=messages,
        task_type=task_type,
        user_id=user_id,
        bot_source=bot_source,
    )
    return result
