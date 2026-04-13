"""OpenRouter AI клиент — единая точка вызова LLM.

Выбор модели по task_type из таблицы model_routing.
Retry с exponential backoff через tenacity.
Логирование расходов через cost_tracker.
"""

from typing import Any

import httpx
import structlog
from tenacity import retry, stop_after_attempt, wait_exponential, retry_if_exception_type

from src.config import settings
from src.db.queries import get_model_config as _db_get_model_config
from src.utils.cost_tracker import log_api_cost
from src.utils.budget_limiter import check_budget, BudgetExceededError

logger = structlog.get_logger()

OPENROUTER_URL = "https://openrouter.ai/api/v1/chat/completions"

# Кэш маршрутов моделей (чтобы не ходить в БД каждый раз)
_model_cache: dict[str, dict] = {}


async def get_model_config(task_type: str) -> dict:
    """Получить конфиг модели для task_type из таблицы model_routing."""
    if task_type in _model_cache:
        return _model_cache[task_type]

    config = await _db_get_model_config(task_type)
    if config is None:
        # Все задачи → DeepSeek V3.2 (GPT-5 class, дешевле gpt-4o-mini по output)
        # fallback → gpt-4o-mini на случай недоступности DeepSeek
        config = {
            "model": "deepseek/deepseek-v3.2",
            "max_tokens": 1000,
            "temperature": 0.5,
            "fallback_model": "openai/gpt-4o-mini",
        }
    _model_cache[task_type] = config
    return config


def invalidate_model_cache() -> None:
    """Сбросить кэш (при изменении model_routing через БД)."""
    _model_cache.clear()


@retry(
    stop=stop_after_attempt(3),
    wait=wait_exponential(multiplier=1, min=1, max=10),
    retry=retry_if_exception_type((httpx.HTTPStatusError, httpx.ConnectError, httpx.TimeoutException)),
)
async def _call_openrouter(
    model: str,
    messages: list[dict[str, str]],
    max_tokens: int,
    temperature: float,
) -> dict[str, Any]:
    """Низкоуровневый вызов OpenRouter API с retry."""
    async with httpx.AsyncClient(timeout=60.0) as client:
        response = await client.post(
            OPENROUTER_URL,
            headers={
                "Authorization": f"Bearer {settings.openrouter_api_key}",
                "Content-Type": "application/json",
            },
            json={
                "model": model,
                "messages": messages,
                "max_tokens": max_tokens,
                "temperature": temperature,
            },
        )
        response.raise_for_status()
        return response.json()


async def chat(
    messages: list[dict[str, str]],
    task_type: str = "general_chat",
    user_id: int | None = None,
    bot_source: str | None = None,
) -> str:
    """Отправить промпт в LLM и получить ответ.

    Автоматически выбирает модель по task_type.
    При ошибке основной модели — переключается на fallback.
    Логирует расход в api_costs.
    Проверяет бюджетный лимит перед вызовом.
    """
    # Budget check
    try:
        await check_budget()
    except BudgetExceededError as e:
        logger.warning("budget_exceeded", task=task_type, error=str(e))
        return f"⚠️ {e}"

    config = await get_model_config(task_type)
    model = config["model"]
    max_tokens = config.get("max_tokens") or 1000
    temperature = float(config.get("temperature") or 0.5)
    fallback = config.get("fallback_model")

    try:
        data = await _call_openrouter(model, messages, max_tokens, temperature)
    except Exception:
        if fallback:
            logger.warning("model_fallback", primary=model, fallback=fallback, task=task_type)
            data = await _call_openrouter(fallback, messages, max_tokens, temperature)
            model = fallback
        else:
            raise

    # Извлекаем ответ
    choice = data.get("choices", [{}])[0]
    content = choice.get("message", {}).get("content", "")

    # Логируем расход
    usage = data.get("usage", {})
    tokens_in = usage.get("prompt_tokens", 0)
    tokens_out = usage.get("completion_tokens", 0)

    await log_api_cost(
        user_id=user_id,
        bot_source=bot_source,
        model=model,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
        task_type=task_type,
    )

    logger.info(
        "llm_call",
        model=model,
        task=task_type,
        tokens_in=tokens_in,
        tokens_out=tokens_out,
    )

    return content
