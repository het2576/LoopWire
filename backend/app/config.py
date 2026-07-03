from functools import lru_cache

from pydantic_settings import BaseSettings, SettingsConfigDict


class Settings(BaseSettings):
    model_config = SettingsConfigDict(env_file=".env", env_file_encoding="utf-8", extra="ignore")

    # Database (Supabase Postgres connection string)
    database_url: str = "postgresql+psycopg2://postgres:postgres@localhost:5432/postgres"

    # Telegram
    telegram_bot_token: str = ""

    # LLM
    gemini_api_key: str = ""
    gemini_model: str = "gemini-2.5-flash"

    # Email (Resend) - sender address is fixed/branded; the recipient is
    # each user's own account email now (Phase A), passed per-call instead
    # of read from config.
    resend_api_key: str = ""
    loopwire_from_email: str = "hello@loopwire.example.com"

    # Web dashboard
    dashboard_base_url: str = "http://localhost:3000"
    backend_base_url: str = "http://localhost:8000"

    # Send scheduling (hour is in IST, Asia/Kolkata)
    # Only used by the optional in-process APScheduler (start_scheduler in
    # scheduler.py) - the default deployment triggers sends via an external
    # cron hitting /send-digest instead, since Render's free web service tier
    # sleeps when idle and can't be relied on for an internal cron to fire.
    loopwire_period: str = "daily"  # "daily" or "weekly"
    loopwire_send_hour_ist: int = 9  # 9am IST

    # --- Telegram webhook mode ---
    # Secret Telegram echoes back in the X-Telegram-Bot-Api-Secret-Token
    # header on every webhook call, so /telegram-webhook can reject requests
    # that didn't actually come from Telegram. Optional but recommended -
    # generate with: python -c "import secrets; print(secrets.token_urlsafe(32))"
    telegram_webhook_secret: str = ""

    # --- /send-digest endpoint protection ---
    # Required query param (?key=...) to trigger a send over HTTP (e.g. from
    # a cron-job.org ping). Left blank by default so the endpoint fails
    # closed - a blank secret never matches, even an empty ?key= param.
    send_loopwire_secret: str = ""

    # --- /process-pending endpoint protection ---
    # Same fail-closed pattern as send_loopwire_secret, for the endpoint that
    # runs extraction + summarization on demand (replaces the always-on
    # worker loop - see SETUP.md).
    process_pending_secret: str = ""

    # --- Internal Next.js <-> FastAPI auth bridge (Phase A, prdv2.md) ---
    # Shared secret proving a request came from our own Next.js server (which
    # has already validated the NextAuth session) rather than a random
    # caller. Same value must be set in dashboard/.env.local. Fails closed
    # if blank - see app/auth.py.
    internal_auth_secret: str = ""


@lru_cache
def get_settings() -> Settings:
    return Settings()
