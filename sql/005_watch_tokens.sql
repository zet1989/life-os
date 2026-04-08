-- 005: HUAWEI Health Kit — токены часов
-- Хранит OAuth2 токены для HUAWEI Health Kit (смарт-часы)

CREATE TABLE IF NOT EXISTS watch_tokens (
    user_id BIGINT PRIMARY KEY REFERENCES users(user_id),
    access_token TEXT NOT NULL,
    refresh_token TEXT NOT NULL,
    expires_at TIMESTAMPTZ NOT NULL,
    device_name TEXT DEFAULT 'HUAWEI WATCH FIT 4 Pro',
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

COMMENT ON TABLE watch_tokens IS 'OAuth2 токены для HUAWEI Health Kit — данные смарт-часов';
