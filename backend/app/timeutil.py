"""Local-day boundaries for per-day caps and dispatch dates."""

import datetime as dt
from zoneinfo import ZoneInfo

from app.config import get_settings


def app_tz() -> ZoneInfo:
    return ZoneInfo(get_settings().app_timezone)


def local_day_start_utc(now: dt.datetime | None = None) -> dt.datetime:
    """Start of 'today' in the app timezone, as a UTC datetime. Caps used to
    reset at UTC midnight - 5:30am IST - so a late-night user hit
    yesterday's cap after midnight local time."""
    now = now or dt.datetime.now(dt.UTC)
    local = now.astimezone(app_tz())
    return local.replace(hour=0, minute=0, second=0, microsecond=0).astimezone(dt.UTC)


def local_today(now: dt.datetime | None = None) -> dt.date:
    now = now or dt.datetime.now(dt.UTC)
    return now.astimezone(app_tz()).date()
