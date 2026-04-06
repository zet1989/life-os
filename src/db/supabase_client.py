"""Инициализация Supabase-клиента."""

from supabase import create_client, Client

from src.config import settings

_client: Client | None = None


def get_supabase() -> Client:
    """Ленивая инициализация — клиент создаётся при первом вызове."""
    global _client
    if _client is None:
        _client = create_client(settings.supabase_url, settings.supabase_key)
    return _client
