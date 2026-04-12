# Life OS — Инструкции для Copilot

## Проект

Разработка экосистемы персональных AI-агентов (Life OS) — сеть Telegram-ботов на Python 3.11+ / aiogram 3.x с Supabase, pgvector RAG, OpenRouter.

## Обязательный контекст

Перед началом любой работы по проекту — прочитай оба файла:
- `plan.md` — ТЗ: концепция, стек, схема БД, этапы, UI/UX, инструкции для vibecoding.
- `implementation_plan.md` — план реализации: структура проекта, SQL-схема, чеклист по фазам, зависимости, риски.

Не отступай от архитектуры и решений, зафиксированных в этих файлах. Если нужно отклониться — спроси подтверждение.
Всегда пиши в чате на руссоком языке, если не указано иное.

## Стек (не менять без согласования)

- Python 3.11+, aiogram 3.x, PostgreSQL 16 + pgvector (Docker, self-hosted)
- asyncpg (connection pool), Redis (кэш контекста, очереди, дедупликация)
- OpenRouter (AI routing), OpenAI Whisper (аудио), text-embedding-3-small (RAG)
- Pydantic Settings, tenacity, APScheduler, structlog
- Docker Compose, VPS Beget, GitHub Actions CI/CD

## Правила

- Финансы считать ТОЛЬКО через SQL (SUM/GROUP BY), НИКОГДА через LLM.
- Все данные фильтруются по user_id (ACL). Роль wife — доступ к ботам health и family.
- Партнёр (Александр) видит только partnership-проекты, в которых он collaborator (поле `collaborators` в projects).
- Жена видит только family-проекты (через `collaborators`) и свои личные данные в health.
- Фазы выполняются строго последовательно. Не начинать Фазу N+1 пока N не стабильна.
- При обновлении чеклиста в implementation_plan.md — отмечай `[x]` выполненные пункты.
- **После каждой рабочей сессии** обязательно обнови `docs/PROJECT_CONTEXT.md`: секцию Changelog, описание изменённых компонентов и решённых проблем.
- **После ЛЮБЫХ изменений** обнови соответствующие документы:
  - `docs/PROJECT_CONTEXT.md` — Changelog, описание затронутых компонентов
  - `docs/ROADMAP.md` — отметь `[x]` выполненные пункты, добавь новые если появились
