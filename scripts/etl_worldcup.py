#!/usr/bin/env python3
"""Convert openfootball worldcup JSON (data/YYYY/*.json) → teams.csv + matches.csv."""

from __future__ import annotations

import argparse
import csv
import json
import re
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
# JSON layout: data/1930/worldcup.json, data/2026/worldcup.teams.json, ...
DEFAULT_JSON_DIR = ROOT / "data"
DEFAULT_OUT_DIR = ROOT / "data"

ROUND_ZH = {
    "final": "决赛",
    "semi-finals": "半决赛",
    "quarter-finals": "八强",
    "round of 16": "十六强",
    "round of 32": "三十二强",
    "match for third place": "季军赛",
    "third place": "季军赛",
}


def slugify(name: str) -> str:
    s = name.strip().lower()
    s = s.replace("&", " and ")
    s = re.sub(r"[^a-z0-9]+", "_", s)
    return s.strip("_")


def competition_label(year: str, round_name: str, group: str | None) -> str:
    r = round_name.lower()
    if "matchday" in r or r.startswith("group"):
        g = f" {group}" if group else ""
        return f"世界杯{year}小组赛{g}"
    for key, zh in ROUND_ZH.items():
        if key in r:
            return f"世界杯{year}{zh}"
    return f"世界杯{year} {round_name}"


def parse_score(match: dict) -> tuple[int | None, int | None, int | None, int | None]:
    """Return home_ft, away_ft, home_pen, away_pen."""
    score = match.get("score") or {}
    ft = score.get("ft")
    if not ft or len(ft) < 2:
        return None, None, None, None
    home_ft, away_ft = int(ft[0]), int(ft[1])
    pen = score.get("p")
    if pen and len(pen) >= 2:
        return home_ft, away_ft, int(pen[0]), int(pen[1])
    return home_ft, away_ft, None, None


def iter_year_dirs(json_dir: Path) -> list[Path]:
    """Return data/YYYY/ subdirs (4-digit year names only)."""
    return sorted(
        p for p in json_dir.iterdir()
        if p.is_dir() and p.name.isdigit() and len(p.name) == 4
    )


def load_team_meta(json_dir: Path) -> dict[str, dict]:
    """Load fifa_code / confederation from worldcup.teams.json when present."""
    meta: dict[str, dict] = {}
    for year_dir in iter_year_dirs(json_dir):
        teams_file = year_dir / "worldcup.teams.json"
        if not teams_file.exists():
            continue
        year = year_dir.name
        try:
            teams = json.loads(teams_file.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            continue
        if not isinstance(teams, list):
            continue
        for t in teams:
            name = t.get("name") or t.get("name_normalised")
            if not name:
                continue
            tid = slugify(name)
            meta[tid] = {
                "team_id": tid,
                "name_en": name,
                "name_zh": "",
                "fifa_rank": "",
                "coach": "",
                "style": "",
                "confederation": t.get("confed", t.get("continent", "")),
                "fifa_code": t.get("fifa_code", ""),
                "last_seen_year": year,
            }
    return meta


def load_overrides(path: Path) -> dict[str, dict]:
    if not path.exists():
        return {}
    out: dict[str, dict] = {}
    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tid = row["team_id"]
            out[tid] = {k: v for k, v in row.items() if v}
    return out


def collect_matches(json_dir: Path) -> tuple[list[dict], set[str]]:
    rows: list[dict] = []
    all_names: set[str] = set()
    for year_dir in iter_year_dirs(json_dir):
        wc_file = year_dir / "worldcup.json"
        if not wc_file.exists():
            continue
        year = year_dir.name
        data = json.loads(wc_file.read_text(encoding="utf-8"))
        for m in data.get("matches", []):
            team1 = (m.get("team1") or "").strip()
            team2 = (m.get("team2") or "").strip()
            if not team1 or not team2:
                continue
            all_names.add(team1)
            all_names.add(team2)
            home_score, away_score, pen_home, pen_away = parse_score(m)
            if home_score is None:
                continue  # skip unplayed fixtures
            rows.append(
                {
                    "date": m.get("date", ""),
                    "home_team": slugify(team1),
                    "away_team": slugify(team2),
                    "home_score": home_score,
                    "away_score": away_score,
                    "competition": competition_label(year, m.get("round", ""), m.get("group")),
                    "year": year,
                    "round": m.get("round", ""),
                    "group": m.get("group", ""),
                    "venue": m.get("ground", ""),
                    "pen_home": pen_home if pen_home is not None else "",
                    "pen_away": pen_away if pen_away is not None else "",
                    "home_team_name": team1,
                    "away_team_name": team2,
                }
            )
    rows.sort(key=lambda r: (r["date"], r["home_team"], r["away_team"]))
    return rows, all_names


def build_teams(
    all_names: set[str],
    meta: dict[str, dict],
    overrides: dict[str, dict],
) -> list[dict]:
    teams: dict[str, dict] = {}
    for name in sorted(all_names):
        tid = slugify(name)
        base = {
            "team_id": tid,
            "name_zh": "",
            "name_en": name,
            "fifa_rank": "",
            "coach": "",
            "style": "",
            "confederation": "",
            "fifa_code": "",
        }
        if tid in meta:
            base.update({k: meta[tid].get(k, "") for k in base if k in meta[tid]})
        if tid in overrides:
            base.update(overrides[tid])
        teams[tid] = base
    return list(teams.values())


def write_csv(path: Path, fieldnames: list[str], rows: list[dict]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    with path.open("w", encoding="utf-8", newline="") as f:
        w = csv.DictWriter(f, fieldnames=fieldnames, extrasaction="ignore")
        w.writeheader()
        w.writerows(rows)


def main() -> None:
    parser = argparse.ArgumentParser(description="ETL worldcup.json → CSV")
    parser.add_argument("--json-dir", type=Path, default=DEFAULT_JSON_DIR)
    parser.add_argument("--out-dir", type=Path, default=DEFAULT_OUT_DIR)
    parser.add_argument("--overrides", type=Path, default=DEFAULT_OUT_DIR / "team_overrides.csv")
    args = parser.parse_args()

    if not args.json_dir.exists():
        print(f"JSON dir not found: {args.json_dir}", file=sys.stderr)
        sys.exit(1)

    meta = load_team_meta(args.json_dir)
    overrides = load_overrides(args.overrides)
    match_rows, all_names = collect_matches(args.json_dir)
    team_rows = build_teams(all_names, meta, overrides)

    match_fields = [
        "date",
        "home_team",
        "away_team",
        "home_score",
        "away_score",
        "competition",
        "year",
        "round",
        "group",
        "venue",
        "pen_home",
        "pen_away",
    ]
    team_fields = [
        "team_id",
        "name_zh",
        "name_en",
        "fifa_rank",
        "coach",
        "style",
        "confederation",
        "fifa_code",
    ]

    teams_path = args.out_dir / "teams.csv"
    matches_path = args.out_dir / "matches.csv"
    write_csv(teams_path, team_fields, team_rows)
    write_csv(matches_path, match_fields, match_rows)

    print(f"Wrote {len(team_rows)} teams → {teams_path}")
    print(f"Wrote {len(match_rows)} matches → {matches_path}")
    print(f"Years: {sorted({r['year'] for r in match_rows})}")
    print("\nNext: python scripts/ingest.py  # rebuild SQLite")


if __name__ == "__main__":
    main()
