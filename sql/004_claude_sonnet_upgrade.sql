-- =========================================
-- 004: Upgrade AI models → DeepSeek V3.2
-- =========================================
-- Стратегические задачи переводятся на DeepSeek V3.2.
-- Быстрые парсинг-задачи остаются на gpt-4o-mini.
-- =========================================

-- 1. Upgrade existing Claude 3.5 → DeepSeek V3.2
UPDATE model_routing
SET model = 'deepseek/deepseek-v3.2',
    fallback_model = 'openai/gpt-4o-mini'
WHERE model = 'claude-3.5-sonnet';

-- 2. Upgrade strategic tasks that were on gpt-4o-mini → DeepSeek
UPDATE model_routing
SET model = 'deepseek/deepseek-v3.2',
    max_tokens = 2000,
    temperature = 0.5,
    fallback_model = 'openai/gpt-4o-mini'
WHERE task_type IN ('psychology_diary', 'master_goal', 'master_talk');

-- 3. Add missing task types
INSERT INTO model_routing (task_type, model, max_tokens, temperature, fallback_model) VALUES
    ('quarterly_audit',    'deepseek/deepseek-v3.2', 3000, 0.5, 'openai/gpt-4o-mini'),
    ('psychology_report',  'deepseek/deepseek-v3.2', 2500, 0.5, 'openai/gpt-4o-mini'),
    ('business_strategy',  'deepseek/deepseek-v3.2', 2000, 0.4, 'openai/gpt-4o-mini'),
    ('doctor_consult',     'deepseek/deepseek-v3.2', 2000, 0.3, 'openai/gpt-4o-mini'),
    ('voice_summary',      'openai/gpt-4o-mini',     1000, 0.3, NULL)
ON CONFLICT (task_type) DO UPDATE
SET model = EXCLUDED.model,
    max_tokens = EXCLUDED.max_tokens,
    temperature = EXCLUDED.temperature,
    fallback_model = EXCLUDED.fallback_model;
