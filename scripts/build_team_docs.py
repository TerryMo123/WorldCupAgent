#!/usr/bin/env python3
"""Build docs/teams/*.md skeletons from 2026 squads.json + SQLite stats."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sqlite3
import sys
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.tools.teams import normalize_team_id, reload_team_registry

POS_ZH = {"GK": "门将", "DF": "后卫", "MF": "中场", "FW": "前锋"}


def slugify(name: str) -> str:
    s = name.strip().lower().replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def resolve_team_id(name: str) -> str:
    return normalize_team_id(name) or slugify(name)


def load_squads(path: Path) -> list[dict[str, Any]]:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, list):
        raise ValueError(f"Expected JSON array in {path}")
    return data


def load_team_meta(path: Path) -> dict[str, dict[str, Any]]:
    if not path.exists():
        return {}
    teams = json.loads(path.read_text(encoding="utf-8"))
    out: dict[str, dict[str, Any]] = {}
    for t in teams:
        name = t.get("name") or t.get("name_normalised")
        if not name:
            continue
        out[resolve_team_id(name)] = t
    return out


def load_csv_teams(path: Path) -> dict[str, dict[str, str]]:
    if not path.exists():
        return {}
    out: dict[str, dict[str, str]] = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            out[row["team_id"]] = row
    return out


def _form_from_rows(rows: list[sqlite3.Row]) -> dict[str, Any]:
    wins = draws = losses = goals_for = goals_against = 0
    recent: list[dict[str, str]] = []
    for r in rows:
        home_id, away_id = r["home_team"], r["away_team"]
        # rows are for a single team_id filter; caller sets perspective
        team_id = r["_team_id"]
        home = home_id == team_id
        gf = r["home_score"] if home else r["away_score"]
        ga = r["away_score"] if home else r["home_score"]
        if gf > ga:
            wins += 1
            result = "胜"
        elif gf < ga:
            losses += 1
            result = "负"
        else:
            draws += 1
            result = "平"
        goals_for += gf
        goals_against += ga
        opp = away_id if home else home_id
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
    return {
        "played": played,
        "wins": wins,
        "draws": draws,
        "losses": losses,
        "goals_for": goals_for,
        "goals_against": goals_against,
        "win_rate": round(wins / played, 3) if played else 0.0,
        "recent_matches": recent,
    }


def fetch_team_form(conn: sqlite3.Connection, team_id: str, *, year: str | None = None, limit: int = 10) -> dict[str, Any]:
    sql = """
        SELECT date, home_team, away_team, home_score, away_score, competition, year
        FROM matches
        WHERE (home_team = ? OR away_team = ?)
    """
    params: list[Any] = [team_id, team_id]
    if year:
        sql += " AND year = ?"
        params.append(year)
    sql += " ORDER BY date DESC LIMIT ?"
    params.append(limit)
    rows = conn.execute(sql, params).fetchall()
    enriched: list[dict[str, Any]] = []
    for r in rows:
        enriched.append({**dict(r), "_team_id": team_id})

    class RowDict:
        def __init__(self, d: dict[str, Any]):
            self._d = d

        def __getitem__(self, key: str) -> Any:
            return self._d[key]

    return _form_from_rows([RowDict(d) for d in enriched])


def fetch_world_cup_titles(conn: sqlite3.Connection, team_id: str) -> int:
    row = conn.execute(
        """
        SELECT COUNT(*) AS c FROM matches
        WHERE competition LIKE '%世界杯%'
          AND competition LIKE '%决赛'
          AND competition NOT LIKE '%半决赛%'
          AND competition NOT LIKE '%季军%'
          AND (
            (home_team = ? AND home_score > away_score)
            OR (away_team = ? AND away_score > home_score)
            OR (home_team = ? AND pen_home IS NOT NULL AND pen_home > pen_away)
            OR (away_team = ? AND pen_away IS NOT NULL AND pen_away > pen_home)
          )
        """,
        (team_id, team_id, team_id, team_id),
    ).fetchone()
    return int(row["c"]) if row else 0


def pick_key_players(players: list[dict], max_players: int = 6) -> list[dict]:
    """Pick likely starters / star players by position priority."""
    by_pos: dict[str, list[dict]] = {"FW": [], "MF": [], "DF": [], "GK": []}
    for p in sorted(players, key=lambda x: x.get("number", 99)):
        pos = p.get("pos", "MF")
        if pos in by_pos:
            by_pos[pos].append(p)
    picked: list[dict] = []
    for pos, limit in [("FW", 2), ("MF", 2), ("DF", 1), ("GK", 1)]:
        picked.extend(by_pos[pos][:limit])
        if len(picked) >= max_players:
            break
    return picked[:max_players]


def infer_pros_cons(
    all_form: dict[str, Any],
    wc_form: dict[str, Any],
    wc_titles: int,
    squad_size: int,
) -> tuple[list[str], list[str]]:
    pros: list[str] = []
    cons: list[str] = []

    if wc_titles > 0:
        pros.append(f"世界杯历史冠军 {wc_titles} 次，大赛底蕴深厚")
    if all_form["played"] >= 5 and all_form["win_rate"] >= 0.5:
        pros.append(f"历届世界杯胜率 {all_form['win_rate']*100:.1f}%（{all_form['played']} 场）")
    if all_form["goals_for"] > all_form["goals_against"] and all_form["played"]:
        pros.append(f"历届世界杯进 {all_form['goals_for']} 失 {all_form['goals_against']}，进攻效率较好")
    if squad_size >= 26:
        pros.append(f"2026 世界杯名单 {squad_size} 人，阵容储备充足")

    if all_form["played"] >= 5 and all_form["win_rate"] < 0.35:
        cons.append(f"历届世界杯胜率偏低（{all_form['win_rate']*100:.1f}%）")
    if all_form["goals_against"] > all_form["goals_for"] and all_form["played"]:
        cons.append(f"历届世界杯失球（{all_form['goals_against']}）多于进球（{all_form['goals_for']}）")
    if wc_form["played"] == 0:
        cons.append("2026 世界杯暂无已完成的比赛数据（或尚未开赛）")

    if not pros:
        pros.append("（待补充：根据战绩与阵容人工完善）")
    if not cons:
        cons.append("（待补充：根据对手与战术人工完善）")
    return pros, cons


def format_recent_status(all_form: dict[str, Any], wc_form: dict[str, Any], year: str) -> str:
    lines: list[str] = []
    if wc_form["played"]:
        lines.append(
            f"{year} 世界杯已赛 {wc_form['played']} 场："
            f"{wc_form['wins']} 胜 {wc_form['draws']} 平 {wc_form['losses']} 负，"
            f"进 {wc_form['goals_for']} 失 {wc_form['goals_against']}。"
        )
        if wc_form["recent_matches"]:
            m = wc_form["recent_matches"][0]
            lines.append(f"最近一场：{m['date']} vs {m['opponent']} {m['score']}（{m['competition']}）。")
    else:
        lines.append(f"{year} 世界杯暂无已结束比赛记录。")

    if all_form["played"]:
        lines.append(
            f"历届世界杯共 {all_form['played']} 场，胜率 {all_form['win_rate']*100:.1f}%，"
            f"进 {all_form['goals_for']} 失 {all_form['goals_against']}。"
        )
    return "\n".join(lines)


def build_markdown(
    team_id: str,
    squad: dict[str, Any],
    csv_row: dict[str, str],
    meta: dict[str, Any],
    all_form: dict[str, Any],
    wc_form: dict[str, Any],
    wc_titles: int,
    year: str,
) -> str:
    display = csv_row.get("name_zh") or squad.get("name") or csv_row.get("name_en") or team_id
    fifa_code = squad.get("fifa_code") or csv_row.get("fifa_code", "")
    group = squad.get("group") or meta.get("group", "")
    conf = csv_row.get("confederation") or meta.get("confed") or meta.get("continent", "")
    coach = csv_row.get("coach", "").strip()
    style = csv_row.get("style", "").strip()
    players = squad.get("players") or []
    key_players = pick_key_players(players)
    pros, cons = infer_pros_cons(all_form, wc_form, wc_titles, len(players))

    lines = [f"# {display}", ""]

    lines.extend(["## 基本信息", ""])
    lines.append(f"- 球队 ID：`{team_id}`")
    if fifa_code:
        lines.append(f"- FIFA 代码：{fifa_code}")
    if conf:
        lines.append(f"- 足协/大区：{conf}")
    if group:
        lines.append(f"- {year} 世界杯小组：{group}")
    if coach:
        lines.append(f"- 主教练：{coach}")
    lines.append("")

    lines.extend(["## 战术风格", ""])
    if style:
        lines.append(style)
    else:
        lines.append("（待补充：结合阵容与教练体系描述，如控球/反击/高位压迫等）")
    lines.append("")

    lines.extend(["## 核心球员", ""])
    lines.append(f"（来源：{year} 世界杯名单，共 {len(players)} 人）")
    lines.append("")
    for p in key_players:
        pos = POS_ZH.get(p.get("pos", ""), p.get("pos", ""))
        club = (p.get("club") or {}).get("name", "")
        club_part = f"，{club}" if club else ""
        lines.append(f"- {p.get('name', '未知')}（{pos}{club_part}）")
    if len(players) > len(key_players):
        lines.append(f"- … 另有 {len(players) - len(key_players)} 名球员未列出")
    lines.append("")

    lines.extend(["## 优势", ""])
    for p in pros:
        lines.append(f"- {p}")
    lines.append("")

    lines.extend(["## 劣势", ""])
    for c in cons:
        lines.append(f"- {c}")
    lines.append("")

    lines.extend(["## 近期状态", ""])
    lines.append(format_recent_status(all_form, wc_form, year))
    lines.append("")

    lines.extend(
        [
            "## 数据来源",
            "",
            f"- `data/{year}/worldcup.squads.json`",
            "- `data/worldcup.db`（由 matches.csv 导入）",
            "- `data/teams.csv`",
            "",
            "> 本文为脚本自动生成的骨架，「战术风格」及优劣势细节建议人工校对或用 LLM 补全。",
            "",
        ]
    )
    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Generate docs/teams/*.md from squads + SQLite")
    parser.add_argument("--year", default="2026", help="World Cup year (default: 2026)")
    parser.add_argument(
        "--squads",
        type=Path,
        default=None,
        help="Path to worldcup.squads.json (default: data/YEAR/worldcup.squads.json)",
    )
    parser.add_argument("--db", type=Path, default=settings.db_path)
    parser.add_argument("--docs-dir", type=Path, default=settings.docs_dir)
    parser.add_argument("--teams-csv", type=Path, default=settings.data_dir / "teams.csv")
    parser.add_argument(
        "--teams-meta",
        type=Path,
        default=None,
        help="Path to worldcup.teams.json (default: data/YEAR/worldcup.teams.json)",
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing markdown files")
    parser.add_argument("--dry-run", action="store_true", help="Print paths only, do not write")
    args = parser.parse_args()

    year = args.year
    squads_path = args.squads or (settings.data_dir / year / "worldcup.squads.json")
    teams_meta_path = args.teams_meta or (settings.data_dir / year / "worldcup.teams.json")

    if not squads_path.exists():
        print(f"Squads file not found: {squads_path}", file=sys.stderr)
        sys.exit(1)
    if not args.db.exists():
        print(f"SQLite not found: {args.db}", file=sys.stderr)
        print("Run: python scripts/ingest.py", file=sys.stderr)
        sys.exit(1)

    reload_team_registry()
    squads = load_squads(squads_path)
    meta_by_id = load_team_meta(teams_meta_path)
    csv_teams = load_csv_teams(args.teams_csv)

    conn = sqlite3.connect(f"file:{args.db}?mode=ro", uri=True)
    conn.row_factory = sqlite3.Row

    args.docs_dir.mkdir(parents=True, exist_ok=True)
    written = skipped = 0

    for squad in squads:
        name = squad.get("name", "")
        team_id = resolve_team_id(name)
        out_path = args.docs_dir / f"{team_id}.md"

        if out_path.exists() and not args.force:
            skipped += 1
            continue

        csv_row = csv_teams.get(team_id, {})
        meta = meta_by_id.get(team_id, {})
        all_form = fetch_team_form(conn, team_id, limit=20)
        wc_form = fetch_team_form(conn, team_id, year=year, limit=10)
        wc_titles = fetch_world_cup_titles(conn, team_id)

        md = build_markdown(team_id, squad, csv_row, meta, all_form, wc_form, wc_titles, year)

        if args.dry_run:
            print(f"would write: {out_path}")
        else:
            out_path.write_text(md, encoding="utf-8")
            print(f"wrote: {out_path}")
        written += 1

    conn.close()
    print(f"\nDone: {written} generated, {skipped} skipped (use --force to overwrite)")


if __name__ == "__main__":
    main()
