"""Timezone helpers — display times in Asia/Shanghai (UTC+8)."""

from __future__ import annotations

from datetime import datetime, timezone
from zoneinfo import ZoneInfo

BEIJING = ZoneInfo("Asia/Shanghai")


def utc_now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def parse_iso_datetime(value: str) -> datetime | None:
    if not value:
        return None
    try:
        # Python 3.11+ handles Z suffix
        return datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None


def to_beijing_display(value: str | datetime | None) -> str | None:
    """Format as local Beijing time: 2026-07-03 16:29:26"""
    if value is None:
        return None
    dt = value if isinstance(value, datetime) else parse_iso_datetime(value)
    if dt is None:
        return str(value)[:19].replace("T", " ")
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    local = dt.astimezone(BEIJING)
    return local.strftime("%Y-%m-%d %H:%M:%S")


def to_beijing_iso(value: str | datetime | None) -> str | None:
    """ISO 8601 with +08:00 offset."""
    if value is None:
        return None
    dt = value if isinstance(value, datetime) else parse_iso_datetime(value)
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.astimezone(BEIJING).isoformat(timespec="seconds")
