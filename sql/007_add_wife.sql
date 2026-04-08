-- 007: Добавить жену в систему
-- Роль wife — доступ к ботам health и family

INSERT INTO users (user_id, display_name, role, permissions, is_active)
VALUES (5152648460, 'Жена', 'wife', '{"bots": ["health", "family"]}', true)
ON CONFLICT (user_id) DO UPDATE SET
    role = 'wife',
    permissions = '{"bots": ["health", "family"]}',
    is_active = true;
