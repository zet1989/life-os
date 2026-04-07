-- 003: Obsidian tasks table
CREATE TABLE IF NOT EXISTS obsidian_tasks (
    id SERIAL PRIMARY KEY,
    user_id BIGINT REFERENCES users(user_id),
    task_text TEXT NOT NULL,
    source_file TEXT NOT NULL,
    due_date DATE,
    due_time TIME,
    is_done BOOLEAN DEFAULT FALSE,
    reminder_sent BOOLEAN DEFAULT FALSE,
    created_at TIMESTAMPTZ DEFAULT NOW(),
    updated_at TIMESTAMPTZ DEFAULT NOW(),
    UNIQUE(source_file, task_text)
);

CREATE INDEX IF NOT EXISTS idx_obsidian_tasks_due
    ON obsidian_tasks(due_date, due_time)
    WHERE is_done = FALSE AND reminder_sent = FALSE;

CREATE INDEX IF NOT EXISTS idx_obsidian_tasks_user
    ON obsidian_tasks(user_id, due_date)
    WHERE is_done = FALSE;
