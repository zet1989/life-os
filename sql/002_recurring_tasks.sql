-- Migration: Add recurrence support for tasks
-- Run this on existing database to add recurring tasks feature

ALTER TABLE tasks ADD COLUMN IF NOT EXISTS recurrence TEXT DEFAULT NULL;
-- Values: NULL (one-time), 'daily', 'weekly', 'monthly', 'weekdays'

ALTER TABLE tasks ADD COLUMN IF NOT EXISTS recurrence_parent_id INT REFERENCES tasks(id) DEFAULT NULL;
-- Points to the "template" task that spawns recurring instances

COMMENT ON COLUMN tasks.recurrence IS 'Recurrence pattern: NULL, daily, weekly, monthly, weekdays';
COMMENT ON COLUMN tasks.recurrence_parent_id IS 'ID of parent recurring task template';
