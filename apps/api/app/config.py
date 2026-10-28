from functools import lru_cache
from zoneinfo import ZoneInfo

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", extra="ignore")

    jarvis_uid: str = ""
    timezone: str = "Asia/Kolkata"

    firebase_service_account_json: str = ""
    google_application_credentials: str = ""

    cors_origins: str = "http://localhost:5173"
    cron_secret: str = ""

    llm_provider: str = "anthropic"
    llm_model: str = ""
    anthropic_api_key: str = ""
    gemini_api_key: str = ""
    ollama_url: str = "http://localhost:11434"

    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_webhook_secret: str = ""

    focus_switch_threshold: int = 12

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
