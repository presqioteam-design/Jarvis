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
    email_app_password: str = ""      # SMTP/IMAP; used when the Gmail API isn't set up
    # Gmail API (HTTPS): needed where email ports are blocked, e.g. Render's free plan
    gmail_client_id: str = ""
    gmail_client_secret: str = ""
    gmail_refresh_token: str = ""
    sender_name: str = "Presqio Team"
    daily_email_cap: int = 50        # hard limit per day, protects the Gmail account

    # automatic sending (cron every 30 min); "pause auto" on Telegram turns it off
    auto_send_per_run: int = 5
    auto_send_from: str = "10:00"    # local time, Monday–Saturday
    auto_send_until: str = "14:00"
    auto_daily_cap: int = 40         # automatic batches stop here; manual "send" can use the rest


    telegram_bot_token: str = ""
    telegram_chat_id: str = ""
    telegram_webhook_secret: str = ""
    telegram_mode: str = "polling"   # "polling" for local dev, "webhook" when deployed

    # Render sets this to the service's public URL (https://<name>.onrender.com)
    render_external_url: str = ""

    @property
    def tz(self) -> ZoneInfo:
        return ZoneInfo(self.timezone)

    @property
    def cors_list(self) -> list[str]:
        return [o.strip() for o in self.cors_origins.split(",") if o.strip()]


@lru_cache
def get_settings() -> Settings:
    return Settings()
