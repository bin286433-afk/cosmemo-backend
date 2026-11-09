"""한국 시간 기준 현재 시각과 화면 표시용 라벨('오늘 오전 9:00', '10.29 18:30')."""
from datetime import date, datetime, timedelta, timezone
from typing import Optional

from app.config import settings


def local_tz() -> timezone:
    return timezone(timedelta(hours=settings.TZ_OFFSET_HOURS))


def now_local() -> datetime:
    return datetime.now(local_tz())


def to_local(dt_utc_naive: datetime) -> datetime:
    """DB에 저장된 naive UTC → 로컬 시각"""
    return dt_utc_naive.replace(tzinfo=timezone.utc).astimezone(local_tz())


def format_label(dt_utc_naive: Optional[datetime], today: Optional[date] = None) -> str:
    if not dt_utc_naive:
        return ""
    loc = to_local(dt_utc_naive)
    today = today or now_local().date()
    ampm = "오전" if loc.hour < 12 else "오후"
    h12 = loc.hour % 12 or 12
    if loc.date() == today:
        return f"오늘 {ampm} {h12}:{loc.minute:02d}"
    if loc.date() == today - timedelta(days=1):
        return f"어제 {ampm} {h12}:{loc.minute:02d}"
    if loc.year == today.year:
        return loc.strftime("%m.%d %H:%M")
    return loc.strftime("%Y.%m.%d %H:%M")
