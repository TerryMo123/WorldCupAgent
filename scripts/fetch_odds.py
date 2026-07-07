#!/usr/bin/env python3
"""Fetch 1X2 odds and persist to tournament.db (cron-friendly)."""

from __future__ import annotations

import argparse
import asyncio
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.services.match_schedule import refresh_match_card
from app.tools.odds import fetch_odds_for_cards
from app.tools.tournament_db import TournamentDatabase


async def run(year: int | None, mock_only: bool) -> None:
    yr = year or settings.tournament_year
    db = TournamentDatabase(settings.tournament_db_path)
    await db.connect()
    try:
        if not db.is_populated(yr):
            print("Tournament DB empty. Run: python scripts/compute_standings.py")
            sys.exit(1)

        cards = await db.fetch_all_match_cards(yr)
        cards = [refresh_match_card(c) for c in cards]
        scheduled = [c for c in cards if c.get("home", {}).get("score") is None]
        print(f"Backend: {settings.odds_backend}")
        print(f"Scheduled matches (no score): {len(scheduled)}")

        if mock_only:
            from app.tools.odds import generate_mock_odds

            records = generate_mock_odds(scheduled)
        else:
            records = await fetch_odds_for_cards(cards)

        count = await db.upsert_odds(records)
        print(f"Upserted {count} odds rows → {settings.tournament_db_path}")
        if records:
            sample = records[0]
            print(
                f"Sample: {sample['match_id']} "
                f"{sample.get('home')}/{sample.get('draw')}/{sample.get('away')} ({sample.get('bookmaker')})"
            )
    finally:
        await db.close()


def main() -> None:
    parser = argparse.ArgumentParser(description="Fetch match odds into tournament.db")
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--mock-only", action="store_true", help="Force mock odds")
    args = parser.parse_args()
    if args.mock_only:
        import app.config as cfg

        cfg.settings.odds_backend = "mock"
    asyncio.run(run(args.year, args.mock_only))


if __name__ == "__main__":
    main()
