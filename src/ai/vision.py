"""Анализ фото через Vision API (OpenRouter).

Скачивание фото → base64 → LLM с vision. Архив на диске.
"""

import base64
import uuid
from io import BytesIO

import structlog
from aiogram import Bot
from aiogram.types import PhotoSize

from src.ai.router import chat
from src.core.media import save_media

logger = structlog.get_logger()


async def analyze_photo(
    bot: Bot,
    photo: PhotoSize,
    prompt: str,
    task_type: str = "meal_photo",
    user_id: int | None = None,
    bot_source: str | None = None,
    caption: str | None = None,
) -> str:
    """Скачать фото из Telegram, сохранить локально, отправить в Vision LLM (base64)."""
    # Скачиваем фото
    file = await bot.get_file(photo.file_id)
    assert file.file_path is not None

    buf = BytesIO()
    await bot.download_file(file.file_path, destination=buf)
    buf.seek(0)
    photo_bytes = buf.read()

    # Сохраняем на диск (архив)
    filename = f"{user_id}/{uuid.uuid4().hex}.jpg"
    await save_media(photo_bytes, filename, content_type="image/jpeg")

    # Base64 для Vision API
    b64 = base64.b64encode(photo_bytes).decode()
    data_uri = f"data:image/jpeg;base64,{b64}"

    logger.info("photo_prepared", task=task_type, size=len(photo_bytes))

    # Формируем messages с image_url для Vision
    user_content: list[dict] = [
        {
            "type": "image_url",
            "image_url": {"url": data_uri},
        },
    ]
    if caption:
        user_content.append({"type": "text", "text": caption})

    messages = [
        {"role": "system", "content": prompt},
        {
            "role": "user",
            "content": user_content,
        },
    ]

    result = await chat(
        messages=messages,
        task_type=task_type,
        user_id=user_id,
        bot_source=bot_source,
    )
    return result
