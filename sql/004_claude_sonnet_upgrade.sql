-- =========================================
-- 004: Upgrade AI models → DeepSeek V3.2
-- =========================================
-- ВСЕ задачи на DeepSeek V3.2 (GPT-5 class).
-- gpt-4o-mini только как fallback.
-- =========================================

-- 1. Upgrade ALL tasks → DeepSeek V3.2
UPDATE model_routing
SET model = 'deepseek/deepseek-v3.2',
    fallback_model = 'openai/gpt-4o-mini'
WHERE model IN ('claude-3.5-sonnet', 'gpt-4o-mini', 'openai/gpt-4o-mini', 'gpt-4o', 'openai/gpt-4o', 'anthropic/claude-sonnet-4')
  AND task_type != 'transcription';

-- 2. Add missing task types
INSERT INTO model_routing (task_type, model, max_tokens, temperature, fallback_model) VALUES
    ('quarterly_audit',    'deepseek/deepseek-v3.2', 3000, 0.5, 'openai/gpt-4o-mini'),
    ('psychology_report',  'deepseek/deepseek-v3.2', 2500, 0.5, 'openai/gpt-4o-mini'),
    ('business_strategy',  'deepseek/deepseek-v3.2', 2000, 0.4, 'openai/gpt-4o-mini'),
    ('doctor_consult',     'deepseek/deepseek-v3.2', 2000, 0.3, 'openai/gpt-4o-mini'),
    ('voice_summary',      'deepseek/deepseek-v3.2', 1000, 0.3, 'openai/gpt-4o-mini')
ON CONFLICT (task_type) DO UPDATE
SET model = EXCLUDED.model,
    max_tokens = EXCLUDED.max_tokens,
    temperature = EXCLUDED.temperature,
    fallback_model = EXCLUDED.fallback_model;
