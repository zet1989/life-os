"""Инициализация Supabase-клиента.

DEPRECATED: Проект мигрировал на прямое подключение через asyncpg.
Этот модуль сохранён для совместимости на случай будущего использования
Supabase REST API (Storage, Realtime).
Для основных SQL-запросов используйте src/db/postgres.py + src/db/queries.py.
"""

# from supabase import create_client, Client
# from src.config import settings

# _client: Client | None = None

# def get_supabase() -> Client:
#     global _client
#     if _client is None:
#         _client = create_client(settings.supabase_url, settings.supabase_key)
#     return _client
