#!/usr/bin/env python3
"""Lightweight sync: recompute tournament snapshot from local JSON (cron-friendly)."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.services.tournament import sync_tournament_to_db
from app.tools.tournament_db import TournamentDatabase


async def main_async(year: int | None) -> None:
    db = TournamentDatabase(settings.tournament_db_path)
    await db.connect()
    try:
        result = await sync_tournament_to_db(db, year, export_json=True)
    finally:
        await db.close()
    print(f"synced {result['year']} at {result['synced_at']}")
    print(f"counts: {result['counts']}")


def main() -> None:
    parser = argparse.ArgumentParser(description="Sync tournament.db from worldcup JSON")
    parser.add_argument("--year", type=int, default=None)
    args = parser.parse_args()
    asyncio.run(main_async(args.year))


if __name__ == "__main__":
    main()
