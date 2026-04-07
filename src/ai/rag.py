"""RAG — семантический поиск по pgvector.

Запрос → embedding → SQL оператор <=> → top-K результатов.
Фильтрация по user_id и опционально project_id (ACL).
"""

import structlog

from src.ai.embeddings import generate_embedding
from src.db.queries import match_events, update_event_embedding

logger = structlog.get_logger()


async def store_event_embedding(
    event_id: int,
    text: str,
    user_id: int | None = None,
    bot_source: str | None = None,
) -> None:
    """Сгенерировать эмбеддинг и сохранить в поле embedding таблицы events."""
    embedding = await generate_embedding(text, user_id=user_id, bot_source=bot_source)
    await update_event_embedding(event_id, embedding)
    logger.info("event_embedding_stored", event_id=event_id)


async def search(
    query: str,
    user_id: int,
    top_k: int = 5,
    project_id: int | None = None,
    bot_source: str | None = None,
) -> list[dict]:
    """Семантический поиск по событиям пользователя."""
    embedding = await generate_embedding(query, user_id=user_id, bot_source=bot_source)
    results = await match_events(embedding, user_id, match_count=top_k, project_id=project_id)
    logger.info("rag_search", query=query[:50], results=len(results))
    return results


async def rag_answer(
    query: str,
    user_id: int,
    system_prompt: str,
    top_k: int = 5,
    project_id: int | None = None,
    bot_source: str | None = None,
) -> str:
    """RAG-ответ: поиск релевантных событий → формирование контекста → LLM.

    Паттерн: retrieve → augment → generate.
    """
    from src.ai.router import chat

    # Retrieve
    docs = await search(query, user_id, top_k=top_k, project_id=project_id, bot_source=bot_source)

    if not docs:
        context = "Релевантных записей не найдено."
    else:
        chunks = []
        for doc in docs:
            ts = doc.get("timestamp", "")
            text = doc.get("raw_text", "")
            etype = doc.get("event_type", "")
            jd = doc.get("json_data") or {}
            if etype == "obsidian_note":
                src = jd.get("source_file", "")
                chunks.append(f"[📝 Obsidian: {src}] {text}")
            else:
                chunks.append(f"[{ts}] ({etype}) {text}")
        context = "\n".join(chunks)

    # Источники из Obsidian
    obsidian_sources = [
        (doc.get("json_data") or {}).get("source_file", "")
        for doc in docs
        if doc.get("event_type") == "obsidian_note"
    ]

    # Augment + Generate
    messages = [
        {"role": "system", "content": system_prompt},
        {"role": "user", "content": f"Контекст из базы знаний:\n{context}\n\nВопрос: {query}"},
    ]

    answer = await chat(
        messages=messages,
        task_type="rag_answer",
        user_id=user_id,
        bot_source=bot_source,
    )

    # Добавляем ссылки на Obsidian-источники
    if obsidian_sources:
        sources_text = "\n".join(f"📝 {s}" for s in obsidian_sources if s)
        if sources_text:
            answer += f"\n\n📂 Источники Obsidian:\n{sources_text}"

    return answer
