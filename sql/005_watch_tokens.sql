-- 005: Amazfit Watch — API-ключи часов (push-модель)
-- Хранит API-ключи для push-интеграции с Amazfit Balance 2 (Zepp OS)

CREATE TABLE IF NOT EXISTS watch_tokens (
    user_id BIGINT PRIMARY KEY REFERENCES users(user_id),
    api_key TEXT NOT NULL UNIQUE,
    device_name TEXT DEFAULT 'Amazfit Balance 2',
    push_interval_min INT DEFAULT 15,
    is_active BOOLEAN DEFAULT TRUE,
    last_push_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_watch_tokens_api_key ON watch_tokens(api_key);

COMMENT ON TABLE watch_tokens IS 'API-ключи для push-интеграции с Amazfit Balance 2 — данные смарт-часов';
