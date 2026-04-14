# Life OS — Полная проектная документация

> **Последнее обновление:** 20 апреля 2026
> **Автор:** Алексей (zet1989)
> **Файл в .gitignore для сохранения приватности**

---

## 1. Обзор проекта

**Life OS** — экосистема из 8 персональных AI-агентов (Telegram-ботов), объединённых общей базой данных. Каждый бот отвечает за свою сферу жизни.

### 1.1 Архитектура

**Режим Unified Bot (основной):** все 8 секций работают внутри одного Telegram-бота (токен `BOT_TOKEN_UNIFIED`). Пользователь выбирает секцию через главное меню, кнопка «🏠 Меню» возвращает назад. SectionFilter на роутерах изолирует обработчики секций.

**Legacy multi-bot:** 8 отдельных ботов (по токену на каждого). Работает если `BOT_TOKEN_UNIFIED` не задан.

### 1.1.1 Секции (бывшие отдельные боты)

| # | Секция | Меню | Назначение |
|---|--------|------|------------|
| 1 | **Health** | 🏥 Здоровье | Фото еды → КБЖУ + health score + советы; лог тренировок; Доктор; профиль |
| 2 | **Assets** | 🏠 Дом и Авто | Бортжурнал авто, замеры дома, чеки → финансы, напоминания по пробегу |
| 3 | **Business** | 💼 Бизнес | Проектный бизнес с per-project промптами, фин. отчёты (SQL only) |
| 4 | **Partner** | 🤝 Партнёр | Мульти-проект для партнёра Александра, privacy mode |
| 5 | **Mentor** | 📈 Ментор | Идеи → RAG, анализ обсуждений (Whisper), фин. стратегия |
| 6 | **Family** | 👨‍👩‍👧 Семья | Расходы/доходы, OCR чеков, отчёты, лимиты категорий |
| 7 | **Psychology** | 🧠 Психолог | Дневник → RAG, трекинг привычек, ретроспектива, профиль |
| 8 | **Master** | 🎛 Мастер | Хранитель видения, фин. панорама, аудит, промпт-менеджмент |

### 1.2 Пользователи

| Роль | Telegram ID | Доступ |
|------|-------------|--------|
| **admin** (Алексей) | `ADMIN_USER_ID` из .env | Все 8 ботов |
| **wife** (жена) | В таблице users | health, family, свои данные |
| **partner** (Александр) | В таблице users | partnership-проекты через `collaborators[]` |

---

## 2. Стек технологий

| Компонент | Технология | Версия |
|-----------|-----------|--------|
| Язык | Python | 3.11+ |
| Telegram framework | aiogram | 3.x |
| БД | PostgreSQL + pgvector | 16 |
| Пул соединений | asyncpg | — |
| Кэш/очереди | Redis | 7 |
| AI routing | OpenRouter | — |
| Audio (STT) | faster-whisper (ЛОКАЛЬНЫЙ) | model "medium", CPU int8 |
| Embeddings | text-embedding-3-small | 1536 dim |
| Конфигурация | Pydantic Settings | — |
| Retry | tenacity | — |
| Планировщик | APScheduler | — |
| Логирование | structlog | — |
| Контейнеризация | Docker Compose | — |
| CI/CD | GitHub Actions | — |
| VPS | Beget | — |

---

## 3. Инфраструктура и деплой

### 3.1 Сервер

- **IP:** 159.194.218.101
- **User:** root
- **SSH ключ:** ed25519 (публичный: `ssh-ed25519 AAAAC3NzaC1lZDI1NTE5AAAAIKlyhZJXrQ6XO9FatkXAoJPAT0uF66SAgasRfVx3WJHa`)
- **Путь проекта на сервере:** `/opt/life-os/`

### 3.2 GitHub

- **Репозиторий:** https://github.com/zet1989/life-os
- **Ветка:** `main`
- **Публичный:** Да
- **Секреты Actions:** VPS_HOST, VPS_USER, VPS_SSH_KEY

### 3.3 CI/CD Pipeline

При push в `main`:
1. GitHub Actions SSH на VPS
2. `cd /opt/life-os && git pull origin main`
3. `docker compose build --no-cache bot`
4. `docker compose up -d`
5. `docker compose logs --tail=20 bot`

### 3.4 Docker Compose

| Сервис | Образ | Порты | Health Check |
|--------|-------|-------|-------------|
| **bot** | Dockerfile (local) | 8443:8443 | HTTP /status |
| **postgres** | pgvector/pgvector:pg16 | 127.0.0.1:5432:5432 | pg_isready |
| **redis** | redis:7-alpine | — (внутренняя сеть) | — |
| **nginx** (prod) | nginx:alpine | 80, 443 | — |

### 3.5 Ручной деплой

```powershell
# Локально (PowerShell)
ssh root@159.194.218.101 "cd /opt/life-os && git pull origin main && docker compose build --no-cache bot && docker compose up -d && docker compose logs --tail=30 bot"
```

### 3.6 Структура на VPS

```
/opt/life-os/
├── .env                    # Все токены и секреты
├── docker-compose.yml
├── Dockerfile
├── requirements.txt
├── sql/
│   └── 001_init_schema.sql
├── src/                    # Код приложения
│   ├── config.py
│   ├── main.py
│   ├── ai/
│   ├── bots/
│   ├── core/
│   ├── db/
│   └── utils/
└── nginx/
    └── life-os.conf
```

---

## 4. Локальная разработка

### 4.1 Структура рабочей директории

```
c:\Users\Alexey\Desktop\Жизнь\
├── .github/
│   ├── copilot-instructions.md
│   └── workflows/deploy.yml
├── plan.md                    # ТЗ
├── implementation_plan.md     # План реализации
├── life-os/                   # ← Рабочая папка (здесь правим код)
│   ├── .env
│   ├── docker-compose.yml
│   ├── Dockerfile
│   ├── requirements.txt
│   ├── src/                   # Правим файлы ЗДЕСЬ
│   ├── sql/
│   ├── docs/
│   └── nginx/
├── src/                       # ← Git tracking (копируем сюда перед коммитом)
├── sql/
├── docs/
├── nginx/
├── docker-compose.yml
├── Dockerfile
└── requirements.txt
```

### 4.2 КРИТИЧЕСКИ ВАЖНО: Синхронизация перед коммитом

Git отслеживает файлы в корне (`src/`, `sql/` и т.д.), а правки делаются в `life-os/src/`.
**Перед каждым коммитом:**

```powershell
# Копируем изменённые файлы из life-os/ в корень
Copy-Item -Recurse -Force life-os\src\* src\
Copy-Item -Recurse -Force life-os\sql\* sql\
Copy-Item -Force life-os\docker-compose.yml .
Copy-Item -Force life-os\Dockerfile .
Copy-Item -Force life-os\requirements.txt .

# Коммитим
git add -A
git commit -m "описание"
git push origin main  # → триггерит GitHub Actions
```

---

## 5. База данных

### 5.1 Таблицы

| Таблица | Назначение | Ключевые поля |
|---------|-----------|--------------|
| **users** | Пользователи | user_id (TG ID), role, permissions (JSONB), system_prompt_overrides |
| **projects** | Проекты | project_id, name, type, owner_id, collaborators[], metadata (JSONB) |
| **goals** | Цели/мечты | user_id, type (dream/yearly_goal/habit_target), progress_pct, parent_goal_id |
| **events** | Единая шина данных | user_id, project_id, bot_source, event_type, raw_text, json_data (JSONB), embedding (vector 1536) |
| **finances** | Строгая математика | project_id, user_id, amount (NUMERIC 12,2), category, transaction_type |
| **conversations** | Контекст диалогов | user_id, bot_source, role, content, tokens_used |
| **api_costs** | Контроль расходов | user_id, bot_source, model, cost_usd, task_type |
| **reminders** | Напоминания | user_id, bot_source, cron_expression, next_fire_at |
| **model_routing** | Маршрутизация AI | task_type (UNIQUE), model, max_tokens, temperature, fallback_model |

### 5.2 Ключевые event_types

`meal`, `workout`, `thought`, `business_task`, `measurement`, `auto_maintenance`, `diary`, `habit`, `family_info`, `health_record`

### 5.3 Ключевые bot_sources

`health`, `assets`, `business`, `partner`, `mentor`, `family`, `psychology`, `master`

> В unified-режиме `bot_source` остаётся прежним (по секции), т.к. хардкодится в каждом хэндлере.

### 5.4 RPC-функции PostgreSQL

- `match_events()` — семантический поиск по embedding (RAG)
- `sum_api_costs()` — сумма API-расходов за период
- `finance_summary()` — GROUP BY category/type (ТОЛЬКО SQL, НЕ LLM)
- `get_accessible_projects()` — проекты по ACL

---

## 6. AI и модели

### 6.1 Model Routing

| task_type | Модель | max_tokens | Назначение |
|-----------|--------|-----------|------------|
| meal_photo | gpt-4o-mini | 500 | Анализ еды: КБЖУ + health score + советы + оценка дня |
| nutrition_consult | deepseek-v3.2 | 1500 | Вопросы нутрициологу (советы, добавки, анализ рациона) |
| doctor_consult | deepseek-v3.2 | 2000 | Медицинские консультации, анализы (fallback: gpt-4o) |
| workout_parse | gpt-4o-mini | 500 | Парсинг тренировки |
| business_strategy | deepseek-v3.2 | 2000 | Бизнес-стратегия |
| diary_reflection | deepseek-v3.2 | 2000 | Психология - дневник |
| mentor_discussion | deepseek-v3.2 | 2000 | Ментор - анализ обсуждений |
| daily_summary | gpt-4o-mini | 800 | Дневная сводка КБЖУ |
| general_chat | gpt-4o-mini | 1000 | Общий чат |

### 6.2 Бюджеты

- Daily API limit: $2.0
- Monthly API limit: $20.0
- Ожидаемый расход: ~$5-10/мес (после перехода на DeepSeek V3.2)
- Бесплатные модели отключены (см. 7.6)

---

## 7. Известные проблемы и решения

### 7.1 Калории накапливались из истории чата

**Проблема:** LLM видела в conversation history свои старые ответы «Итого 2737 ккал» и прибавляла к ним.
**Корень:** Таблица conversations хранила ответы LLM с цифрами, даже 2 сообщения из history отравляли контекст.
**Решение (v3 — финальное):**
- STATELESS архитектура: ноль conversation history, каждое сообщение обрабатывается независимо
- System prompt (данные о еде из `events.json_data` через `_today_meals_context()`) — ЕДИНСТВЕННЫЙ источник данных
- Health бот НЕ сохраняет ответы в conversations, НЕ читает conversations
- Event создаётся ТОЛЬКО если LLM вернул JSON с КБЖУ (нет мусорных записей)
- Удалена вся health conversation history из БД

### 7.2 Пустая строка + фразы-филлеры

**Проблема:** LLM писала «содержание калорий будет следующим:» + пустое место, дублировала КБЖУ.
**Решение:** Карточка строится на стороне кода из json_data, НЕ из текста LLM. Промпт требует ТОЛЬКО JSON.

### 7.5 LLM спрашивала вес продукта

**Проблема:** При вводе «банан» LLM спрашивала «сколько он весит?» — event создавался без json_data.
**Решение:** Промпт явно запрещает спрашивать вес, стандартная порция (банан=120г, яблоко=180г). Event НЕ создаётся если json_data пустая.

### 7.6 Бесплатные модели OpenRouter — ОТКЛЮЧЕНЫ ✅

**Проблема:** `meta-llama/llama-3.1-8b-instruct:free` стабильно фейлился, все запросы падали на платный gpt-4o-mini.
**Статистика:** 105 вызовов — все пошли через gpt-4o-mini ($0.08 суммарно). Ноль успешных бесплатных вызовов.
**Решение:** Полностью удалён механизм бесплатных моделей из router.py — FREE_MODEL_MAP, _pick_model(), _get_free_count_today(), _increment_free_count(), FREE_DAILY_LIMIT. Функция chat() всегда использует платную модель из model_routing. AI Панель в Master боте обновлена — убрана информация о бесплатных лимитах.

### 7.3 Психолог не знал про машину из assets

**Проблема:** `_build_life_context()` брала события за 7 дней — авто было записано раньше.
**Решение:** Добавлена `get_life_profile()` — берёт из assets без лимита по дате.

### 7.4 Бизнес-бот использовал общий промпт

**Проблема:** Все проекты в business видели одинаковый BUSINESS_SYSTEM.
**Решение:** Per-project промпты через `project.metadata.system_prompt` + управление через Master (/set_prompt, /clear_prompt).

---

## 8. Scheduler (планировщик)

### 8.1 Health Bot

| Задача | Расписание | Описание |
|--------|-----------|----------|
| Дневная сводка КБЖУ | Ежедневно 21:00 MSK | Перечисляет все блюда, ИТОГО, рекомендации |
| Недельная сводка | Воскресенье 20:00 MSK | Средние КБЖУ, дни-выбросы, оценка 1-10 |
| Месячная сводка | Последний день месяца 20:00 MSK | Динамика по неделям, рекомендации на месяц |

### 8.2 Assets Bot

| Задача | Расписание | Описание |
|--------|-----------|----------|
| Напоминание по пробегу | Настраивается | Напоминает о ТО по пробегу |

### 8.3 Master Bot

| Задача | Расписание | Описание |
|--------|-----------|----------|
| Ежемесячный аудит | 1-е число месяца | Кросс-бот анализ всех сфер |

---

## 8.5 Health Bot — Архитектура режимов

| Режим | Кнопка | Модель | Архитектура | Описание |
|-------|--------|--------|-------------|----------|
| **Еда** | 🍽 Еда | gpt-4o-mini | STATELESS (0 history) | Фото/текст → КБЖУ JSON → карточка |
| **Вопрос нутрициологу** | 🍽 Еда | deepseek-v3.2 | История (4 сообщ.) + рацион за 30 дней | Вопросы, оценка рациона, тренды питания |
| **Тренировка** | 🏋️ Тренировка | gpt-4o-mini | STATELESS | Описание → exercises JSON → карточка |
| **Доктор** | 🩺 Доктор | gpt-4o (critical) | С ИСТОРИЕЙ (build_messages) | Медконсультации, анализы, лекарства |
| **Профиль** | 📋 Мой профиль | — | — | Просмотр/обновление профиля (users.system_prompt_overrides) |

**Жена (role=wife):** Использует отдельный WIFE_NUTRITIONIST_SYSTEM промпт в режиме Еда — нормы для женщин (1600-2000 ккал, железо 18 мг, кальций 1000 мг, фолиевая кислота, витамин D), тёплый тон.

**Доктор** — единственный режим Health с conversation history. Видит: питание дня, тренировки дня, полный профиль (болезни, лекарства). Фото в режиме доктора анализируются как медицинские (анализы, симптомы).

**Профиль** — общее поле `system_prompt_overrides` в таблице users. Доступен из обоих ботов (Health и Psychology). Изменения в одном боте видны в другом.

---

## 9. ACL (Контроль доступа)

### 9.1 Правила

1. Все данные фильтруются по `user_id`
2. Роль `wife` → доступ к ботам health и family
3. Партнёр (Александр) → только partnership-проекты, где он в `collaborators[]`
4. Жена → только family-проекты (через `collaborators[]`) и свои данные в health
5. Финансы считаются ТОЛЬКО через SQL (SUM/GROUP BY), НИКОГДА через LLM

### 9.2 ACL Middleware

Каждый бот подключает `ACLMiddleware(bot_name=...)`. При каждом сообщении:
1. Проверяется `users.is_active = TRUE`
2. Проверяются `permissions.bots`
3. При доступе к проекту — проверяется `owner_id` или наличие в `collaborators[]`

---

## 10. Переменные окружения (.env)

```env
# === Боты ===
BOT_TOKEN_HEALTH=...
BOT_TOKEN_ASSETS=...
BOT_TOKEN_BUSINESS=...
BOT_TOKEN_PARTNER=...
BOT_TOKEN_MENTOR=...
BOT_TOKEN_FAMILY=...
BOT_TOKEN_PSYCHOLOGY=...
BOT_TOKEN_MASTER=...

# === БД ===
DATABASE_URL=postgresql://lifeos:lifeos@postgres:5432/lifeos
POSTGRES_PASSWORD=lifeos

# === AI ===
OPENROUTER_API_KEY=...
OPENAI_API_KEY=...

# === Redis ===
REDIS_URL=redis://redis:6379/0

# === Общие ===
ADMIN_USER_ID=...
LOG_LEVEL=INFO

# === Webhook (prod) ===
USE_WEBHOOK=false
WEBHOOK_HOST=
WEBHOOK_PORT=8443
WEBHOOK_SECRET=

# === Лимиты ===
API_DAILY_LIMIT_USD=2.0
API_MONTHLY_LIMIT_USD=20.0
```

---

## 11. Ключевые файлы и их назначение

| Файл | Назначение |
|------|-----------|
| `src/main.py` | Точка входа, сбор ботов, polling/webhook |
| `src/config.py` | Pydantic Settings, все env vars |
| `src/ai/router.py` | OpenRouter клиент, model routing, tenacity retry, fallback для doctor_consult → gpt-4o |
| `src/ai/whisper.py` | Транскрипция аудио |
| `src/ai/vision.py` | Анализ фото (gpt-4o) |
| `src/ai/embeddings.py` | text-embedding-3-small |
| `src/ai/rag.py` | Семантический поиск pgvector |
| `src/db/postgres.py` | asyncpg connection pool |
| `src/db/queries.py` | Все SQL-запросы (CRUD, фильтры, агрегаты) |
| `src/core/acl.py` | ACL middleware |
| `src/core/context.py` | Загрузка/сохранение контекста диалога |
| `src/core/media.py` | Работа с медиафайлами |
| `src/utils/telegram.py` | safe_answer, safe_edit, safe_send |
| `src/utils/budget_limiter.py` | Контроль API-расходов |
| `src/utils/cost_tracker.py` | Трекинг стоимости запросов |

---

## 12. Changelog (последние изменения)

### 14 апреля 2026 — Todoist интеграция + очистка watch_stale

- **Todoist:**
  - `src/integrations/todoist.py` — новый модуль: async-клиент Todoist REST API v1 (Bearer token). Функции: `get_inbox_tasks()`, `create_task()`, `close_task()`, `get_projects()`, `get_user_info()`
  - `src/config.py` — добавлен `todoist_api_token` (Personal API token, Settings → Integrations → Developer)
  - `src/bots/master/handlers.py` — команда `/todoist`: просмотр Todoist Inbox, импорт задач в Life OS (по одной или все разом), завершение в Todoist. Callbacks: `td_imp:`, `td_done:`, `td_imp_all`
- **Watch stale cleanup:**
  - `src/bots/health/scheduler.py` — удалены функция `check_watch_stale()` и её регистрация в планировщике. Пользователь синхронизирует часы вручную раз в сутки.
- **Файлы:** `src/integrations/todoist.py`, `src/config.py`, `src/bots/master/handlers.py`, `src/bots/health/scheduler.py`

### 14 апреля 2026 — GTD Inbox: быстрый захват мыслей

- **Проблема:** Нет быстрого способа записать мысль/идею без указания даты и проекта. При добавлении задач требуется парсинг через LLM (задержка).
- **Решение:** Реализован GTD Inbox — система мгновенного захвата мыслей по методологии Getting Things Done (David Allen). Capture → Clarify → Organize.
- **Изменения:**
  - `src/db/queries.py` — добавлена функция `get_inbox_tasks()` (задачи без даты, не выполнены, без parent)
  - `src/bots/master/keyboard.py` — добавлен `Mode.INBOX`, кнопка «📥 Inbox» в главную клавиатуру
  - `src/bots/master/handlers.py` — полный набор inbox-хэндлеров:
    - `/i <текст>` — ультра-быстрый захват (1 символ команды!)
    - `/inbox [текст]` — показ inbox или захват
    - Кнопка «📥 Inbox» — режим INBOX, любой текст = захват
    - Разбор inbox: 📅 планирование (сегодня/завтра/пн), ✅ выполнено, 🗑 удалить
    - Массовые операции: «Все→сегодня», «Все→завтра»
    - Бэдж в задачах: «📥 Inbox: N нераспределённых мыслей → /inbox»
  - `src/webapp/__init__.py` — inbox-задачи включены в API `/api/webapp/tasks`
- **Принцип:** Без LLM, без даты, без приоритета, без проекта = мгновенная запись. Разбор потом в удобное время.
- **Файлы:** `src/db/queries.py`, `src/bots/master/keyboard.py`, `src/bots/master/handlers.py`, `src/webapp/__init__.py`

### 13 апреля 2026 — Единая модель: DeepSeek V3.2 на все задачи

- **Причина:** DeepSeek V3.2 (GPT-5 class) — $0.26/$0.38 за 1M токенов. Output на 37% дешевле gpt-4o-mini ($0.38 vs $0.60), при значительно лучшем качестве.
- **Изменения:**
  - `src/ai/router.py` — упрощён: единый fallback `deepseek/deepseek-v3.2` для всех task_type, gpt-4o-mini только как fallback
  - `sql/001_init_schema.sql` — все 25 seed-записей переведены на `deepseek/deepseek-v3.2`
  - `sql/004_claude_sonnet_upgrade.sql` — миграция переписана: единый UPDATE для всех моделей → DeepSeek
  - `docs/FULL_GUIDE.md` — обновлена таблица моделей
  - Production DB: UPDATE 16 записей gpt-4o-mini → deepseek/deepseek-v3.2
- **Итог:** Одна модель (DeepSeek V3.2) на все 30 задач + whisper для транскрипции. gpt-4o-mini только fallback.
- **Файлы:** `src/ai/router.py`, `sql/001_init_schema.sql`, `sql/004_claude_sonnet_upgrade.sql`, `docs/FULL_GUIDE.md`

### 13 апреля 2026 — Полное удаление дорогих моделей (gpt-4o, Claude)

- **Причина:** Оптимизация расходов — полностью убраны дорогие модели OpenAI (gpt-4o: $2.50/$10) и Claude (Sonnet 4: $3/$15). Оставлены только DeepSeek V3.2 ($0.26/$1.10) и gpt-4o-mini ($0.15/$0.60).
- **Изменения:**
  - `src/ai/router.py` — все fallback_model с `openai/gpt-4o` → `openai/gpt-4o-mini`
  - `sql/001_init_schema.sql` — полностью обновлены seed-данные: gpt-4o убран отовсюду, psychology_diary/master_goal → DeepSeek
  - `sql/004_claude_sonnet_upgrade.sql` — все fallback `openai/gpt-4o` → `openai/gpt-4o-mini`
  - Production DB: UPDATE 13 fallback + UPDATE 2 OCR primary (receipt_ocr, order_ocr: gpt-4o → gpt-4o-mini) + UPDATE 5 оставшихся fallback
- **Итоговая маршрутизация:** DeepSeek V3.2 (стратегия, дневник, доктор, ментор) + gpt-4o-mini (всё остальное). gpt-4o и Claude полностью убраны.
- **Файлы:** `src/ai/router.py`, `sql/001_init_schema.sql`, `sql/004_claude_sonnet_upgrade.sql`

### 20 апреля 2026 — Полная замена Claude Sonnet 4 → DeepSeek V3.2

- **Причина:** DeepSeek V3.2 — сопоставимое качество для стратегических задач при 10x меньшей стоимости ($0.26/$1.10 vs $3/$15 за 1M токенов).
- **Изменения:**
  - `sql/004_claude_sonnet_upgrade.sql` — все `anthropic/claude-sonnet-4` → `deepseek/deepseek-v3.2`
  - `sql/001_init_schema.sql` — все `claude-3.5-sonnet` → `deepseek/deepseek-v3.2` в seed-данных model_routing
  - `docs/FULL_GUIDE.md` — обновлена таблица моделей и секция использования
  - `doctor_consult` переведён с gpt-4o на DeepSeek V3.2
  - Production DB обновлена: UPDATE model_routing
- **Затронутые task_type:** diary_reflection, mentor_*, master_audit, master_talk, master_goal, psychology_diary, psychology_report, business_strategy, quarterly_audit, doctor_consult
- **Файлы:** `sql/004_claude_sonnet_upgrade.sql`, `sql/001_init_schema.sql`, `docs/FULL_GUIDE.md`

### 13 апреля 2026 — Фикс автосинхронизации часов: архитектурная переработка AppService

- **Проблема:** Автосинхронизация часов не работала — данные собирались фоновым сервисом каждые 15 мин, но НИКОГДА не отправлялись на сервер. Причина: Zepp OS AppService в режиме Single Execution (setAlarm) имеет лимит 600мс — async BLE messaging физически не успевает завершиться. `getApp()._options.globalData.messaging` всегда null в контексте AppService (ZML не инициализирован). Также `setAlarm` вызывался ПОСЛЕ сбора данных — если сбор падал, цепочка alarm'ов разрывалась. URL alarm содержал `.js` суффикс, не совпадающий с app.json.
- **Решение:**
  - **AppService полностью переписан:** удалён мёртвый код `trySendViaMessaging()` и `getApp` import. Alarm ставится ПЕРВЫМ (до сбора данных — цепочка не может прерваться). URL alarm исправлен на `app-service/index` (без .js). Добавлен `last_collect_time` и `collect_count` для отслеживания работы фона. Весь сбор данных в try/catch.
  - **Page улучшена:** Pending данные отправляются МГНОВЕННО при открытии (было через 12 сек). Свежая синхронизация через 3 сек (было 10). Показывает отдельно «Отправлено: HH:MM» и «Фон: HH:MM (ожидает отправки) [N]». Оранжевый цвет для pending статуса.
  - **Формат времени сна:** `start_time`/`end_time` от датчика Sleep приходят как минуты от полуночи (1341 = 22:21, 1902 = 7:42). Добавлена конвертация `_minutes_to_hhmm()` в `amazfit.py` — теперь в БД и AI-контексте время в формате HH:MM.
  - **Архитектурное решение:** True background network sync невозможен в Zepp OS для сторонних приложений. AppService ТОЛЬКО собирает данные → localStorage. Page отправляет при открытии. Это ограничение платформы.
- **Файлы:** `zepp-app/app-service/index.js` (переписан), `zepp-app/page/index.js` (улучшен), `src/integrations/amazfit.py` (конвертация времени сна)

### 13 апреля 2026 — Данные часов доступны психологу + время засыпания/пробуждения

- **Проблема:** Психолог не видел данные часов (время сна, стресс, шаги) — не мог учитывать физиологию в анализе. Также не сохранялись время засыпания/пробуждения и оценка сна (score)
- **Решение:**
  - Вынесен `watch_context()` в общий модуль `src/core/watch.py` — используется в health, psychology и любых будущих ботах
  - `_psychology_system()` теперь подключает данные часов в system prompt
  - `process_watch_push()` сохраняет score, start_time, end_time, nap_min из данных сна
  - `watch_context()` отображает время засыпания/пробуждения для AI
- **Файлы:** `src/core/watch.py` (новый), `src/bots/health/handlers.py`, `src/bots/psychology/handlers.py`, `src/integrations/amazfit.py`
- **Примечание:** Доктор и Консультация уже использовали watch_context — теперь они тоже получают расширенные данные сна

### 13 апреля 2026 — Режим Еда: принудительная интерпретация сленга как еды

- **Проблема:** Пользователь пишет «бэпэшка» (сленг для лапши быстрого приготовления) в режиме Еда — бот не понимает и спрашивает «это еда или шутка?» вместо возврата КБЖУ
- **Решение:** Добавлено правило №11 в NUTRITIONIST_SYSTEM и правило №7 в WIFE_NUTRITIONIST_SYSTEM: в режиме Еда каждое сообщение — описание еды. Незнакомые слова интерпретируются как сленг/бренд ближайшего продукта. Запрещено переспрашивать.
- **Файлы:** `src/bots/health/prompts.py` — оба промпта нутрициолога

### 13 апреля 2026 — Расширение данных часов: 7 → 15 метрик

- **Проблема:** Часы Amazfit Balance 2 собирали только 7 базовых метрик (шаги, дистанция, калории, пульс, SpO2, стресс, сон). Не использовались: температура тела, PAI, жиросжигание, стояние, тренировки, фазы сна (REM/лёгкий), пульс покоя
- **Решение:** Расширена коллекция до 15 метрик на всех уровнях (часы → сервер → AI-контекст)

**Изменённые файлы:**
- **`zepp-app/app-service/index.js`:** `collectHealthData()` расширена — HeartRate (last/resting/avg/min/max), Stress (last + avg через getTodayByHour), Sleep (score + REM/light/awake стадии + дневной сон getNap), BodyTemperature, FatBurning, Pai (total+today), Stand, Workout (vo2Max, trainingLoad, recoveryTime)
- **`zepp-app/page/index.js`:** Идентичное расширение `collectHealthData()` для ручной отправки
- **`zepp-app/app.json`:** Новые permissions: calorie, body_temp, fat_burning, pai, stand, workout
- **`src/integrations/amazfit.py`:** `process_watch_push()` — обработка новых полей; `format_summary()` — форматирование всех 15 метрик
- **`src/bots/health/handlers.py`:** `_watch_context()` — AI-контекст расширен: дистанция, пульс покоя, оценка сна, REM/лёгкий/дневной сон, температура тела, жиросжигание, PAI, стояние, тренировка (VO₂max, нагрузка, восстановление)

### 13 апреля 2026 — Кнопка «Консультация» + оптимизация режима Еда

- **Проблема:** Вопросы по питанию (оцени, анализируй) обрабатывались в режиме Еда — подгружался 30-дневный контекст + тяжёлая модель → ответ >1 минуты вместо секунд
- **Решение:** Разделение на два независимых режима: Еда (быстрое логирование) и Консультация (глубокий анализ)

**Исправления:**
- **`src/bots/health/keyboard.py`:** Добавлен `Mode.CONSULT = "consult"`, кнопка «💬 Консультация» в reply-клавиатуре
- **`src/bots/health/handlers.py`:**
  - Новый хэндлер `mode_consult()` для кнопки «💬 Консультация» → переключает в Mode.CONSULT
  - Новая функция `_process_consult()` — 30-дневный контекст + nutrition_consult модель (DeepSeek V3.2) + 6 сообщений истории
  - `_process_food_text()` очищена: убраны `_is_question()`, `weekly_ctx`, переключение на nutrition_consult. Теперь всегда `meal_photo` (gpt-4o-mini) + 4 сообщения истории → быстрый ответ
  - `handle_text()` и voice handler: добавлена маршрутизация `Mode.CONSULT → _process_consult()`
  - `/start` приветствие обновлено — добавлена строка про «💬 Консультация»

### 13 апреля 2026 — Нутрициолог: 30-дневный контекст + авто-синх часов

- **Проблема 1:** Запросы типа «оцени мое питание за неделю» НЕ определялись как вопрос → бот не подгружал недельный контекст, обрабатывал как логирование еды
- **Проблема 2:** `_weekly_meals_context()` видел только 7 дней — мало данных для анализа трендов
- **Проблема 3:** Zepp OS app-service собирал данные с часов, но НЕ отправлял на сервер (только сохранял в `localStorage`)

**Исправления:**
- **`src/bots/health/handlers.py`:** `_QUESTION_PATTERNS` — добавлены паттерны: `оцени|проанализируй|анализ|итог|резюме|статистик|сводк|динамик|сравни|покажи|обзор|отчёт|тренд|прогресс`
- **`src/bots/health/handlers.py`:** `_weekly_meals_context()` расширена до 30 дней — детальная разбивка по дням за неделю + агрегация по неделям за месяц + общая статистика (среднее ккал/день за 30 дн.)
- **`zepp-app/app-service/index.js`:** Фоновый сервис теперь пытается отправить данные через ZML messaging (`getApp().globalData.messaging.request()`) → Side Service → `fetch`. Fallback: сохранение в `localStorage`
- **`zepp-app/app-side/index.js`:** Добавлен `onRequest` handler — принимает `push_health_data` из AppService, отправляет на сервер через `fetch`
- **`zepp-app/page/index.js`:** Добавлен `flushPending()` — при открытии приложения отправляет невыгруженные фоновые данные из `localStorage` (двойной fallback)

### 12 апреля 2026 — doctor_consult → DeepSeek V3.2
- **`src/ai/router.py`:** doctor_consult переведён с gpt-4o на deepseek/deepseek-v3.2 (fallback остаётся gpt-4o). Все задачи теперь на DeepSeek кроме meal_photo/daily_summary/general (gpt-4o-mini)
- **БД `model_routing`:** UPDATE doctor_consult → deepseek/deepseek-v3.2

### 12 апреля 2026 — Нутрициолог v2: недельный анализ + DeepSeek V3.2
- **Проблема:** Нутрициолог видел только сегодняшнее питание, не мог анализировать рацион комплексно, отписывался общими фразами на вопросы о добавках
- **`src/bots/health/handlers.py`:** Добавлена `_weekly_meals_context()` — агрегация питания за 7 дней с разбивкой по дням (КБЖУ + клетчатка + список блюд) через `get_meals_range()`. Подключается автоматически при вопросах (`_is_question() == True`)
- **`src/bots/health/handlers.py`:** `_process_food_text()` теперь при вопросах добавляет недельный контекст в system prompt. Параллельные DB-запросы через `asyncio.gather()`
- **`src/bots/health/prompts.py`:** Добавлены правила 16-20 в NUTRITIONIST_SYSTEM и 10-12 в WIFE_NUTRITIONIST_SYSTEM: анализ рациона по цифрам, запрет отписок, обязательный расчёт нутриентов по недельным данным
- **`src/ai/router.py`:** Стратегические задачи (психолог, ментор, мастер, бизнес-стратегия) переведены с Claude Sonnet 4 на DeepSeek V3.2 (в 10x дешевле: $0.26/M input vs $3/M). `nutrition_consult` тоже на DeepSeek V3.2 (вместо gpt-4o)
- **`.github/copilot-instructions.md`:** Добавлено правило: после ЛЮБЫХ изменений обновлять PROJECT_CONTEXT.md и ROADMAP.md

### 11 апреля 2026 — File Extractor + Web App (Mini App)
- **`src/integrations/obsidian/file_extractor.py`** (НОВЫЙ): Модуль извлечения текста из файлов — PDF (PyMuPDF), DOCX (python-docx), XLSX (openpyxl), CSV (stdlib), HTML (BeautifulSoup), TXT. Автоопределение кодировки (utf-8/cp1251/latin-1). Таблицы из DOCX/XLSX конвертируются в pipe-delimited текст
- **`src/integrations/obsidian/watcher.py`:** Расширен для обработки не-md файлов. Новая функция `_is_supported_file()` проверяет .md + все форматы из file_extractor. Не-md файлы → extract_text → RAG индексация (без парсинга задач). `.md` файлы работают как раньше (задачи + RAG)
- **`src/webapp/__init__.py`** (НОВЫЙ): Web App API — 6 эндпоинтов: `/api/webapp/tasks` (GET/POST), `/api/webapp/tasks/{id}/complete` (POST), `/api/webapp/goals` (GET), `/api/webapp/health` (GET), `/api/webapp/finances` (GET). Валидация Telegram initData (HMAC-SHA256). Статика из `src/webapp/static/`
- **`src/webapp/static/`** (НОВЫЙ): Telegram Mini App фронтенд — 4 таба (Задачи, Здоровье, Цели, Финансы). Задачи: создание, отметка done, фокус дня. Здоровье: калории, вода, шаги, пульс, приёмы пищи, тренировки. Цели: прогресс-бары. Финансы: долги, последние транзакции. Адаптивный дизайн под Telegram тему (CSS variables), haptic feedback
- **`src/bots/hub/keyboard.py`:** Добавлена кнопка `📊 Дашборд` с WebAppInfo в главное меню (отображается при наличии webhook_host)
- **`src/main.py`:** Интегрирован `setup_webapp_routes()` — API + статика Web App подключаются к aiohttp-приложению
- **`requirements.txt`:** Добавлены PyMuPDF>=1.24, python-docx>=1.1, openpyxl>=3.1, beautifulsoup4>=4.12
- **`docs/PROJECT_CONTEXT.md`:** Исправлено описание Audio стека: `faster-whisper (ЛОКАЛЬНЫЙ), model "medium", CPU int8` вместо ошибочного `OpenAI Whisper API`

### 11 апреля 2026 — Базы знаний (RAG): автоэкспорт, SEO, project_id
- **Автоэкспорт анализов:** `_process_doctor_photo()` (health/handlers.py) теперь после Vision AI → создаёт `.md` в `02-Knowledge/Здоровье/Анализы/` через `obsidian.log_medical_analysis()` + event `health_record` с эмбеддингом для RAG
- **`src/integrations/obsidian/writer.py`:** Добавлен `log_medical_analysis()` — экспорт расшифровки анализа в Obsidian с frontmatter (type, date, tags); `ensure_knowledge_base_structure()` — создание структуры папок для баз знаний (Здоровье, SEO, КДК, Курсы) + README для SEO
- **SEO-база:** Метод `ensure_knowledge_base_structure()` создаёт 20 папок в `02-Knowledge/Бизнес/SEO/` (Основы, Стратегии, Семантика, Инструменты, Клиенты, Кейсы, Обучение) + README.md. Все заметки автоматически индексируются watcher.py
- **RAG project_id filtering:** `_index_note_for_rag()` (watcher.py) теперь для файлов из `05-Projects/{name}/` автоматически lookup-ит project по имени через `get_project_by_name()` и ставит `project_id` на event. Новые events с project_id → `match_events()` может фильтровать по проекту
- **`src/db/queries.py`:** Добавлен `get_project_by_name()` — поиск активного проекта по имени (case-insensitive, для маппинга папок Obsidian → project_id)

### 12 апреля 2026 — Zepp OS мини-приложение + фиксы итогов дня

- **`zepp-app/`:** Создано Zepp OS мини-приложение для Amazfit Balance 2 — автоматическая отправка данных здоровья на сервер Life OS
  - `zepp-app/app-service/index.js` — фоновый AppService: сбор метрик (шаги, пульс, SpO2, стресс, сон, калории, дистанция, температура кожи) → HTTP POST `/api/watch/push` каждые N минут через `setAlarm` (battery-efficient паттерн)
  - `zepp-app/page/index.js` — UI-экран статуса на часах: последняя синхр., метрики, кнопка «Синхр. сейчас»
  - `zepp-app/config.js` — конфиг (API_KEY, SERVER_URL, INTERVAL_MINUTES) — заполнить перед сборкой
  - `zepp-app/app.json` — манифест с разрешениями на все датчики здоровья (заполнить AppID + deviceSource из developer.zepp.com)
  - `zepp-app/README.md` — пошаговая инструкция установки (8 шагов: Zepp-аккаунт → developer.zepp.com → /watch_connect → Zeus CLI → config.js → сборка → установка → проверка)
- **Поток данных часов:** Watch AppService → HTTP POST Bearer → `/api/watch/push` → `process_watch_push()` → `events` → Health-бот видит данные в контексте AI
- **`src/bots/master/handlers.py`:** Исправлен `cb_task_done` — проверяет результат `complete_task()` (был молчаливый игнор: задача считалась выполненной, но `is_done` не менялось в БД)
- **`src/bots/master/scheduler.py`:** Добавлено structured-логирование в `_send_evening_to_user()` — список задач с `is_done` для диагностики; добавлена кнопка ✅ рядом с каждой невыполненной задачей в итогах дня; вечерний обзор сдвинут с 18:00 → 21:00 MSK

### 11 апреля 2026 — Amazfit Balance 2 (замена Huawei)
- **Архитектура:** Вместо pull каждые 30 мин — часы сами POST-ят данные на `/api/watch/push` с Bearer API-ключом
- **`src/integrations/amazfit.py`:** Новый модуль — `process_watch_push()`, `generate_watch_api_key()`, `format_summary()`
- **`src/integrations/huawei_health.py`:** Удалён (заменён amazfit.py)
- **`sql/005_watch_tokens.sql`:** Таблица переделана — убраны access_token/refresh_token/expires_at, добавлены api_key (UNIQUE), push_interval_min, is_active, last_push_at
- **`src/db/queries.py`:** Новые функции — `get_watch_user_by_api_key()`, `update_watch_last_push()`. Убраны OAuth-специфичные параметры из `save_watch_token()`
- **`src/config.py`:** Убраны huawei_client_id/huawei_client_secret, добавлен amazfit_push_enabled
- **`src/bots/health/handlers.py`:** /watch_connect генерирует API-ключ (вместо OAuth2 ссылки). Убраны /watch_now и _ensure_valid_token. Добавлена температура кожи
- **`src/bots/health/scheduler.py`:** Убран pull каждые 30 мин, добавлен check_watch_stale (3 раза в день — алерт если push не приходил >2ч)
- **`src/main.py`:** Добавлен эндпоинт POST `/api/watch/push` — приём данных от часов
- **Метрики:** Добавлена температура кожи (skin_temperature) к существующим (шаги, пульс, SpO2, сон, стресс, калории, дистанция)

### 10 апреля 2026 — VPN-прокси, расписание, фиксы
- **Инфра:** На VPS установлен xray-core как VLESS Reality клиент → локальный SOCKS5 прокси (0.0.0.0:10808) через Латвию. Причина: Beget потерял маршрут до api.telegram.org (блокировка РФ)
- **main.py:** Добавлен хелпер `_make_bot()` — создаёт Bot с `AiohttpSession(proxy=...)` если задан `TELEGRAM_PROXY`
- **config.py:** Новая настройка `telegram_proxy` (env: `TELEGRAM_PROXY`), по умолчанию пустая
- **docker-compose.yml:** `extra_hosts: host.docker.internal:host-gateway` для доступа из контейнера к xray на хосте
- **requirements.txt:** Добавлен `aiohttp-socks>=0.9`
- **Master Scheduler:** Вечерний обзор (Итоги дня) перенесён с 21:00 на 18:00 MSK
- **Health Scheduler:** Дневная сводка КБЖУ перенесена с 21:00 на 21:30 MSK
- **Health:** Режим Еда — при вопросах/уточнениях бот теперь отвечает нормально вместо «опишите еду в JSON»
- **Business/Partner:** Убраны следы JSON из ответов бота — ответ форматируется на стороне кода

### 8 апреля 2026 — Долги, Таймер, Советник, Фото-подписи
- **Family:** Добавлен раздел 💳 Долги и кредиты — полный CRUD (создание, оплата /pay, закрытие /close_debt, удаление /del_debt). AI парсит текстовое описание долга в структуру (тип, сумма, ставка, платёж, срок)
- **Family:** Добавлен 🧠 AI Финансовый советник — сбор всех данных (текущий/прошлый месяц, долги, лимиты) → gpt-4o → персональные рекомендации
- **Family:** Убрана надпись «Профиль общий для здоровья и психологии» из 4 файлов
- **Family:** Исправлен silent ignore в _process_input — теперь отвечает подсказкой в нережимных состояниях
- **Business:** Перенесён ⏱ Таймер учёта рабочего времени из Family в Business
- **Business:** Добавлен scheduler — напоминания о таймере в 10:00 (начать) и 18:00 (остановить) пн-пт
- **Business:** Inline-кнопки в напоминаниях: `[▶️ Начать сейчас]` `[🕐 Указать время]` / `[⏹ Остановить]` `[🕐 Указать время]`
- **Business:** Поддержка ретроактивного времени: `/work 9:30`, `/stop 16:00` — парсинг HH:MM
- **Business:** Таймер и кнопка ⏱ скрыты от партнёра (contextvars → main_keyboard, guard на /work /stop /workstats)
- **Health:** Фото-подписи учитываются при анализе еды — caption передаётся в Vision API с префиксом «Подпись пользователя:»
- **Health:** MEAL_PHOTO_PROMPT обновлён — подпись пользователя имеет приоритет, примеры сленга (бэпэшка = лапша быстрого приготовления)
- **DB:** queries.py — start_work_session/stop_work_session принимают custom_time (datetime | None) для ретроактивного указания времени
- **DB:** queries.py — CRUD для долгов (create_debt, get_user_debts, pay_debt, close_debt, delete_debt, get_debts_summary)
- **SQL:** 005_debts.sql — таблица debts; 006_work_sessions.sql — таблица work_sessions
- **Docs:** Обновлены FULL_GUIDE.md, ROADMAP.md. Таймер перенесён из Family в Business

### Июнь 2026 — Единый бот-хаб (Unified Bot)
- **Hub:** Новый модуль `src/bots/hub/` — Section (StrEnum), SectionFilter (BaseFilter), главное меню 4×2
- **Hub:** /start → главное меню с секциями, кнопка «🏠 Меню» для возврата, catch-all для текста без секции
- **Config:** `BOT_TOKEN_UNIFIED` — если задан, все 8 секций работают в одном боте. Остальные токены необязательны
- **ACL:** unified-режим — проверка is_active, доступ к секциям проверяется в hub при переключении
- **main.py:** `_collect_unified()` — hub-роутер первым (приоритет /start, 🏠 Меню), SectionFilter динамически на секционных роутерах
- **main.py:** Поддержка unified в polling + webhook режимах, graceful shutdown, schedulers
- **Backward compat:** Legacy multi-bot режим работает без изменений если `BOT_TOKEN_UNIFIED` не задан
- **Docs:** Обновлены ROADMAP.md, implementation_plan.md (Фаза 11), PROJECT_CONTEXT.md, FULL_GUIDE.md

### Апрель 2026 (обновление: Планировщик + Obsidian)
- **Master:** Добавлен планировщик задач — кнопка 📋 Задачи с inline-управлением (done/undo/overdue/reschedule/delete)
- **Master:** Команды /task, /week, /done для быстрой работы с задачами
- **Master:** Утренний брифинг (08:00 MSK) — задачи на день, просроченные, фокус по целям
- **Master:** Вечерний обзор (21:00 MSK) — итоги дня, незакрытые задачи с кнопками переноса
- **Master:** Напоминания о задачах — каждую минуту проверка pending_task_reminders
- **Master:** Добавление задач через LLM-парсинг (текст/голос → дата, время, приоритет)
- **DB:** Таблица `tasks` (sql/002_add_tasks.sql) — планировщик задач (Telegram + будущая Obsidian-интеграция)
- **DB:** 12 новых queries: create_task, complete_task, get_today_tasks, get_week_tasks, get_overdue_tasks и др.
- **Config:** Добавлены obsidian_vault_path, obsidian_sync_enabled, obsidian_watch_enabled (выключены по умолчанию)
- **Docs:** План интеграции Obsidian (docs/obsidian_integration_plan.md)

### Апрель 2026 (обновление: Obsidian интеграция — Фазы 9.0–9.4)
- **Obsidian:** Vault создан (`C:\Users\Alexey\ObsidianVault\LifeOS\`), структура Zettelkasten, шаблоны Daily/Meeting, MOC-дашборды
- **Syncthing:** Двусторонняя синхронизация VPS ↔ PC (Docker-контейнер + Windows), автостарт настроен
- **Obsidian Writer:** `src/integrations/obsidian/writer.py` — запись данных из ботов в .md файлы (Daily Notes, Inbox)
  - `log_meal()`, `log_workout()`, `log_finance()` → секции Daily Note (`<!-- sync:health/workout/finances -->`)
  - `log_diary()`, `log_idea()` → `00-Inbox/` заметки
  - `log_task_to_daily()` → задачи в формате Tasks-плагина
  - `complete_task_in_md()` / `uncomplete_task_in_md()` → обновление `- [ ]` ↔ `- [x] ✅ дата` в .md
- **Obsidian Watcher:** `src/integrations/obsidian/watcher.py` — watchdog-мониторинг .md файлов, парсинг задач → upsert в БД
- **Obsidian Task Parser:** `src/integrations/obsidian/task_parser.py` — парсинг формата Tasks-плагина (📅 дата, ⏰ время, 🔴🟡🟢⚪ приоритет)
- **DB:** Таблица `obsidian_tasks` (sql/003_obsidian_tasks.sql), queries: upsert_obsidian_task, get_obsidian_pending_reminders, get_obsidian_today_tasks
- **Master:** Кнопка 📋 Задачи теперь показывает и Obsidian-задачи (секция «Из Obsidian»)
- **Master:** Scheduler — напоминания о задачах из Obsidian (каждую минуту)
- **Двусторонняя синхронизация (9.4):** Telegram `/done` → обновляет .md файл; отметка `[x]` в Obsidian → watcher обновляет БД
- **Интеграция в ботах:** health, business, mentor, psychology, master → вызывают obsidian writer после create_event

### Апрель 2026
- **Health:** STATELESS архитектура — ноль conversation history, устранена причина накопления калорий
- **Health:** Полноценный нутрициолог — health_score (1-10), цветные вердикты (🟢🟡🔴), клетчатка, советы, статус дня
- **Health:** Персональные настройки (system_prompt_overrides) подгружаются в промпт
- **Health:** Карточка блюда строится из json_data, не из текста LLM
- **Health:** LLM никогда не спрашивает вес — стандартная порция
- **Health:** Event создаётся ТОЛЬКО при наличии json_data с КБЖУ
- **Health:** Очищена таблица conversations от health-данных
- **Health:** Добавлены недельная и месячная сводки (scheduler)
- **Psychology:** Кросс-бот контекст — get_life_profile() для assets данных
- **Business:** Per-project промпты через metadata.system_prompt
- **Business:** Переключён на gpt-4o (task_type=business_strategy, без free fallback)
- **Master:** Добавлено управление промптами (📋, /set_prompt, /clear_prompt)
- **Deploy:** GitHub Actions CI/CD настроен (SSH на /opt/life-os)
- **Utils:** Добавлен safe_send для scheduler-отправки
- **DB:** Добавлены get_meals_range, get_today_messages, get_life_profile, update_project_metadata
- **Health:** Добавлен режим 🩺 Доктор — личный врач-терапевт на gpt-4o (критичная, без free fallback)
- **Health:** Доктор видит питание, тренировки, профиль пользователя (болезни, лекарства), использует историю диалога
- **Health:** Доктор принимает фото анализов и симптомов (тоже gpt-4o vision)
- **Health+Psychology:** Глобальный профиль пользователя 📋 Мой профиль — общий между ботами, с отображением текущего профиля и возможностью обновления
- **AI Router:** `doctor_consult` добавлен в critical tasks (всегда gpt-4o, нет free fallback)
- **Free models:** Обнаружено: бесплатные Llama модели стабильно фейлятся, все запросы идут через gpt-4o-mini ($0.08/105 запросов)
- **AI Router:** Бесплатные модели полностью отключены — удалены FREE_MODEL_MAP, _pick_model, счётчики. chat() всегда использует платную модель.
- **Master:** AI Панель обновлена — убрана информация о бесплатных лимитах
- **Psychology:** Промпты полностью переписаны с учётом КПТ + ACT + мотивационное интервьюирование, urge surfing, radical acceptance
- **Psychology:** Добавлена интеграция целей пользователя ({user_goals}) — мечты, годовые цели, привычки с прогрессом
- **Psychology:** DIARY_PROMPT — стиль «терапевтические пометки на полях дневника», без списков/шаблонов
- **Psychology:** RETROSPECTIVE_PROMPT — структура с emoji (📊🔄🎯🛠), сверка с компасом (глобальные цели)
- **Health:** Добавлен WIFE_NUTRITIONIST_SYSTEM — отдельный промпт нутрициолога для жены (нормы для женщин)
- **Health:** handlers определяет role=wife через _is_wife() и подставляет соответствующий промпт
