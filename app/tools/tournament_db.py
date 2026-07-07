"""SQLite store for tournament standings and match snapshots (P1 pipeline)."""

from __future__ import annotations

import asyncio
import json
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.config import settings
from app.utils.timezone import to_beijing_display

_SCHEMA = """
CREATE TABLE IF NOT EXISTS pipeline_meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL,
    updated_at TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS tournament_matches (
    match_id TEXT PRIMARY KEY,
    year INTEGER NOT NULL,
    date TEXT NOT NULL,
    kickoff_display TEXT,
    kickoff_utc TEXT,
    home_team_id TEXT,
    away_team_id TEXT,
    home_name_zh TEXT,
    away_name_zh TEXT,
    home_name_en TEXT,
    away_name_en TEXT,
    home_score INTEGER,
    away_score INTEGER,
    status TEXT NOT NULL,
    stage TEXT,
    grp TEXT,
    venue TEXT,
    time_raw TEXT,
    card_json TEXT NOT NULL
);

CREATE INDEX IF NOT EXISTS idx_tm_year_date ON tournament_matches(year, date);

CREATE TABLE IF NOT EXISTS group_standings (
    year INTEGER NOT NULL,
    grp TEXT NOT NULL,
    rank INTEGER NOT NULL,
    team_id TEXT NOT NULL,
    name_zh TEXT,
    name_en TEXT,
    played INTEGER NOT NULL DEFAULT 0,
    won INTEGER NOT NULL DEFAULT 0,
    drawn INTEGER NOT NULL DEFAULT 0,
    lost INTEGER NOT NULL DEFAULT 0,
    goals_for INTEGER NOT NULL DEFAULT 0,
    goals_against INTEGER NOT NULL DEFAULT 0,
    goal_diff INTEGER NOT NULL DEFAULT 0,
    points INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL DEFAULT 'active',
    PRIMARY KEY (year, grp, team_id)
);

CREATE TABLE IF NOT EXISTS team_tournament (
    year INTEGER NOT NULL,
    team_id TEXT NOT NULL,
    name_zh TEXT,
    name_en TEXT,
    grp TEXT,
    status TEXT NOT NULL DEFAULT 'active',
    played INTEGER NOT NULL DEFAULT 0,
    won INTEGER NOT NULL DEFAULT 0,
    drawn INTEGER NOT NULL DEFAULT 0,
    lost INTEGER NOT NULL DEFAULT 0,
    goals_for INTEGER NOT NULL DEFAULT 0,
    goals_against INTEGER NOT NULL DEFAULT 0,
    points INTEGER NOT NULL DEFAULT 0,
    win_rate REAL,
    PRIMARY KEY (year, team_id)
);

CREATE TABLE IF NOT EXISTS odds_snapshots (
    match_id TEXT PRIMARY KEY,
    bookmaker TEXT NOT NULL,
    home_odds REAL,
    draw_odds REAL,
    away_odds REAL,
    fetched_at TEXT NOT NULL
);
"""


class TournamentDatabase:
    def __init__(self, db_path: Path | None = None) -> None:
        self._db_path = db_path or settings.tournament_db_path
        self._conn: sqlite3.Connection | None = None

    async def connect(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self._open)

    def _open(self) -> None:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        self._conn.executescript(_SCHEMA)

    async def close(self) -> None:
        if self._conn:
            await asyncio.to_thread(self._conn.close)
            self._conn = None

    def is_populated(self, year: int | None = None) -> bool:
        if self._conn is None:
            return False
        yr = year or settings.tournament_year
        row = self._conn.execute(
            "SELECT value FROM pipeline_meta WHERE key = ?",
            (f"snapshot_{yr}",),
        ).fetchone()
        return row is not None

    async def get_meta(self) -> dict[str, Any]:
        await asyncio.to_thread(self._open)
        assert self._conn
        rows = self._conn.execute("SELECT key, value, updated_at FROM pipeline_meta").fetchall()
        return {r["key"]: {"value": r["value"], "updated_at": r["updated_at"]} for r in rows}

    async def sync_snapshot(self, snapshot: dict[str, Any]) -> dict[str, int]:
        """Replace tournament tables from a computed snapshot dict."""
        return await asyncio.to_thread(self._sync_snapshot, snapshot)

    def _sync_snapshot(self, snapshot: dict[str, Any]) -> dict[str, int]:
        self._open()
        assert self._conn
        year = int(snapshot["year"])
        now = snapshot.get("synced_at") or datetime.now(timezone.utc).isoformat()

        self._conn.execute("DELETE FROM tournament_matches WHERE year = ?", (year,))
        self._conn.execute("DELETE FROM group_standings WHERE year = ?", (year,))
        self._conn.execute("DELETE FROM team_tournament WHERE year = ?", (year,))

        match_count = 0
        for card in snapshot.get("matches", []):
            home = card["home"]
            away = card["away"]
            self._conn.execute(
                """
                INSERT INTO tournament_matches VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    card["match_id"],
                    year,
                    card["date"],
                    card.get("kickoff_display"),
                    card.get("kickoff_utc"),
                    home.get("team_id"),
                    away.get("team_id"),
                    home.get("name_zh"),
                    away.get("name_zh"),
                    home.get("name_en"),
                    away.get("name_en"),
                    home.get("score"),
                    away.get("score"),
                    card["status"],
                    card.get("stage"),
                    card.get("group"),
                    card.get("venue"),
                    card.get("time_raw"),
                    json.dumps(card, ensure_ascii=False),
                ),
            )
            match_count += 1

        standing_count = 0
        for group in snapshot.get("standings", []):
            grp = group["group"]
            for row in group["rows"]:
                self._conn.execute(
                    """
                    INSERT INTO group_standings VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                    """,
                    (
                        year,
                        grp,
                        row["rank"],
                        row["team_id"],
                        row.get("name_zh"),
                        row.get("name_en"),
                        row["played"],
                        row["won"],
                        row["drawn"],
                        row["lost"],
                        row["goals_for"],
                        row["goals_against"],
                        row["goal_diff"],
                        row["points"],
                        row["status"],
                    ),
                )
                standing_count += 1

        team_count = 0
        for team in snapshot.get("teams", []):
            self._conn.execute(
                """
                INSERT INTO team_tournament VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?)
                """,
                (
                    year,
                    team["team_id"],
                    team.get("name_zh"),
                    team.get("name_en"),
                    team.get("group"),
                    team["status"],
                    team["played"],
                    team["won"],
                    team["drawn"],
                    team["lost"],
                    team["goals_for"],
                    team["goals_against"],
                    team["points"],
                    team.get("win_rate"),
                ),
            )
            team_count += 1

        tournament = snapshot.get("tournament", {})
        self._conn.execute(
            """
            INSERT OR REPLACE INTO pipeline_meta (key, value, updated_at) VALUES (?,?,?)
            """,
            (f"snapshot_{year}", json.dumps(tournament, ensure_ascii=False), now),
        )
        self._conn.execute(
            """
            INSERT OR REPLACE INTO pipeline_meta (key, value, updated_at) VALUES (?,?,?)
            """,
            ("last_sync_at", now, now),
        )
        self._conn.execute(
            """
            INSERT OR REPLACE INTO pipeline_meta (key, value, updated_at) VALUES (?,?,?)
            """,
            (
                f"counts_{year}",
                json.dumps(
                    {
                        "matches": match_count,
                        "standings_rows": standing_count,
                        "teams": team_count,
                    }
                ),
                now,
            ),
        )
        self._conn.commit()
        return {"matches": match_count, "standings_rows": standing_count, "teams": team_count}

    async def fetch_matches_on_date(
        self,
        date_str: str,
        year: int | None = None,
        tz_name: str = "Asia/Shanghai",
    ) -> dict[str, Any]:
        from datetime import date as date_type

        from app.services.match_schedule import filter_cards_by_beijing_date

        yr = year or settings.tournament_year
        await asyncio.to_thread(self._open)
        assert self._conn
        rows = self._conn.execute(
            "SELECT card_json FROM tournament_matches WHERE year = ? ORDER BY kickoff_utc",
            (yr,),
        ).fetchall()
        cards = [json.loads(r["card_json"]) for r in rows]
        target = date_type.fromisoformat(date_str)
        day_cards = filter_cards_by_beijing_date(cards, target, tz_name)
        odds_map = await self.fetch_odds_map([c["match_id"] for c in day_cards])
        from app.tools.odds import attach_odds_to_cards

        day_cards = attach_odds_to_cards(day_cards, odds_map)
        return {"date": date_str, "timezone": tz_name, "matches": day_cards}

    async def fetch_all_match_cards(self, year: int | None = None) -> list[dict[str, Any]]:
        yr = year or settings.tournament_year
        await asyncio.to_thread(self._open)
        assert self._conn
        rows = self._conn.execute(
            "SELECT card_json FROM tournament_matches WHERE year = ?",
            (yr,),
        ).fetchall()
        return [json.loads(r["card_json"]) for r in rows]

    async def upsert_odds(self, records: list[dict[str, Any]]) -> int:
        return await asyncio.to_thread(self._upsert_odds, records)

    def _upsert_odds(self, records: list[dict[str, Any]]) -> int:
        self._open()
        assert self._conn
        now = datetime.now(timezone.utc).isoformat()
        count = 0
        for r in records:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO odds_snapshots
                (match_id, bookmaker, home_odds, draw_odds, away_odds, fetched_at)
                VALUES (?,?,?,?,?,?)
                """,
                (
                    r["match_id"],
                    r.get("bookmaker", "unknown"),
                    r.get("home"),
                    r.get("draw"),
                    r.get("away"),
                    r.get("fetched_at") or now,
                ),
            )
            count += 1
        if count:
            self._conn.execute(
                """
                INSERT OR REPLACE INTO pipeline_meta (key, value, updated_at) VALUES (?,?,?)
                """,
                ("last_odds_fetch_at", now, now),
            )
        self._conn.commit()
        return count

    async def fetch_odds_map(self, match_ids: list[str]) -> dict[str, dict[str, Any]]:
        if not match_ids:
            return {}
        return await asyncio.to_thread(self._fetch_odds_map, match_ids)

    def _fetch_odds_map(self, match_ids: list[str]) -> dict[str, dict[str, Any]]:
        self._open()
        assert self._conn
        placeholders = ",".join("?" * len(match_ids))
        rows = self._conn.execute(
            f"""
            SELECT match_id, bookmaker, home_odds, draw_odds, away_odds, fetched_at
            FROM odds_snapshots WHERE match_id IN ({placeholders})
            """,
            match_ids,
        ).fetchall()
        out: dict[str, dict[str, Any]] = {}
        for r in rows:
            out[r["match_id"]] = {
                "bookmaker": r["bookmaker"],
                "home": r["home_odds"],
                "draw": r["draw_odds"],
                "away": r["away_odds"],
                "updated_at": to_beijing_display(r["fetched_at"]),
            }
        return out

    def has_odds(self) -> bool:
        self._open()
        assert self._conn
        row = self._conn.execute("SELECT COUNT(*) AS c FROM odds_snapshots").fetchone()
        return bool(row and row["c"] > 0)

    async def fetch_standings(self, year: int | None = None) -> list[dict[str, Any]]:
        yr = year or settings.tournament_year
        await asyncio.to_thread(self._open)
        assert self._conn
        rows = self._conn.execute(
            """
            SELECT grp, rank, team_id, name_zh, name_en, played, won, drawn, lost,
                   goals_for, goals_against, goal_diff, points, status
            FROM group_standings WHERE year = ?
            ORDER BY grp, rank
            """,
            (yr,),
        ).fetchall()
        groups: dict[str, list[dict[str, Any]]] = {}
        for r in rows:
            groups.setdefault(r["grp"], []).append(
                {
                    "rank": r["rank"],
                    "team_id": r["team_id"],
                    "name_zh": r["name_zh"],
                    "name_en": r["name_en"],
                    "played": r["played"],
                    "won": r["won"],
                    "drawn": r["drawn"],
                    "lost": r["lost"],
                    "goals_for": r["goals_for"],
                    "goals_against": r["goals_against"],
                    "goal_diff": r["goal_diff"],
                    "points": r["points"],
                    "status": r["status"],
                }
            )
        return [{"group": g, "rows": groups[g]} for g in sorted(groups)]

    async def fetch_teams(
        self,
        year: int | None = None,
        status: str | None = None,
    ) -> list[dict[str, Any]]:
        yr = year or settings.tournament_year
        await asyncio.to_thread(self._open)
        assert self._conn
        sql = """
            SELECT team_id, name_zh, name_en, grp, status, played, won, drawn, lost,
                   goals_for, goals_against, points, win_rate
            FROM team_tournament WHERE year = ?
        """
        params: list[Any] = [yr]
        if status:
            sql += " AND status = ?"
            params.append(status)
        sql += " ORDER BY name_zh"
        rows = self._conn.execute(sql, params).fetchall()
        return [
            {
                "team_id": r["team_id"],
                "name_zh": r["name_zh"],
                "name_en": r["name_en"],
                "group": r["grp"],
                "status": r["status"],
                "played": r["played"],
                "won": r["won"],
                "drawn": r["drawn"],
                "lost": r["lost"],
                "goals_for": r["goals_for"],
                "goals_against": r["goals_against"],
                "points": r["points"],
                "win_rate": r["win_rate"],
            }
            for r in rows
        ]

    async def fetch_tournament_info(self, year: int | None = None) -> dict[str, Any] | None:
        yr = year or settings.tournament_year
        await asyncio.to_thread(self._open)
        assert self._conn
        row = self._conn.execute(
            "SELECT value, updated_at FROM pipeline_meta WHERE key = ?",
            (f"snapshot_{yr}",),
        ).fetchone()
        if not row:
            return None
        info = json.loads(row["value"])
        info["data_updated_at"] = to_beijing_display(row["updated_at"])
        return info
