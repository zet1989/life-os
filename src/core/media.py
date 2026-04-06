"""Локальное хранилище медиафайлов.

Файлы сохраняются в /app/media/ (Docker volume).
"""

from pathlib import Path

import structlog

logger = structlog.get_logger()

MEDIA_DIR = Path("/app/media")


async def save_media(
    data: bytes,
    path: str,
    content_type: str = "image/jpeg",
) -> str:
    """Сохранить файл на диск. Возвращает локальный путь."""
    filepath = MEDIA_DIR / path
    filepath.parent.mkdir(parents=True, exist_ok=True)
    filepath.write_bytes(data)
    logger.info("media_saved", path=str(filepath), size=len(data))
    return str(filepath)
