"""Tournament standings, schedules, and team status from openfootball JSON."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass, field
from datetime import date, datetime, timedelta, timezone
from functools import lru_cache
from pathlib import Path
from typing import Any, Literal
from zoneinfo import ZoneInfo

from app.services.match_schedule import (
    filter_cards_by_beijing_date,
    format_kickoff_beijing,
    match_status as _match_status_new,
    refresh_match_card,
)
from app.config import settings
from app.tools.teams import normalize_team_id, reload_team_registry
from app.tools.tournament_db import TournamentDatabase
from app.utils.timezone import to_beijing_display, utc_now_iso

TeamStatus = Literal["active", "qualified", "eliminated", "champion"]

KNOCKOUT_ROUNDS = ("round of 32", "round of 16", "quarter-finals", "semi-finals", "final", "third place", "match for third place")
TZ_DEFAULT = ZoneInfo("Asia/Shanghai")


@dataclass
class ParsedMatch:
    match_id: str
    date: str
    time_raw: str | None
    kickoff_utc: datetime | None
    team1_name: str
    team2_name: str
    team1_id: str | None
    team2_id: str | None
    home_score: int | None
    away_score: int | None
    pen_home: int | None
    pen_away: int | None
    round_name: str
    group: str | None
    venue: str | None
    status: Literal["scheduled", "live", "finished"]

    @property
    def is_group_stage(self) -> bool:
        return self.group is not None and "matchday" in self.round_name.lower()


@dataclass
class TeamRecord:
    team_id: str
    name_zh: str
    name_en: str
    group: str | None = None
    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    goals_for: int = 0
    goals_against: int = 0
    points: int = 0
    status: TeamStatus = "active"


def _slugify(name: str) -> str:
    s = name.strip().lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def resolve_team(name: str) -> tuple[str | None, str, str]:
    """Return (team_id, name_en, name_zh). Placeholders like W83 → id None."""
    stripped = name.strip()
    if not stripped or re.match(r"^W\d+$", stripped, re.I):
        return None, stripped, stripped
    tid = normalize_team_id(stripped)
    if not tid:
        tid = normalize_team_id(_slugify(stripped))
    name_en = stripped
    name_zh = stripped
    if tid:
        info = _team_info_map().get(tid, {})
        name_en = info.get("name_en") or stripped
        name_zh = info.get("name_zh") or name_en
    return tid, name_en, name_zh


@lru_cache
def _team_info_map() -> dict[str, dict[str, str]]:
    import csv

    path = settings.data_dir / "teams.csv"
    out: dict[str, dict[str, str]] = {}
    if not path.exists():
        return out
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tid = row["team_id"].strip()
            out[tid] = {
                "name_en": row.get("name_en", "").strip() or tid,
                "name_zh": row.get("name_zh", "").strip() or row.get("name_en", tid),
            }
    return out


@lru_cache
def _load_groups(year: int) -> dict[str, list[str]]:
    path = settings.worldcup_json_dir / str(year) / "worldcup.groups.json"
    if not path.exists():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    result: dict[str, list[str]] = {}
    for g in data.get("groups", []):
        gname = g.get("name", "")
        ids: list[str] = []
        for t in g.get("teams", []):
            tid, _, _ = resolve_team(t)
            if tid:
                ids.append(tid)
        if gname:
            result[gname] = ids
    return result


def _parse_time(date_str: str, time_str: str | None) -> datetime | None:
    if not time_str:
        return None
    m = re.match(r"(\d{1,2}):(\d{2})\s*UTC([+-]?\d+)", time_str.strip(), re.I)
    if not m:
        return None
    hour, minute, offset_h = int(m.group(1)), int(m.group(2)), int(m.group(3))
    tz = timezone(timedelta(hours=offset_h))
    try:
        d = date.fromisoformat(date_str)
        return datetime(d.year, d.month, d.day, hour, minute, tzinfo=tz)
    except ValueError:
        return None


def _parse_score(match: dict) -> tuple[int | None, int | None, int | None, int | None]:
    score = match.get("score") or {}
    ft = score.get("ft")
    if not ft or len(ft) < 2:
        return None, None, None, None
    home_ft, away_ft = int(ft[0]), int(ft[1])
    pen = score.get("p")
    if pen and len(pen) >= 2:
        return home_ft, away_ft, int(pen[0]), int(pen[1])
    return home_ft, away_ft, None, None


def _match_status(
    date_str: str,
    home_score: int | None,
    away_score: int | None,
    kickoff_utc: datetime | None = None,
) -> Literal["scheduled", "live", "finished"]:
    return _match_status_new(home_score, away_score, kickoff_utc, date_str, TZ_DEFAULT)


@lru_cache
def load_matches(year: int | None = None) -> list[ParsedMatch]:
    reload_team_registry()
    yr = year or settings.tournament_year
    path = settings.worldcup_json_dir / str(yr) / "worldcup.json"
    if not path.exists():
        return []
    data = json.loads(path.read_text(encoding="utf-8"))
    parsed: list[ParsedMatch] = []
    for raw in data.get("matches", []):
        t1, t2 = raw.get("team1", ""), raw.get("team2", "")
        tid1, en1, _ = resolve_team(t1)
        tid2, en2, _ = resolve_team(t2)
        hs, aws, ph, pa = _parse_score(raw)
        date_str = raw.get("date", "")
        kickoff = _parse_time(date_str, raw.get("time"))
        mid = f"{date_str}_{tid1 or _slugify(t1)}_{tid2 or _slugify(t2)}"
        parsed.append(
            ParsedMatch(
                match_id=mid,
                date=date_str,
                time_raw=raw.get("time"),
                kickoff_utc=kickoff,
                team1_name=t1,
                team2_name=t2,
                team1_id=tid1,
                team2_id=tid2,
                home_score=hs,
                away_score=aws,
                pen_home=ph,
                pen_away=pa,
                round_name=raw.get("round", ""),
                group=raw.get("group"),
                venue=raw.get("ground"),
                status=_match_status(date_str, hs, aws, kickoff),
            )
        )
    return parsed


def _loser(pm: ParsedMatch) -> str | None:
    if pm.home_score is None or pm.away_score is None:
        return None
    if pm.home_score > pm.away_score:
        return pm.team2_id
    if pm.away_score > pm.home_score:
        return pm.team1_id
    if pm.pen_home is not None and pm.pen_away is not None:
        return pm.team2_id if pm.pen_home > pm.pen_away else pm.team1_id
    return None


def _winner(pm: ParsedMatch) -> str | None:
    loser = _loser(pm)
    if loser is None:
        return None
    if loser == pm.team1_id:
        return pm.team2_id
    return pm.team1_id


def _compute_team_statuses(matches: list[ParsedMatch], year: int) -> dict[str, TeamStatus]:
    groups = _load_groups(year)
    team_group: dict[str, str] = {}
    for gname, tids in groups.items():
        for tid in tids:
            team_group[tid] = gname

    statuses: dict[str, TeamStatus] = {tid: "active" for tids in groups.values() for tid in tids}

    knockout_teams: set[str] = set()
    eliminated: set[str] = set()
    champion: str | None = None

    for pm in matches:
        rlow = pm.round_name.lower()
        if any(k in rlow for k in KNOCKOUT_ROUNDS):
            for tid in (pm.team1_id, pm.team2_id):
                if tid:
                    knockout_teams.add(tid)
            loser = _loser(pm)
            if loser:
                eliminated.add(loser)
            if "final" in rlow and "semi" not in rlow:
                w = _winner(pm)
                if w:
                    champion = w

    group_records: dict[str, dict[str, TeamRecord]] = {}
    for pm in matches:
        if not pm.is_group_stage or not pm.group:
            continue
        g = pm.group
        group_records.setdefault(g, {})
        for tid, gf, ga, is_home in (
            (pm.team1_id, pm.home_score, pm.away_score, True),
            (pm.team2_id, pm.away_score, pm.home_score, False),
        ):
            if not tid or pm.home_score is None or pm.away_score is None:
                continue
            info = _team_info_map().get(tid, {})
            rec = group_records[g].setdefault(
                tid,
                TeamRecord(
                    team_id=tid,
                    name_en=info.get("name_en", tid),
                    name_zh=info.get("name_zh", tid),
                    group=g,
                ),
            )
            rec.played += 1
            rec.goals_for += gf or 0
            rec.goals_against += ga or 0
            if gf > ga:
                rec.won += 1
                rec.points += 3
            elif gf == ga:
                rec.drawn += 1
                rec.points += 1
            else:
                rec.lost += 1

    for g, recs in group_records.items():
        expected = len(_load_groups(year).get(g, [])) * 3 // 2  # 3 matchdays, 2 games per team per matchday... actually 3 games each
        sorted_rows = sorted(
            recs.values(),
            key=lambda r: (r.points, r.goals_for - r.goals_against, r.goals_for),
            reverse=True,
        )
        all_played = all(r.played >= 3 for r in sorted_rows) if sorted_rows else False
        if all_played and len(sorted_rows) >= 4:
            for i, row in enumerate(sorted_rows):
                if i >= 3:
                    eliminated.add(row.team_id)

    for tid in knockout_teams:
        if tid not in eliminated:
            statuses[tid] = "qualified"

    for tid in eliminated:
        statuses[tid] = "eliminated"

    if champion:
        statuses[champion] = "champion"
        for tid in statuses:
            if tid != champion and statuses[tid] != "eliminated":
                if tid not in knockout_teams:
                    pass

    return statuses


def get_standings(year: int | None = None) -> list[dict[str, Any]]:
    yr = year or settings.tournament_year
    matches = load_matches(yr)
    statuses = _compute_team_statuses(matches, yr)
    group_records: dict[str, dict[str, TeamRecord]] = {}

    for pm in matches:
        if not pm.is_group_stage or not pm.group:
            continue
        g = pm.group
        group_records.setdefault(g, {})
        for tid, gf, ga in (
            (pm.team1_id, pm.home_score, pm.away_score),
            (pm.team2_id, pm.away_score, pm.home_score),
        ):
            if not tid or pm.home_score is None or pm.away_score is None:
                continue
            info = _team_info_map().get(tid, {})
            rec = group_records[g].setdefault(
                tid,
                TeamRecord(
                    team_id=tid,
                    name_en=info.get("name_en", tid),
                    name_zh=info.get("name_zh", tid),
                    group=g,
                ),
            )
            rec.played += 1
            rec.goals_for += gf or 0
            rec.goals_against += ga or 0
            if gf > ga:
                rec.won += 1
                rec.points += 3
            elif gf == ga:
                rec.drawn += 1
                rec.points += 1
            else:
                rec.lost += 1

    result: list[dict[str, Any]] = []
    for g in sorted(group_records.keys()):
        rows = sorted(
            group_records[g].values(),
            key=lambda r: (r.points, r.goals_for - r.goals_against, r.goals_for),
            reverse=True,
        )
        group_rows = []
        for i, r in enumerate(rows, 1):
            st = statuses.get(r.team_id, "active")
            group_rows.append(
                {
                    "rank": i,
                    "team_id": r.team_id,
                    "name_zh": r.name_zh,
                    "name_en": r.name_en,
                    "played": r.played,
                    "won": r.won,
                    "drawn": r.drawn,
                    "lost": r.lost,
                    "goals_for": r.goals_for,
                    "goals_against": r.goals_against,
                    "goal_diff": r.goals_for - r.goals_against,
                    "points": r.points,
                    "status": st,
                }
            )
        result.append({"group": g, "rows": group_rows})
    return result


def match_to_card(pm: ParsedMatch, tz: ZoneInfo = TZ_DEFAULT) -> dict[str, Any]:
    _, en1, zh1 = resolve_team(pm.team1_name)
    _, en2, zh2 = resolve_team(pm.team2_name)
    kickoff_display, kickoff_utc, kickoff_local = format_kickoff_beijing(
        pm.kickoff_utc, pm.time_raw, pm.date, tz
    )
    status = _match_status_new(pm.home_score, pm.away_score, pm.kickoff_utc, pm.date, tz)
    return {
        "match_id": pm.match_id,
        "date": pm.date,
        "kickoff_display": kickoff_display,
        "kickoff_utc": kickoff_utc,
        "kickoff_local": kickoff_local,
        "home": {
            "team_id": pm.team1_id,
            "name_zh": zh1,
            "name_en": en1,
            "score": pm.home_score,
        },
        "away": {
            "team_id": pm.team2_id,
            "name_zh": zh2,
            "name_en": en2,
            "score": pm.away_score,
        },
        "status": status,
        "stage": pm.round_name,
        "group": pm.group,
        "venue": pm.venue,
        "time_raw": pm.time_raw,
        "odds": None,
    }


def get_matches_on_date(target: date | None = None, year: int | None = None, tz_name: str = "Asia/Shanghai") -> dict[str, Any]:
    tz = ZoneInfo(tz_name)
    today = target or datetime.now(tz).date()
    date_str = today.isoformat()
    matches = load_matches(year)
    cards = [match_to_card(m, tz) for m in matches]
    day_cards = filter_cards_by_beijing_date(cards, today, tz_name)
    return {
        "date": date_str,
        "timezone": tz_name,
        "matches": day_cards,
    }


def get_all_teams(year: int | None = None) -> list[dict[str, Any]]:
    yr = year or settings.tournament_year
    matches = load_matches(yr)
    statuses = _compute_team_statuses(matches, yr)
    groups = _load_groups(yr)
    team_group = {tid: g for g, tids in groups.items() for tid in tids}

    records: dict[str, TeamRecord] = {}
    for g, tids in groups.items():
        for tid in tids:
            info = _team_info_map().get(tid, {})
            records.setdefault(
                tid,
                TeamRecord(
                    team_id=tid,
                    name_en=info.get("name_en", tid),
                    name_zh=info.get("name_zh", tid),
                    group=g,
                ),
            )
    for pm in matches:
        if not pm.is_group_stage:
            continue
        for tid, gf, ga in (
            (pm.team1_id, pm.home_score, pm.away_score),
            (pm.team2_id, pm.away_score, pm.home_score),
        ):
            if not tid or pm.home_score is None or pm.away_score is None:
                continue
            info = _team_info_map().get(tid, {})
            rec = records.setdefault(
                tid,
                TeamRecord(
                    team_id=tid,
                    name_en=info.get("name_en", tid),
                    name_zh=info.get("name_zh", tid),
                    group=team_group.get(tid),
                ),
            )
            rec.played += 1
            rec.goals_for += gf or 0
            rec.goals_against += ga or 0
            if gf > ga:
                rec.won += 1
                rec.points += 3
            elif gf == ga:
                rec.drawn += 1
                rec.points += 1
            else:
                rec.lost += 1

    out: list[dict[str, Any]] = []
    for tid in sorted(records.keys(), key=lambda t: records[t].name_zh):
        r = records[tid]
        played = r.played
        wr = round(r.won / played, 3) if played else None
        out.append(
            {
                "team_id": tid,
                "name_zh": r.name_zh,
                "name_en": r.name_en,
                "group": r.group,
                "status": statuses.get(tid, "active"),
                "played": r.played,
                "won": r.won,
                "drawn": r.drawn,
                "lost": r.lost,
                "goals_for": r.goals_for,
                "goals_against": r.goals_against,
                "points": r.points,
                "win_rate": wr,
            }
        )
    return out


def get_tournament_info(year: int | None = None) -> dict[str, Any]:
    yr = year or settings.tournament_year
    path = settings.worldcup_json_dir / str(yr) / "worldcup.json"
    name = f"World Cup {yr}"
    if path.exists():
        data = json.loads(path.read_text(encoding="utf-8"))
        name = data.get("name", name)
    groups = _load_groups(yr)
    total = sum(len(v) for v in groups.values())
    matches = load_matches(yr)
    phase = "小组赛"
    if any("round of 32" in m.round_name.lower() for m in matches):
        phase = "淘汰赛"
    if any("final" in m.round_name.lower() and m.home_score is not None for m in matches):
        phase = "已结束或决赛阶段"
    mtime = path.stat().st_mtime if path.exists() else None
    updated = datetime.fromtimestamp(mtime, tz=timezone.utc).isoformat() if mtime else None
    return {
        "year": yr,
        "name": name,
        "phase": phase,
        "total_teams": total,
        "data_updated_at": to_beijing_display(updated),
    }


def invalidate_tournament_cache() -> None:
    load_matches.cache_clear()
    _load_groups.cache_clear()
    _team_info_map.cache_clear()


def build_tournament_snapshot(year: int | None = None) -> dict[str, Any]:
    """Compute full tournament snapshot from JSON (source of truth)."""
    from app.tools.teams import reload_team_registry

    reload_team_registry()
    invalidate_tournament_cache()
    yr = year or settings.tournament_year
    matches = load_matches(yr)
    return {
        "year": yr,
        "synced_at": utc_now_iso(),
        "tournament": get_tournament_info(yr),
        "matches": [match_to_card(m) for m in matches],
        "standings": get_standings(yr),
        "teams": get_all_teams(yr),
    }


def export_snapshot_json(snapshot: dict[str, Any]) -> Path:
    """Write snapshot to data/snapshots/ for inspection and backup."""
    out_dir = settings.tournament_snapshot_dir
    out_dir.mkdir(parents=True, exist_ok=True)
    yr = snapshot["year"]
    path = out_dir / f"tournament_{yr}.json"
    path.write_text(json.dumps(snapshot, ensure_ascii=False, indent=2), encoding="utf-8")
    return path


async def sync_tournament_to_db(
    db: TournamentDatabase,
    year: int | None = None,
    export_json: bool = True,
) -> dict[str, Any]:
    """Compute from JSON and persist to tournament.db (+ optional JSON file)."""
    snapshot = build_tournament_snapshot(year)
    counts = await db.sync_snapshot(snapshot)
    json_path = export_snapshot_json(snapshot) if export_json else None
    return {
        "year": snapshot["year"],
        "synced_at": snapshot["synced_at"],
        "counts": counts,
        "json_path": str(json_path) if json_path else None,
    }


def get_overview(target_date: date | None = None) -> dict[str, Any]:
    return {
        "tournament": get_tournament_info(),
        "today": get_matches_on_date(target_date),
        "standings": {"year": settings.tournament_year, "groups": get_standings()},
        "meta": {"odds_available": False, "source": "json", "timezone": "Asia/Shanghai"},
    }


async def get_overview_from_db(
    db: TournamentDatabase,
    target_date: date | None = None,
    tz_name: str = "Asia/Shanghai",
) -> dict[str, Any] | None:
    if not db.is_populated():
        return None
    from zoneinfo import ZoneInfo
    from datetime import datetime

    tz = ZoneInfo(tz_name)
    today = target_date or datetime.now(tz).date()
    tournament = await db.fetch_tournament_info()
    if not tournament:
        return None
    today_data = await db.fetch_matches_on_date(today.isoformat(), tz_name=tz_name)
    groups = await db.fetch_standings()
    meta = await db.get_meta()
    raw_sync = meta.get("last_sync_at", {}).get("value")
    return {
        "tournament": tournament,
        "today": today_data,
        "standings": {"year": settings.tournament_year, "groups": groups},
        "meta": {
            "odds_available": db.has_odds(),
            "odds_backend": settings.odds_backend,
            "source": "sqlite",
            "timezone": "Asia/Shanghai",
            "last_sync_at": to_beijing_display(raw_sync),
            "last_odds_fetch_at": to_beijing_display(
                meta.get("last_odds_fetch_at", {}).get("value")
            ),
        },
    }
