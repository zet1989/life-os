-- Life OS: начальная схема БД
-- Автоматически выполняется при первом запуске PostgreSQL в Docker

-- Расширение для pgvector (семантический поиск)
CREATE EXTENSION IF NOT EXISTS vector;

-- =========================================
-- Основные таблицы
-- =========================================

CREATE TABLE users (
    user_id BIGINT PRIMARY KEY,             -- Telegram ID
    username TEXT,                            -- @username
    display_name TEXT,                        -- имя для отчётов
    role TEXT NOT NULL DEFAULT 'admin',       -- admin, wife, partner
    permissions JSONB DEFAULT '{}',           -- {"bots": ["health"], "projects": ["cleaning"]}
    system_prompt_overrides TEXT,             -- динамические настройки (диета, калории)
    timezone TEXT DEFAULT 'Europe/Moscow',
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    last_active_at TIMESTAMPTZ
);

CREATE TABLE projects (
    project_id SERIAL PRIMARY KEY,
    name TEXT NOT NULL,
    type TEXT NOT NULL,                       -- solo, partnership, family, asset
    status TEXT DEFAULT 'active',             -- active, paused, archived
    owner_id BIGINT REFERENCES users(user_id),
    collaborators BIGINT[] DEFAULT '{}',     -- telegram_id партнёров с доступом
    metadata JSONB DEFAULT '{}',             -- VIN авто, адрес дома, текущий пробег...
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE goals (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id),
    type TEXT NOT NULL,                       -- dream, yearly_goal, habit_target
    title TEXT NOT NULL,
    description TEXT,
    status TEXT DEFAULT 'active',             -- active, achieved
    target_date DATE,
    progress_pct SMALLINT DEFAULT 0 CHECK (progress_pct BETWEEN 0 AND 100),
    parent_goal_id INT REFERENCES goals(id),
    created_at TIMESTAMPTZ DEFAULT NOW(),
    achieved_at TIMESTAMPTZ
);

CREATE TABLE events (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    user_id BIGINT REFERENCES users(user_id),
    project_id INT REFERENCES projects(project_id),
    bot_source TEXT,                           -- health, garage, renovation, master, psychology
    event_type TEXT NOT NULL,                  -- meal, workout, thought, business_task, measurement, auto_maintenance, diary, habit
    raw_text TEXT,
    json_data JSONB,
    media_url TEXT,
    embedding vector(1536),
    is_processed BOOLEAN DEFAULT TRUE
);

CREATE TABLE finances (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    project_id INT REFERENCES projects(project_id),
    user_id BIGINT REFERENCES users(user_id),
    transaction_type TEXT NOT NULL,            -- income, expense
    amount NUMERIC(12,2) NOT NULL,
    currency TEXT DEFAULT 'RUB',
    category TEXT NOT NULL,                    -- materials, marketing, salary, taxes, auto_parts, auto_service
    description TEXT,
    receipt_url TEXT,
    source_event_id BIGINT REFERENCES events(id)
);

-- =========================================
-- Служебные таблицы
-- =========================================

CREATE TABLE conversations (
    id BIGSERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id),
    bot_source TEXT NOT NULL,
    role TEXT NOT NULL,                        -- system, user, assistant
    content TEXT NOT NULL,
    tokens_used INT,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE api_costs (
    id BIGSERIAL PRIMARY KEY,
    timestamp TIMESTAMPTZ DEFAULT NOW(),
    user_id BIGINT,
    bot_source TEXT,
    model TEXT NOT NULL,
    tokens_in INT,
    tokens_out INT,
    cost_usd NUMERIC(8,6),
    task_type TEXT                             -- meal_photo, transcription, embedding, diary
);

CREATE TABLE reminders (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id),
    bot_source TEXT,
    message TEXT NOT NULL,
    cron_expression TEXT,                      -- '0 9 * * *' = каждый день в 9:00
    next_fire_at TIMESTAMPTZ,
    is_active BOOLEAN DEFAULT TRUE,
    created_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE TABLE model_routing (
    id SERIAL PRIMARY KEY,
    task_type TEXT UNIQUE NOT NULL,
    model TEXT NOT NULL,
    max_tokens INT DEFAULT 1000,
    temperature NUMERIC(2,1) DEFAULT 0.5,
    fallback_model TEXT
);

-- =========================================
-- Индексы
-- =========================================

CREATE INDEX idx_conv_user_bot ON conversations(user_id, bot_source, created_at DESC);
CREATE INDEX idx_events_user_type ON events(user_id, event_type, timestamp DESC);
CREATE INDEX idx_events_project ON events(project_id, timestamp DESC);
CREATE INDEX idx_finances_project ON finances(project_id, timestamp DESC);
CREATE INDEX idx_goals_user ON goals(user_id, status);

-- =========================================
-- Планировщик задач (Obsidian + Telegram)
-- =========================================

CREATE TABLE tasks (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id),
    task_text TEXT NOT NULL,
    source TEXT DEFAULT 'telegram',          -- telegram, obsidian
    source_file TEXT,                         -- путь к .md файлу (для Obsidian)
    due_date DATE,
    due_time TIME,                            -- NULL если без точного времени
    priority TEXT DEFAULT 'normal',           -- low, normal, high, urgent
    project_id INT REFERENCES projects(project_id),
    is_done BOOLEAN DEFAULT FALSE,
    reminder_sent BOOLEAN DEFAULT FALSE,
    recurrence TEXT DEFAULT NULL,             -- NULL, daily, weekly, monthly, weekdays
    recurrence_parent_id INT REFERENCES tasks(id),
    done_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX idx_tasks_user_date ON tasks(user_id, due_date)
    WHERE is_done = FALSE;
CREATE INDEX idx_tasks_reminders ON tasks(due_date, due_time)
    WHERE is_done = FALSE AND reminder_sent = FALSE;

-- =========================================
-- RPC-функции
-- =========================================

-- Семантический поиск по событиям (RAG)
CREATE OR REPLACE FUNCTION match_events(
    query_embedding vector(1536),
    match_count INT DEFAULT 5,
    p_user_id BIGINT DEFAULT NULL,
    p_project_id INT DEFAULT NULL
)
RETURNS TABLE (
    id BIGINT,
    timestamp TIMESTAMPTZ,
    user_id BIGINT,
    project_id INT,
    bot_source TEXT,
    event_type TEXT,
    raw_text TEXT,
    json_data JSONB,
    similarity FLOAT
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT
        e.id, e.timestamp, e.user_id, e.project_id,
        e.bot_source, e.event_type, e.raw_text, e.json_data,
        1 - (e.embedding <=> query_embedding) AS similarity
    FROM events e
    WHERE e.embedding IS NOT NULL
      AND (p_user_id IS NULL OR e.user_id = p_user_id)
      AND (p_project_id IS NULL OR e.project_id = p_project_id)
    ORDER BY e.embedding <=> query_embedding
    LIMIT match_count;
END;
$$;

-- Суммарные расходы на API за период (для budget limiter)
CREATE OR REPLACE FUNCTION sum_api_costs(p_since TIMESTAMPTZ)
RETURNS NUMERIC
LANGUAGE plpgsql
AS $$
DECLARE
    total NUMERIC;
BEGIN
    SELECT COALESCE(SUM(cost_usd), 0) INTO total
    FROM api_costs
    WHERE timestamp >= p_since;
    RETURN total;
END;
$$;

-- Финансовая сводка по проекту (SQL only — НИКОГДА через LLM)
CREATE OR REPLACE FUNCTION finance_summary(p_project_id INT)
RETURNS TABLE (
    transaction_type TEXT,
    category TEXT,
    total NUMERIC(12,2)
)
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT f.transaction_type, f.category, SUM(f.amount) AS total
    FROM finances f
    WHERE f.project_id = p_project_id
    GROUP BY f.transaction_type, f.category
    ORDER BY f.transaction_type, total DESC;
END;
$$;

-- Доступные проекты по типу (с учётом collaborators)
CREATE OR REPLACE FUNCTION get_accessible_projects(
    p_user_id BIGINT,
    p_type TEXT DEFAULT NULL
)
RETURNS SETOF projects
LANGUAGE plpgsql
AS $$
BEGIN
    RETURN QUERY
    SELECT p.*
    FROM projects p
    WHERE p.status = 'active'
      AND (p_type IS NULL OR p.type = p_type)
      AND (p.owner_id = p_user_id OR p_user_id = ANY(p.collaborators))
    ORDER BY p.created_at;
END;
$$;

-- =========================================
-- Начальные данные: маршрутизация моделей
-- =========================================

INSERT INTO model_routing (task_type, model, max_tokens, temperature, fallback_model) VALUES
    ('meal_photo',       'deepseek/deepseek-v3.2',  500,  0.3, 'openai/gpt-4o-mini'),
    ('workout_parse',    'deepseek/deepseek-v3.2',  500,  0.3, 'openai/gpt-4o-mini'),
    ('diary_reflection', 'deepseek/deepseek-v3.2', 1500,  0.7, 'openai/gpt-4o-mini'),
    ('financial_parse',  'deepseek/deepseek-v3.2',  300,  0.1, 'openai/gpt-4o-mini'),
    ('transcription',    'whisper-1',              NULL, NULL, NULL),
    ('rag_answer',       'deepseek/deepseek-v3.2', 1000,  0.5, 'openai/gpt-4o-mini'),
    ('vision_ocr',       'deepseek/deepseek-v3.2',  500,  0.3, 'openai/gpt-4o-mini'),
    ('general_chat',     'deepseek/deepseek-v3.2', 1000,  0.7, 'openai/gpt-4o-mini'),
    ('receipt_ocr',      'deepseek/deepseek-v3.2',  800,  0.2, 'openai/gpt-4o-mini'),
    ('order_ocr',        'deepseek/deepseek-v3.2',  800,  0.2, 'openai/gpt-4o-mini'),
    ('part_photo',       'deepseek/deepseek-v3.2',  500,  0.3, 'openai/gpt-4o-mini'),
    ('mileage_reminder', 'deepseek/deepseek-v3.2',  800,  0.5, 'openai/gpt-4o-mini'),
    ('daily_summary',    'deepseek/deepseek-v3.2',  800,  0.5, 'openai/gpt-4o-mini'),
    ('mentor_idea',      'deepseek/deepseek-v3.2', 1500,  0.7, 'openai/gpt-4o-mini'),
    ('mentor_discussion','deepseek/deepseek-v3.2', 3000,  0.5, 'openai/gpt-4o-mini'),
    ('mentor_strategy',  'deepseek/deepseek-v3.2', 2000,  0.6, 'openai/gpt-4o-mini'),
    ('mentor_report',    'deepseek/deepseek-v3.2', 2500,  0.5, 'openai/gpt-4o-mini'),
    ('family_parse',     'deepseek/deepseek-v3.2',  500,  0.2, 'openai/gpt-4o-mini'),
    ('family_receipt',   'deepseek/deepseek-v3.2',  500,  0.3, 'openai/gpt-4o-mini'),
    ('family_report',    'deepseek/deepseek-v3.2',  800,  0.5, 'openai/gpt-4o-mini'),
    ('psychology_diary', 'deepseek/deepseek-v3.2', 2000,  0.5, 'openai/gpt-4o-mini'),
    ('psychology_habit', 'deepseek/deepseek-v3.2',  300,  0.6, 'openai/gpt-4o-mini'),
    ('master_audit',     'deepseek/deepseek-v3.2', 3000,  0.5, 'openai/gpt-4o-mini'),
    ('master_talk',      'deepseek/deepseek-v3.2', 1000,  0.7, 'openai/gpt-4o-mini'),
    ('master_goal',      'deepseek/deepseek-v3.2',  500,  0.2, 'openai/gpt-4o-mini');

-- =========================================
-- Начальные данные: проекты
-- =========================================

INSERT INTO projects (name, type, owner_id, collaborators, status, metadata) VALUES
    ('House Renovation',    'asset',       1, '{}',  'active', '{"subtype": "renovation"}'),
    ('Hyundai Sonata 2006', 'asset',       1, '{}',  'active', '{"brand": "Hyundai", "model": "Sonata", "year": 2006, "assembly": "TagAZ"}'),
    ('KDK-GRUPP',           'solo',        1, '{}',  'active', '{}'),
    ('Cleaning Kostroma',   'partnership', 1, '{0}', 'active', '{}'),  -- 0 заменить на telegram_id Александра
    ('Семейный бюджет',     'family',      1, '{0}', 'active', '{"categories": ["\u043f\u0440\u043e\u0434\u0443\u043a\u0442\u044b", "\u0416\u041a\u0425", "\u0442\u0440\u0430\u043d\u0441\u043f\u043e\u0440\u0442", "\u0437\u0434\u043e\u0440\u043e\u0432\u044c\u0435", "\u043e\u0434\u0435\u0436\u0434\u0430", "\u0434\u0435\u0442\u0438", "\u0440\u0430\u0437\u0432\u043b\u0435\u0447\u0435\u043d\u0438\u044f", "\u043e\u0431\u0440\u0430\u0437\u043e\u0432\u0430\u043d\u0438\u0435", "\u043f\u043e\u0434\u043f\u0438\u0441\u043a\u0438", "\u043f\u0440\u043e\u0447\u0435\u0435"]}');  -- 0 заменить на telegram_id жены
