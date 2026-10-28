from datetime import date, datetime, timedelta, timezone

from .config import get_settings


def now_utc() -> datetime:
    return datetime.now(timezone.utc)


def now_local() -> datetime:
    return datetime.now(get_settings().tz)


def today() -> str:
    return now_local().date().isoformat()


def yesterday() -> str:
    return (now_local().date() - timedelta(days=1)).isoformat()


def tomorrow() -> str:
    return (now_local().date() + timedelta(days=1)).isoformat()


def parse(ts: str) -> datetime:
    return datetime.fromisoformat(ts.replace("Z", "+00:00"))


def fmt_duration(seconds: float) -> str:
    m = int(seconds // 60)
    h, m = divmod(m, 60)
    return f"{h}h {m:02d}m" if h else f"{m}m"


def iso_date(d: date) -> str:
    return d.isoformat()
