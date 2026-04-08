# Life OS — Полная проектная документация

> **Последнее обновление:** 8 апреля 2026
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
| Audio | OpenAI Whisper API | — |
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
| doctor_consult | gpt-4o | 2000 | Медицинские консультации, анализы (критичная, без free fallback) |
| workout_parse | gpt-4o-mini | 500 | Парсинг тренировки |
| business_strategy | gpt-4o | 2000 | Бизнес-стратегия (критичная, без free fallback) |
| diary_reflection | claude-3.5-sonnet | 1500 | Психология - дневник |
| mentor_discussion | claude-3.5-sonnet | 3000 | Ментор - анализ обсуждений |
| daily_summary | gpt-4o-mini | 800 | Дневная сводка КБЖУ |
| general_chat | gpt-4o-mini | 1000 | Общий чат |

### 6.2 Бюджеты

- Daily API limit: $2.0
- Monthly API limit: $20.0
- Ожидаемый расход: ~$13-18/мес
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
| `src/ai/router.py` | OpenRouter клиент, model routing, tenacity retry, critical tasks (business_strategy, doctor_consult) |
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
