-- Migration 003: Subtasks, goal linking, tags, kanban, sort order
-- Date: 2026-04-07

-- 1. Подзадачи: parent_task_id для иерархии задач
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS parent_task_id INT REFERENCES tasks(id) ON DELETE CASCADE;
CREATE INDEX IF NOT EXISTS idx_tasks_parent ON tasks(parent_task_id) WHERE parent_task_id IS NOT NULL;

-- 2. Привязка задач к целям
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS goal_id INT REFERENCES goals(id) ON DELETE SET NULL;
CREATE INDEX IF NOT EXISTS idx_tasks_goal ON tasks(goal_id) WHERE goal_id IS NOT NULL;

-- 3. Тэги (PostgreSQL массив + GIN индекс)
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS tags TEXT[] DEFAULT '{}';
CREATE INDEX IF NOT EXISTS idx_tasks_tags ON tasks USING GIN(tags);

-- 4. Kanban-статус
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS kanban_status TEXT DEFAULT 'todo'
    CHECK (kanban_status IN ('backlog', 'todo', 'in_progress', 'done'));

-- Инициализировать kanban_status для существующих задач
UPDATE tasks SET kanban_status = 'done' WHERE is_done = TRUE AND kanban_status = 'todo';

-- 5. Числовой порядок для drag & drop приоритетов
ALTER TABLE tasks ADD COLUMN IF NOT EXISTS sort_order INT DEFAULT 0;
