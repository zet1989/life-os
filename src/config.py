"""Конфигурация приложения — Pydantic Settings.

Все секреты загружаются из .env при старте.
Если переменная не задана — приложение упадёт сразу, а не при первом запросе.
"""

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        env_file=".env",
        env_file_encoding="utf-8",
        extra="ignore",
    )

    # --- Telegram Bot Tokens ---
    bot_token_health: str = ""
    bot_token_assets: str = ""
    bot_token_business: str = ""
    bot_token_partner: str = ""
    bot_token_mentor: str = ""
    bot_token_family: str = ""
    bot_token_psychology: str = ""
    bot_token_master: str = ""

    # --- Unified Bot (единый бот-хаб) ---
    bot_token_unified: str = ""     # если задан — все секции в одном боте

    # --- PostgreSQL ---
    database_url: str = "postgresql://lifeos:lifeos@postgres:5432/lifeos"

    # --- AI APIs ---
    openrouter_api_key: str
    openai_api_key: str = ""        # опционально
    groq_api_key: str = ""          # Groq API для Whisper транскрипции

    # --- Redis ---
    redis_url: str = "redis://localhost:6379/0"

    # --- App ---
    log_level: str = "INFO"
    admin_user_id: int = 0

    # --- Webhook (продакшен) ---
    use_webhook: bool = False
    webhook_host: str = ""          # https://yourdomain.com
    webhook_port: int = 8443
    webhook_secret: str = ""        # секрет для верификации

    # --- Budget limiter ---
    api_daily_limit_usd: float = 2.0
    api_monthly_limit_usd: float = 20.0

    # --- Obsidian integration ---
    obsidian_vault_path: str = "/app/obsidian-vault"
    obsidian_sync_enabled: bool = False
    obsidian_watch_enabled: bool = False

    # --- HUAWEI Health Kit (смарт-часы) ---
    huawei_client_id: str = ""
    huawei_client_secret: str = ""

    # --- Free model limits ---
    free_model_daily_limit: int = 950  # запросов бесплатных моделей в день (с запасом от 1000 при $10+)


settings = Settings()  # type: ignore[call-arg]
