-- Учёт рабочего времени

CREATE TABLE IF NOT EXISTS work_sessions (
    id              SERIAL PRIMARY KEY,
    user_id         BIGINT NOT NULL REFERENCES users(user_id),
    start_time      TIMESTAMPTZ NOT NULL,
    end_time        TIMESTAMPTZ,
    duration_minutes INTEGER,          -- auto-calculated on stop
    notes           TEXT,
    created_at      TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_work_sessions_user ON work_sessions(user_id, start_time DESC);
