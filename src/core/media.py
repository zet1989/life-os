"""Загрузка файлов в Supabase Storage."""

import structlog

from src.db.supabase_client import get_supabase

logger = structlog.get_logger()

BUCKET = "media"


async def upload_to_storage(
    data: bytes,
    path: str,
    content_type: str = "image/jpeg",
) -> str:
    """Загрузить файл в Supabase Storage и вернуть публичный URL."""
    sb = get_supabase()
    sb.storage.from_(BUCKET).upload(
        path=path,
        file=data,
        file_options={"content-type": content_type},
    )
    public_url = sb.storage.from_(BUCKET).get_public_url(path)
    logger.info("storage_uploaded", path=path)
    return public_url
