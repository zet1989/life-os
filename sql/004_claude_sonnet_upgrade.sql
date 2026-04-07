-- =========================================
-- 004: Upgrade AI models — Claude Sonnet 4
-- =========================================
-- Стратегические задачи переводятся на Claude Sonnet 4.
-- Быстрые парсинг-задачи остаются на gpt-4o-mini.
-- =========================================

-- 1. Upgrade existing Claude 3.5 → Claude Sonnet 4
UPDATE model_routing
SET model = 'anthropic/claude-sonnet-4',
    fallback_model = 'openai/gpt-4o'
WHERE model = 'claude-3.5-sonnet';

-- 2. Upgrade strategic tasks that were on gpt-4o-mini → Claude
UPDATE model_routing
SET model = 'anthropic/claude-sonnet-4',
    max_tokens = 2000,
    temperature = 0.5,
    fallback_model = 'openai/gpt-4o'
WHERE task_type IN ('psychology_diary', 'master_goal', 'master_talk');

-- 3. Add missing task types
INSERT INTO model_routing (task_type, model, max_tokens, temperature, fallback_model) VALUES
    ('quarterly_audit',    'anthropic/claude-sonnet-4', 3000, 0.5, 'openai/gpt-4o'),
    ('psychology_report',  'anthropic/claude-sonnet-4', 2500, 0.5, 'openai/gpt-4o'),
    ('business_strategy',  'anthropic/claude-sonnet-4', 2000, 0.4, 'openai/gpt-4o'),
    ('doctor_consult',     'openai/gpt-4o',             2000, 0.3, 'openai/gpt-4o-mini'),
    ('voice_summary',      'openai/gpt-4o-mini',        1000, 0.3, NULL)
ON CONFLICT (task_type) DO UPDATE
SET model = EXCLUDED.model,
    max_tokens = EXCLUDED.max_tokens,
    temperature = EXCLUDED.temperature,
    fallback_model = EXCLUDED.fallback_model;
