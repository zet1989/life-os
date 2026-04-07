# Life OS — План реализации

---

## Структура проекта

```
life-os/
├── docker-compose.yml
├── .env.example
├── alembic/                    # миграции БД
│   └── versions/
├── sql/                        # начальные SQL-скрипты для Supabase
│   └── 001_init_schema.sql
├── src/
│   ├── __init__.py
│   ├── main.py                 # точка входа, запуск всех ботов
│   ├── config.py               # Pydantic Settings, загрузка .env
│   ├── db/
│   │   ├── __init__.py
│   │   ├── supabase_client.py  # инициализация Supabase
│   │   ├── models.py           # dataclasses/TypedDict для таблиц
│   │   └── queries.py          # SQL-запросы (события, финансы, цели)
│   ├── ai/
│   │   ├── __init__.py
│   │   ├── router.py           # OpenRouter клиент + выбор модели
│   │   ├── whisper.py          # транскрипция аудио
│   │   ├── vision.py           # анализ фото
│   │   ├── embeddings.py       # генерация эмбеддингов для RAG
│   │   └── rag.py              # семантический поиск по pgvector
│   ├── core/
│   │   ├── __init__.py
│   │   ├── acl.py              # проверка прав доступа
│   │   ├── context.py          # управление контекстом диалога
│   │   ├── scheduler.py        # APScheduler: напоминания, аудиты
│   │   └── media.py            # загрузка файлов в Supabase Storage
│   ├── bots/
│   │   ├── __init__.py
│   │   ├── base.py             # базовый класс/миксин для всех ботов
│   │   ├── health/             # Этап 1: Нутрициолог + Тренер
│   │   │   ├── __init__.py
│   │   │   ├── bot.py
│   │   │   ├── handlers.py
│   │   │   └── prompts.py
│   │   ├── assets/             # Этап 2: Дом + Авто
│   │   │   ├── __init__.py
│   │   │   ├── renovation_bot.py
│   │   │   ├── garage_bot.py
│   │   │   └── handlers.py
│   │   ├── business/           # Этап 3: Мульти-проектный
│   │   │   └── ...
│   │   ├── partner/            # Этап 4a: Партнёрский учёт (группа)
│   │   │   └── ...
│   │   ├── mentor/             # Этап 4b: Бизнес-ментор (стратег)
│   │   │   └── ...
│   │   ├── family/             # Этап 4c: Семейный бюджет
│   │   │   └── ...
│   │   ├── psychology/         # Этап 5: Психолог + Дневник
│   │   │   └── ...
│   │   └── master/             # Этап 6: Главный ментор
│   │       └── ...
│   └── utils/
│       ├── __init__.py
│       ├── cost_tracker.py     # логирование расходов на API
│       └── telegram_helpers.py # вспомогательные функции Telegram
├── tests/
│   ├── test_acl.py
│   ├── test_queries.py
│   └── test_ai_router.py
├── requirements.txt
└── README.md
```

---

## Схема БД (Supabase SQL)

```sql
-- Расширенная схема (дополнения к ТЗ выделены комментариями)

CREATE TABLE users (
    user_id BIGINT PRIMARY KEY,          -- Telegram ID
    username TEXT,                         -- @username для удобства
    display_name TEXT,                     -- ДОБАВЛЕНО: имя для отчётов
    role TEXT NOT NULL DEFAULT 'admin',
    permissions JSONB DEFAULT '{}',
    system_prompt_overrides TEXT,
    timezone TEXT DEFAULT 'Europe/Moscow', -- ДОБАВЛЕНО
    is_active BOOLEAN DEFAULT TRUE,       -- ДОБАВЛЕНО
    created_at TIMESTAMPTZ DEFAULT NOW(),  -- ДОБАВЛЕНО
    last_active_at TIMESTAMPTZ            -- ДОБАВЛЕНО
);

CREATE TABLE projects (
    project_id SERIAL PRIMARY KEY,        -- SERIAL вместо ручного ID
    name TEXT NOT NULL,
    type TEXT NOT NULL,                    -- solo, partnership, family, asset
    status TEXT DEFAULT 'active',
    owner_id BIGINT REFERENCES users(user_id),
    collaborators BIGINT[] DEFAULT '{}',  -- telegram_id партнёров с доступом
    metadata JSONB DEFAULT '{}',          -- VIN авто, адрес дома...
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE goals (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id),
    type TEXT NOT NULL,                   -- dream, yearly_goal, habit_target
    title TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'active',
    target_date DATE,                     -- ДОБАВЛЕНО: дедлайн
    progress_pct SMALLINT DEFAULT 0,      -- ДОБАВЛЕНО: % выполнения
    parent_goal_id INT REFERENCES goals(id), -- ДОБАВЛЕНО: иерархия целей
    created_at TIMESTAMPTZ DEFAULT NOW(),
    achieved_at TIMESTAMPTZ              -- ДОБАВЛЕНО
);

CREATE TABLE events (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    user_id BIGINT REFERENCES users(user_id),
    project_id INT REFERENCES projects(project_id),
    bot_source TEXT,                       -- ДОБАВЛЕНО: health, garage, renovation, master...
    event_type TEXT NOT NULL,
    raw_text TEXT,
    json_data JSONB,
    media_url TEXT,
    embedding vector(1536),               -- ДОБАВЛЕНО: вектор прямо в таблице (pgvector)
    is_processed BOOLEAN DEFAULT TRUE     -- ДОБАВЛЕНО
);

CREATE TABLE finances (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    project_id INT REFERENCES projects(project_id),
    user_id BIGINT REFERENCES users(user_id),
    transaction_type TEXT NOT NULL,       -- income, expense
    amount NUMERIC(12,2) NOT NULL,
    currency TEXT DEFAULT 'RUB',          -- ДОБАВЛЕНО
    category TEXT NOT NULL,
    description TEXT,
    receipt_url TEXT,                      -- ДОБАВЛЕНО: ссылка на фото чека
    source_event_id BIGINT REFERENCES events(id) -- ДОБАВЛЕНО: связь с событием
);

-- НОВЫЕ ТАБЛИЦЫ:

CREATE TABLE conversations (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id),
    bot_source TEXT NOT NULL,
    role TEXT NOT NULL,                   -- system, user, assistant
    content TEXT NOT NULL,
    tokens_used INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);
CREATE INDEX idx_conv_user_bot ON conversations(user_id, bot_source, created_at DESC);

CREATE TABLE api_costs (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    user_id BIGINT,
    bot_source TEXT,
    model TEXT NOT NULL,
    tokens_in INT,
    tokens_out INT,
    cost_usd NUMERIC(8,6),
    task_type TEXT                        -- meal_photo, transcription, embedding...
);

CREATE TABLE reminders (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id),
    bot_source TEXT,
    message TEXT NOT NULL,
    cron_expression TEXT,                 -- '0 9 * * *' = каждый день в 9:00
    next_fire_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE model_routing (
    id SERIAL PRIMARY KEY,
    task_type TEXT UNIQUE NOT NULL,       -- meal_photo, diary, financial_parse...
    model TEXT NOT NULL,                  -- gpt-4o-mini, claude-3.5-sonnet...
    max_tokens INT DEFAULT 1000,
    temperature NUMERIC(2,1) DEFAULT 0.5,
    fallback_model TEXT                   -- запасная модель
);

-- Индексы для производительности
CREATE INDEX idx_events_user_type ON events(user_id, event_type, timestamp DESC);
CREATE INDEX idx_events_project ON events(project_id, timestamp DESC);
CREATE INDEX idx_finances_project ON finances(project_id, timestamp DESC);
CREATE INDEX idx_goals_user ON goals(user_id, status);
```

---

## Чеклист реализации

### Фаза 0: Фундамент (без этого не стартовать)
- [x] **0.1** Создать репозиторий, структуру папок, `.env.example`, `requirements.txt`
- [x] **0.2** `config.py` — Pydantic Settings, загрузка и валидация всех переменных окружения
- [x] **0.3** Supabase: создать проект, выполнить SQL-схему (все таблицы выше)
- [x] **0.4** `supabase_client.py` — инициализация клиента, проверка соединения
- [x] **0.5** `main.py` — запуск одного aiogram 3 бота (Long Polling), команда /start с проверкой ACL
- [x] **0.6** `acl.py` — middleware: проверка user_id в таблице users, отсечение неизвестных
- [x] **0.7** `queries.py` — базовые CRUD: create_event, get_user, update_user_settings
- [x] **0.8** Docker Compose: бот + .env → `docker compose up` работает

### Фаза 1: AI-слой и мультимодальность
- [x] **1.1** `router.py` — OpenRouter клиент: отправка промпта, получение ответа, retry с tenacity
- [x] **1.2** `model_routing` — заполнить таблицу маршрутизации моделей, функция выбора модели по task_type
- [x] **1.3** `cost_tracker.py` — логирование каждого вызова LLM в таблицу api_costs
- [x] **1.4** `whisper.py` — приём voice-сообщений, скачивание .ogg, отправка в Whisper API, возврат текста
- [x] **1.5** `vision.py` — приём фото, загрузка в Supabase Storage, отправка URL в gpt-4o vision
- [x] **1.6** `context.py` — загрузка последних N сообщений из conversations, формирование messages[]
- [x] **1.7** `embeddings.py` — генерация эмбеддингов через `text-embedding-3-small`
- [x] **1.8** `rag.py` — семантический поиск: запрос → embedding → SQL `<=>` по pgvector → top-5 результатов

### Фаза 2: Этап 1 — Нутрициолог и Тренер
- [x] **2.1** Бот health: создать токен в BotFather, добавить в мульти-бот архитектуру
- [x] **2.2** Два юзера: Алексей (admin) + жена (wife, permissions={"bots": ["health"]}), user_id-фильтрация всех данных
- [x] **2.3** Хэндлер фото еды: фото → vision → КБЖУ JSON → event + финансы (если чек)
- [x] **2.4** Хэндлер текста/голоса тренировки: парсинг упражнений → event
- [x] **2.5** Reply-клавиатура: [🍽 Еда] [🏋️ Тренировка] [⚙️ Настройки]
- [x] **2.6** Команда /settings — обновление system_prompt_overrides (калории, диета, витамины) для каждого user_id
- [x] **2.7** Ежедневная сводка КБЖУ (APScheduler, вечером) — каждому пользователю отдельно

### Фаза 3: Этап 2 — Дом и Авто
- [x] **3.1** Бот assets: токен, хэндлеры, инлайн-кнопки [Замер|Чек|ТО|Запчасть]
- [x] **3.2** Хэндлер голосового замера → транскрипция → RAG embedding → event (renovation)
- [x] **3.3** Хэндлер фото чека стройматериалов → vision OCR → finances (house)
- [x] **3.4** Хэндлер бортжурнала авто: голос/текст → RAG embedding → event (auto_maintenance)
- [x] **3.5** Хэндлер фото запчасти/заказ-наряда → vision → finances (auto_service/auto_parts)
- [x] **3.6** RAG-запросы: "когда менял масло?", "какие сайлентблоки ставил?"
- [x] **3.7** Напоминания по пробегу: промпт auto_metadata из projects.metadata

### Фаза 4: Этап 3 — Мульти-проектный бизнес-бот
- [x] **4.1** Бот business: токен, reply-клавиатура [Идея|Задача|Проекты|Отчёт]
- [x] **4.2** /add_project, /archive_project — управление через чат
- [x] **4.3** Инлайн-кнопки выбора проекта при отправке идеи/задачи
- [x] **4.4** Финансовый отчёт по проекту: SQL SUM(amount) GROUP BY category
- [x] **4.5** RAG по бизнес-идеям: поиск ранее записанных мыслей

### Фаза 5: Этап 4 — Совместные боты

**5A. Бот partner (Опердир — операционный учёт бизнес-партнёрства)**
- [x] **5.1** Бот partner: токен, настройка для групповых чатов, reply-клавиатура [Расход|Доход|Проекты|Отчёт]
- [x] **5.2** SQL: миграция `collaborators BIGINT[]` в projects, RPC `get_accessible_projects`
- [x] **5.3** ACL: партнёр видит только partnership-проекты, в которых он collaborator; RAG изолирован по project_id
- [x] **5.4** /add_project, /archive_project, /add_partner — управление партнёрскими проектами
- [x] **5.5** Инлайн-кнопки выбора проекта при записи расхода/дохода
- [x] **5.6** Парсинг расходов/доходов из текста/голоса → finances (LLM парсит текст, SQL считает итоги)
- [x] **5.7** Отчёт прибыльности по проекту: доходы − расходы по категориям (SQL only)
- [x] **5.8** Privacy mode: бот реагирует только на @упоминание или reply в групповых чатах

**5B. Бот mentor (Бизнес-Ментор — стратегический AI-коуч)**
- [x] **5.9** Бот mentor: токен, промпт стратегического бизнес-коуча, reply-клавиатура [💡 Идея|🎙 Обсуждение|📊 Аналитика|📁 Проекты|❓ Спросить]
- [x] **5.10** ACL: тот же фильтр partnership-проектов через `collaborators` (оба партнёра видят одни проекты)
- [x] **5.11** Запись бизнес-идей: текст/голос → LLM структурирует (суть, потенциал, первый шаг) → Inline выбор проекта → events + RAG embedding + сопоставление с прошлыми идеями
- [x] **5.12** Анализ обсуждений: длинное аудио → Whisper → LLM генерирует саммари + решения + экшен-айтемы → events + RAG embedding
- [x] **5.13** Стратегическая память (RAG): поиск по идеям, обсуждениям, решениям с фильтром по project_id
- [x] **5.14** Финансовая стратегия: SQL-данные (доходы, расходы, маржа) → LLM анализирует тренды + рекомендации по прибыли
- [x] **5.15** Отчёт за период: финансы (SQL) + ключевые решения (RAG) + рекомендации

**5C. Бот family (Семейный бюджет)**
- [x] **5.16** Бот family: токен, промпт семейного бухгалтера, reply-клавиатура [💰 Расход|💵 Доход|📊 Отчёт|📈 Категории|⚙️ Настройки]
- [x] **5.17** ACL: жена (wife) получает доступ permissions={"bots": ["health", "family"]}; family-проекты через collaborators
- [x] **5.18** Парсинг расходов/доходов: текст/голос → LLM парсит (сумма, категория, описание) → finances
- [x] **5.19** Фото чека → Vision OCR → авто-категоризация и сумма → finances
- [x] **5.20** Отчёт за период: доход − расход = баланс по категориям (SQL only)
- [x] **5.21** Топ категорий: "Куда ушли деньги?" → SQL GROUP BY category + сортировка
- [x] **5.22** Бюджетные лимиты по категориям (хранятся в projects.metadata) + предупреждение при приближении/превышении
- [x] **5.23** Privacy mode (если в группе): реагирует только на @упоминание или reply

### Фаза 6: Этап 5 — Психолог и Дневник
- [x] **6.1** Бот psychology: токен, промпт профессионального психолога
- [x] **6.2** Хэндлер дневника: текст/голос → events + RAG embedding
- [x] **6.3** Трекинг привычек: inline-кнопки [✅ Не курил] [❌ Сорвался] → events
- [x] **6.4** Ретроспектива: "Как я себя чувствовал на прошлой неделе?" → RAG поиск

### Фаза 7: Этап 6 — Master Intelligence
- [x] **7.1** Бот master: главный пульт, reply-клавиатура из ТЗ
- [x] **7.2** Хранитель Видения: перед ответом SELECT goals WHERE status='active' → добавить в system prompt
- [x] **7.3** Перекрёстный доступ к RAG всех ботов (с фильтром по user_id)
- [x] **7.4** Ежемесячный аудит (cron 1-го числа): SQL-сводка финансов + спорт + прогресс целей
- [x] **7.5** Финансовая панорама: агрегация ВСЕХ финансов (solo + partnership + family + assets) = полная картина жизни
- [x] **7.6** Проактивные подсказки: "Эта идея приближает тебя к цели X" / "Это отвлечение"

### Фаза 8: Продакшен и полировка
- [x] **8.1** Переход на Webhooks + nginx + SSL
- [x] **8.2** Structured logging (structlog) → мониторинг
- [x] **8.3** Health-check эндпоинт /status
- [x] **8.4** Graceful shutdown: on_shutdown хук сохраняет состояние
- [x] **8.5** Бюджетный лимитер API-расходов (daily/monthly cap)
- [x] **8.6** Команда /export — выгрузка данных юзера в JSON
- [x] **8.7** Grafana / matplotlib графики трендов

### Фаза 9: Интеграция Obsidian (ожидает ручной настройки)
- [ ] **9.0** Подготовка инфраструктуры — Obsidian Vault, шаблоны, плагины (ручная)
- [ ] **9.1** Syncthing — синхронизация VPS ↔ ноутбук (ручная)
- [ ] **9.2** Telegram → Obsidian — writer-модуль, экспорт данных в .md
- [ ] **9.3** Obsidian → Telegram — watcher + парсер задач + напоминания
- [ ] **9.4** Двусторонняя синхронизация задач
- [ ] **9.5** RAG-интеграция с Obsidian-заметками
- [x] **9.6** Конфигурация (obsidian_vault_path, sync_enabled, watch_enabled)

### Фаза 10: Ежедневный планировщик (Daily Planner) ✅
- [x] **10.1** Модель данных — таблица `tasks`, 12 CRUD-запросов в queries.py
- [x] **10.2** Telegram-интерфейс — кнопка «📋 Задачи», inline-управление, `/task`, `/week`, `/done`
- [x] **10.3** Утренний брифинг (08:00), вечерний обзор (21:00), напоминания по минутам
- [ ] **10.4** Синхронизация Planner ↔ Obsidian (зависит от Фазы 9)

---

## Технические решения

### Выбор embedding-модели
| Модель | Цена/1M токенов | Размерность | Рекомендация |
|--------|-----------------|-------------|--------------|
| text-embedding-3-small | $0.02 | 1536 (или 512) | **Основная** — дёшево, хорошее качество |
| text-embedding-3-large | $0.13 | 3072 | Если качество поиска недостаточно |

### Оценка расходов на API (месяц)
| Компонент | Объём | Модель | Ориентир $/мес |
|-----------|-------|--------|----------------|
| Фото еды (Vision) | 60 фото | gpt-4o-mini | ~$1.5 |
| Текстовые диалоги | 500 сообщений | gpt-4o-mini | ~$0.5 |
| Глубокий анализ | 30 запросов | claude-3.5-sonnet | ~$3 |
| Whisper (аудио) | 60 мин | whisper-1 | ~$0.36 |
| Whisper (обсуждения mentor) | 120 мин | whisper-1 | ~$0.72 |
| Mentor (стратегия, идеи) | 60 запросов | claude-3.5-sonnet | ~$6 |
| Family (семейный бюджет) | 200 сообщений | gpt-4o-mini | ~$0.3 |
| Embeddings | 600 записей | embedding-3-small | ~$0.01 |
| **Итого** | | | **~$13-18/мес** |

### Приоритет зависимостей (requirements.txt)
```
aiogram>=3.4
supabase>=2.0
httpx>=0.27
openai>=1.30
pydantic-settings>=2.0
tenacity>=8.0
apscheduler>=3.10
structlog>=24.0
python-dotenv>=1.0
```

---

## Риски

| Риск | Вероятность | Решение |
|------|-------------|---------|
| OpenRouter API недоступен | Средняя | Fallback на прямой OpenAI API |
| Supabase Free Tier лимиты (500MB, 50K строк) | Высокая через 6 мес | Мониторить, мигрировать на Pro ($25/мес) при необходимости |
| LLM галлюцинирует цифры финансов | Высокая | Финансы ВСЕГДА через SQL, НИКОГДА через LLM |
| Потеря данных при деплое | Средняя | Supabase daily backup (встроено), + ежемесячный /export |
| Scope creep (расползание скоупа) | Очень высокая | Строго по фазам. Не начинать Фазу N+1 пока N не работает стабильно |
| Сложность мульти-ботов | Средняя | Начать с 1 бота (health), добавлять по одному |
