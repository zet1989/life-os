"""Генерация эмбеддингов через OpenAI text-embedding-3-small.

Размерность: 1536. Используется для RAG-поиска по pgvector.
"""

import structlog
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import settings
from src.utils.cost_tracker import log_api_cost

logger = structlog.get_logger()

_client: AsyncOpenAI | None = None


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
) -> list[float]:
    """Сгенерировать вектор эмбеддинга для текста.

    Возвращает list[float] длиной 1536.
    """
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
