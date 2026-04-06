"""Генерация эмбеддингов через OpenRouter (модель openai/text-embedding-3-small).

Размерность: 1536. Используется для RAG-поиска по pgvector.
Использует OpenRouter API с ключом OPENROUTER_API_KEY.
"""

import structlog
from openai import AsyncOpenAI
from tenacity import retry, stop_after_attempt, wait_exponential

from src.config import settings
from src.utils.cost_tracker import log_api_cost

logger = structlog.get_logger()

OPENROUTER_BASE_URL = "https://openrouter.ai/api/v1"
EMBEDDING_MODEL = "openai/text-embedding-3-small"

_client: AsyncOpenAI | None = None


def _get_client() -> AsyncOpenAI:
    global _client
    if _client is None:
        _client = AsyncOpenAI(
            api_key=settings.openrouter_api_key,
            base_url=OPENROUTER_BASE_URL,
        )
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
        model=EMBEDDING_MODEL,
        input=text,
    )
    embedding = response.data[0].embedding
    tokens = response.usage.total_tokens if response.usage else 0

    await log_api_cost(
        user_id=user_id,
        bot_source=bot_source,
        model=EMBEDDING_MODEL,
        tokens_in=tokens,
        tokens_out=0,
        task_type="embedding",
    )

    logger.info("embedding_generated", tokens=tokens, dims=len(embedding))
    return embedding
