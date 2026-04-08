-- Долги и кредиты для семейного бюджета

CREATE TABLE IF NOT EXISTS debts (
    id          SERIAL PRIMARY KEY,
    user_id     BIGINT NOT NULL REFERENCES users(user_id),
    debt_type   TEXT NOT NULL CHECK (debt_type IN ('debt', 'credit')),
    title       TEXT NOT NULL,           -- Название (Ипотека, Долг Ивану и т.д.)
    total_amount NUMERIC(14,2) NOT NULL, -- Общая сумма
    remaining   NUMERIC(14,2) NOT NULL,  -- Остаток
    monthly_payment NUMERIC(14,2),       -- Ежемесячный платёж (для кредитов)
    interest_rate NUMERIC(5,2),          -- Процентная ставка (для кредитов)
    due_date    DATE,                    -- Дата окончания / погашения
    creditor    TEXT,                    -- Кому должны / банк
    notes       TEXT,                    -- Примечания
    is_active   BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMPTZ NOT NULL DEFAULT NOW()
);

CREATE INDEX IF NOT EXISTS idx_debts_user ON debts(user_id, is_active);
