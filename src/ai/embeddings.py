"""Генерация эмбеддингов через OpenAI text-embedding-3-small.

Размерность: 1536. Используется для RAG-поиска по pgvector.
При отсутствии OPENAI_API_KEY — возвращает None (graceful degradation).
"""

import structlog
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import settings
from src.utils.cost_tracker import log_api_cost

logger = structlog.get_logger()

_client: AsyncOpenAI | None = None


def _is_available() -> bool:
    """Проверить, доступен ли OpenAI API ключ для эмбеддингов."""
    return bool(settings.openai_api_key)


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(api_key=settings.openai_api_key)
    return _client


@retry(stop=stop_after_attempt(3), wait=wait_exponential(min=1, max=10))
async def generate_embedding(
    text: str,
    user_id: int | None = None,
    bot_source: str | None = None,
) -> list[float] | None:
    """Сгенерировать вектор эмбеддинга для текста.

    Возвращает list[float] длиной 1536 или None если API ключ не задан.
    """
    if not _is_available():
        logger.warning("embedding_skipped", reason="no_openai_api_key")
        return None

    response = await _get_client().embeddings.create(
        model="text-embedding-3-small",
        input=text,
    )
    embedding = response.data[0].embedding
    tokens = response.usage.total_tokens

    await log_api_cost(
        user_id=user_id,
        bot_source=bot_source,
        model="text-embedding-3-small",
        tokens_in=tokens,
        tokens_out=0,
        task_type="embedding",
    )

    logger.info("embedding_generated", tokens=tokens, dims=len(embedding))
    return embedding
