import asyncio
import csv
import sqlite3
import time
from pathlib import Path
from typing import Any

import structlog

from app.config import settings
from app.models.response import ToolResult
from app.tools.teams import normalize_pair

logger = structlog.get_logger()


class StatsDatabase:
    """SQLite stats store loaded from CSV (demo data)."""

    def __init__(self, db_path: Path, data_dir: Path) -> None:
        self._db_path = db_path
        self._data_dir = data_dir
        self._conn: sqlite3.Connection | None = None

    async def connect(self) -> None:
        self._db_path.parent.mkdir(parents=True, exist_ok=True)
        await asyncio.to_thread(self._init_db)

    async def close(self) -> None:
        if self._conn:
            await asyncio.to_thread(self._conn.close)
            self._conn = None

    def _init_db(self) -> None:
        if self._conn is None:
            self._conn = sqlite3.connect(self._db_path, check_same_thread=False)
            self._conn.row_factory = sqlite3.Row
        self._conn.executescript(
            """
            DROP TABLE IF EXISTS teams;
            DROP TABLE IF EXISTS matches;
            CREATE TABLE teams (
                team_id TEXT PRIMARY KEY,
                name_zh TEXT,
                name_en TEXT,
                fifa_rank INTEGER,
                coach TEXT,
                style TEXT,
                confederation TEXT,
                fifa_code TEXT
            );
            CREATE TABLE matches (
                id INTEGER PRIMARY KEY AUTOINCREMENT,
                date TEXT,
                home_team TEXT,
                away_team TEXT,
                home_score INTEGER,
                away_score INTEGER,
                competition TEXT,
                year TEXT,
                round TEXT,
                grp TEXT,
                venue TEXT,
                pen_home INTEGER,
                pen_away INTEGER
            );
            """
        )
        teams_csv = self._data_dir / "teams.csv"
        matches_csv = self._data_dir / "matches.csv"
        with teams_csv.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                rank = row.get("fifa_rank", "").strip()
                self._conn.execute(
                    "INSERT INTO teams VALUES (?,?,?,?,?,?,?,?)",
                    (
                        row["team_id"],
                        row.get("name_zh", ""),
                        row["name_en"],
                        int(rank) if rank else None,
                        row.get("coach", ""),
                        row.get("style", ""),
                        row.get("confederation", ""),
                        row.get("fifa_code", ""),
                    ),
                )
        with matches_csv.open(encoding="utf-8") as f:
            for row in csv.DictReader(f):
                pen_h = row.get("pen_home", "").strip()
                pen_a = row.get("pen_away", "").strip()
                self._conn.execute(
                    "INSERT INTO matches "
                    "(date,home_team,away_team,home_score,away_score,competition,year,round,grp,venue,pen_home,pen_away) "
                    "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
                    (
                        row["date"],
                        row["home_team"],
                        row["away_team"],
                        int(row["home_score"]),
                        int(row["away_score"]),
                        row["competition"],
                        row.get("year", ""),
                        row.get("round", ""),
                        row.get("group", ""),
                        row.get("venue", ""),
                        int(pen_h) if pen_h else None,
                        int(pen_a) if pen_a else None,
                    ),
                )
        self._conn.commit()

    def _recent_form(self, team_id: str, limit: int = 10) -> dict[str, Any]:
        assert self._conn
        rows = self._conn.execute(
            """
            SELECT date, home_team, away_team, home_score, away_score, competition
            FROM matches
            WHERE home_team = ? OR away_team = ?
            ORDER BY date DESC
            LIMIT ?
            """,
            (team_id, team_id, limit),
        ).fetchall()
        wins = draws = losses = goals_for = goals_against = 0
        recent: list[dict[str, Any]] = []
        for r in rows:
            home = r["home_team"] == team_id
            gf = r["home_score"] if home else r["away_score"]
            ga = r["away_score"] if home else r["home_score"]
            if gf > ga:
                wins += 1
                result = "W"
            elif gf < ga:
                losses += 1
                result = "L"
            else:
                draws += 1
                result = "D"
            goals_for += gf
            goals_against += ga
            opp = r["away_team"] if home else r["home_team"]
            recent.append(
                {
                    "date": r["date"],
                    "opponent": opp,
                    "score": f"{gf}-{ga}",
                    "result": result,
                    "competition": r["competition"],
                }
            )
        played = wins + draws + losses
        win_rate = round(wins / played, 3) if played else 0.0
        return {
            "played": played,
            "wins": wins,
            "draws": draws,
            "losses": losses,
            "goals_for": goals_for,
            "goals_against": goals_against,
            "win_rate": win_rate,
            "recent_matches": recent,
        }

    def _head_to_head(self, team_a: str, team_b: str) -> dict[str, Any]:
        assert self._conn
        rows = self._conn.execute(
            """
            SELECT date, home_team, away_team, home_score, away_score, competition
            FROM matches
            WHERE (home_team = ? AND away_team = ?)
               OR (home_team = ? AND away_team = ?)
            ORDER BY date DESC
            """,
            (team_a, team_b, team_b, team_a),
        ).fetchall()
        a_wins = b_wins = draws = 0
        meetings: list[dict[str, Any]] = []
        for r in rows:
            if r["home_team"] == team_a:
                a_score, b_score = r["home_score"], r["away_score"]
            else:
                a_score, b_score = r["away_score"], r["home_score"]
            if a_score > b_score:
                a_wins += 1
            elif a_score < b_score:
                b_wins += 1
            else:
                draws += 1
            meetings.append(
                {
                    "date": r["date"],
                    "score": f"{r['home_score']}-{r['away_score']}",
                    "competition": r["competition"],
                }
            )
        total = a_wins + b_wins + draws
        return {
            "total_meetings": total,
            "team_a_wins": a_wins,
            "team_b_wins": b_wins,
            "draws": draws,
            "meetings": meetings,
        }

    def _team_profile(self, team_id: str) -> dict[str, Any] | None:
        assert self._conn
        row = self._conn.execute("SELECT * FROM teams WHERE team_id = ?", (team_id,)).fetchone()
        if not row:
            return None
        return dict(row)

    def compare(self, team_a: str, team_b: str, form_limit: int = 10) -> dict[str, Any]:
        profile_a = self._team_profile(team_a)
        profile_b = self._team_profile(team_b)
        if not profile_a or not profile_b:
            missing = []
            if not profile_a:
                missing.append(team_a)
            if not profile_b:
                missing.append(team_b)
            raise ValueError(f"Unknown team(s): {', '.join(missing)}")
        form_a = self._recent_form(team_a, form_limit)
        form_b = self._recent_form(team_b, form_limit)
        h2h = self._head_to_head(team_a, team_b)
        # Simple heuristic win probability from recent form + H2H
        score_a = form_a["win_rate"] * 0.6 + (h2h["team_a_wins"] / h2h["total_meetings"] if h2h["total_meetings"] else 0.5) * 0.4
        score_b = form_b["win_rate"] * 0.6 + (h2h["team_b_wins"] / h2h["total_meetings"] if h2h["total_meetings"] else 0.5) * 0.4
        total = score_a + score_b or 1.0
        return {
            "team_a": {"id": team_a, **profile_a, "form": form_a},
            "team_b": {"id": team_b, **profile_b, "form": form_b},
            "head_to_head": h2h,
            "model_hint": {
                "team_a_win_prob": round(score_a / total, 3),
                "team_b_win_prob": round(score_b / total, 3),
                "note": "基于近期胜率与历史交锋的简易估算，仅供参考",
            },
        }

    async def compare_async(self, team_a: str, team_b: str) -> dict[str, Any]:
        await asyncio.sleep(settings.mock_stats_delay)
        return await asyncio.to_thread(self.compare, team_a, team_b)


async def fetch_stats(team_a: str, team_b: str, db: StatsDatabase) -> ToolResult:
    """Query structured win rates and head-to-head stats."""
    start = time.perf_counter()
    tool_name = "stats"
    norm_a, norm_b = normalize_pair(team_a, team_b)
    if not norm_a or not norm_b:
        latency_ms = (time.perf_counter() - start) * 1000
        return ToolResult(
            tool_name=tool_name,
            success=False,
            error=f"无法识别球队: team_a={team_a}, team_b={team_b}",
            latency_ms=latency_ms,
        )
    try:
        data = await db.compare_async(norm_a, norm_b)
        latency_ms = (time.perf_counter() - start) * 1000
        logger.info("tool_completed", tool=tool_name, latency_ms=round(latency_ms, 2), success=True)
        return ToolResult(
            tool_name=tool_name,
            success=True,
            data=data,
            latency_ms=latency_ms,
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - start) * 1000
        logger.warning("tool_failed", tool=tool_name, latency_ms=round(latency_ms, 2), error=str(exc))
        return ToolResult(
            tool_name=tool_name,
            success=False,
            error=str(exc),
            latency_ms=latency_ms,
        )
