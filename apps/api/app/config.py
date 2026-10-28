from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    jarvis_uid: str = ""
    timezone: str = "Asia/Kolkata"

    firebase_service_account_json: str = ""
    google_application_credentials: str = ""

    cors_origins: str = "http://localhost:3000"
    cron_secret: str = ""

    llm_provider: str = "gemini"
    llm_model: str = ""
    anthropic_api_key: str = ""
    gemini_api_key: str = ""

    tomtom_api_key: str = ""

    email_address: str = ""
    email_app_password: str = ""
    sender_name: str = "Presqio Team"
    daily_email_cap: int = 50        # hard limit per day, protects the Gmail account


    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_webhook_secret: str = ""
    telegram_mode: str = "polling"   # "polling" for local dev, "webhook" when deployed

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
