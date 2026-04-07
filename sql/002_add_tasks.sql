-- Life OS: миграция — таблица tasks (планировщик задач)
-- Выполнить вручную: psql -U lifeos -d lifeos -f sql/002_add_tasks.sql

CREATE TABLE IF NOT EXISTS tasks (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id),
    task_text TEXT NOT NULL,
    source TEXT DEFAULT 'telegram',
    source_file TEXT,
    due_date DATE,
    due_time TIME,
    priority TEXT DEFAULT 'normal',
    project_id INT REFERENCES projects(project_id),
    is_done BOOLEAN DEFAULT FALSE,
    reminder_sent BOOLEAN DEFAULT FALSE,
    done_at TIMESTAMPTZ,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_tasks_user_date ON tasks(user_id, due_date)
    WHERE is_done = FALSE;
CREATE INDEX IF NOT EXISTS idx_tasks_reminders ON tasks(due_date, due_time)
    WHERE is_done = FALSE AND reminder_sent = FALSE;
