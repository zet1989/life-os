-- 008: Todoist auto-sync — отслеживание импортированных задач
-- Без этой таблицы бот не знает, какие задачи уже были импортированы

CREATE TABLE IF NOT EXISTS todoist_synced (
    todoist_id TEXT PRIMARY KEY,
    user_id    BIGINT NOT NULL REFERENCES users(user_id),
    imported   BOOLEAN DEFAULT FALSE,  -- TRUE=импортирована, FALSE=пропущена (первый синк)
    synced_at  TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_todoist_synced_user ON todoist_synced(user_id);
