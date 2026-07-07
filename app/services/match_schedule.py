"""Match kickoff formatting and status (Asia/Shanghai)."""

from __future__ import annotations

from datetime import date, datetime, timezone
from typing import Any, Literal
from zoneinfo import ZoneInfo

from app.utils.timezone import parse_iso_datetime

BEIJING = ZoneInfo("Asia/Shanghai")
MatchStatus = Literal["scheduled", "live", "finished"]

# 单场常规时间约 2h；仅在有比分同步前用于区分「已开球未入库」的展示（仍标 scheduled）
MATCH_DURATION_HOURS = 2


def match_status(
    home_score: int | None,
    away_score: int | None,
    kickoff_utc: datetime | None = None,
    fallback_date: str | None = None,
    tz: ZoneInfo = BEIJING,
    *,
    explicit_live: bool = False,
) -> MatchStatus:
    """
    比赛状态（适配 openfootball 静态 JSON）：
    - 有比分 → finished
    - 无比分 → scheduled（不因开球时间已过就标 live；数据里没有 score 即视为未开赛/未入库）
    - explicit_live 预留给未来实时比分 API
    """
    if home_score is not None and away_score is not None:
        return "finished"
    if explicit_live:
        return "live"
    return "scheduled"


def format_kickoff_beijing(
    kickoff_utc: datetime | None,
    time_raw: str | None = None,
    fallback_date: str | None = None,
    tz: ZoneInfo = BEIJING,
) -> tuple[str, str | None, str | None]:
    """Return (kickoff_display, kickoff_utc_iso, kickoff_local_iso)."""
    if kickoff_utc is not None:
        local = kickoff_utc.astimezone(tz)
        display = local.strftime("%Y-%m-%d %H:%M")
        return (
            display,
            kickoff_utc.astimezone(timezone.utc).isoformat(),
            local.isoformat(timespec="minutes"),
        )
    if fallback_date and time_raw:
        return f"{fallback_date} {time_raw}", None, None
    if fallback_date:
        return fallback_date, None, None
    return "--", None, None


def beijing_date_of(
    kickoff_utc: datetime | None,
    fallback_date: str | None = None,
    tz: ZoneInfo = BEIJING,
) -> date | None:
    if kickoff_utc is not None:
        return kickoff_utc.astimezone(tz).date()
    if fallback_date:
        try:
            return date.fromisoformat(fallback_date)
        except ValueError:
            return None
    return None


def refresh_match_card(card: dict[str, Any], tz_name: str = "Asia/Shanghai") -> dict[str, Any]:
    """Recompute status and Beijing kickoff display (for DB snapshots at read time)."""
    tz = ZoneInfo(tz_name)
    kickoff = parse_iso_datetime(card.get("kickoff_utc") or "")
    home_score = card.get("home", {}).get("score")
    away_score = card.get("away", {}).get("score")
    status = match_status(home_score, away_score, kickoff, card.get("date"), tz)
    display, kickoff_utc, kickoff_local = format_kickoff_beijing(
        kickoff, card.get("time_raw"), card.get("date"), tz
    )
    out = {**card, "status": status, "kickoff_display": display}
    if kickoff_utc:
        out["kickoff_utc"] = kickoff_utc
    if kickoff_local:
        out["kickoff_local"] = kickoff_local
    return out


def filter_cards_by_beijing_date(
    cards: list[dict[str, Any]],
    target: date,
    tz_name: str = "Asia/Shanghai",
) -> list[dict[str, Any]]:
    tz = ZoneInfo(tz_name)
    result: list[dict[str, Any]] = []
    for card in cards:
        kickoff = parse_iso_datetime(card.get("kickoff_utc") or "")
        local_d = beijing_date_of(kickoff, card.get("date"), tz)
        if local_d == target:
            result.append(refresh_match_card(card, tz_name))
    result.sort(key=lambda c: c.get("kickoff_utc") or "")
    return result
