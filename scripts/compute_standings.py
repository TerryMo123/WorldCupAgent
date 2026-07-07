#!/usr/bin/env python3
"""Compute standings from worldcup JSON and persist to tournament.db + JSON snapshot."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.services.tournament import build_tournament_snapshot, export_snapshot_json, sync_tournament_to_db
from app.tools.tournament_db import TournamentDatabase


async def run(year: int | None, export_json: bool) -> None:
    yr = year or settings.tournament_year
    print(f"Computing tournament snapshot for {yr}...")
    snapshot = build_tournament_snapshot(yr)
    print(f"  matches:   {len(snapshot['matches'])}")
    print(f"  groups:    {len(snapshot['standings'])}")
    print(f"  teams:     {len(snapshot['teams'])}")

    db = TournamentDatabase(settings.tournament_db_path)
    await db.connect()
    try:
        result = await sync_tournament_to_db(db, yr, export_json=export_json)
    finally:
        await db.close()

    print(f"SQLite: {settings.tournament_db_path}")
    print(f"Counts: {result['counts']}")
    if result.get("json_path"):
        print(f"JSON snapshot: {result['json_path']}")
    print("compute_standings OK.")


def main() -> None:
    parser = argparse.ArgumentParser(description="Compute and persist tournament standings")
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--no-json", action="store_true", help="Skip JSON snapshot export")
    args = parser.parse_args()
    asyncio.run(run(args.year, export_json=not args.no_json))


if __name__ == "__main__":
    main()
