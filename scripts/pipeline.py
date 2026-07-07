#!/usr/bin/env python3
"""Full data pipeline: ETL → tournament snapshot → stats SQLite → optional docs/embeddings."""

from __future__ import annotations

import argparse
import asyncio
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings
from app.services.tournament import sync_tournament_to_db
from app.tools.rag import create_vector_store
from app.tools.stats import StatsDatabase
from app.tools.teams import reload_team_registry
from app.tools.tournament_db import TournamentDatabase


def run_script(name: str, extra_args: list[str] | None = None) -> None:
    cmd = [sys.executable, str(ROOT / "scripts" / name), *(extra_args or [])]
    print(f"\n>> {' '.join(cmd)}")
    subprocess.run(cmd, check=True)


async def ingest_stats() -> None:
    reload_team_registry()
    db = StatsDatabase(settings.db_path, settings.data_dir)
    await db.connect()
    sample = await db.compare_async("brazil", "france")
    print(f"Stats OK: {sample['head_to_head']['total_meetings']} H2H meetings")
    await db.close()


async def smoke_rag() -> None:
    store = create_vector_store()
    await store.connect()
    chunks = await store.search("Brazil France", team_ids=["brazil", "france"])
    print(f"RAG smoke: {len(chunks)} chunks ({settings.rag_backend})")
    await store.close()


async def main_async(args: argparse.Namespace) -> None:
    print("=== World Cup Data Pipeline ===")
    print(f"Year: {args.year or settings.tournament_year}")

    if not args.skip_etl:
        run_script("etl_worldcup.py")

    if not args.skip_standings:
        db = TournamentDatabase(settings.tournament_db_path)
        await db.connect()
        try:
            result = await sync_tournament_to_db(db, args.year, export_json=True)
            print(f"Tournament DB synced: {result['counts']}")
        finally:
            await db.close()

    if not args.skip_stats:
        await ingest_stats()

    if not args.skip_rag_smoke:
        await smoke_rag()

    if args.build_docs:
        run_script("build_team_docs.py", ["--force"])

    if args.embeddings:
        run_script("ingest_embeddings.py", ["--force"])

    if args.fetch_odds:
        run_script("fetch_odds.py", ["--mock-only"] if args.odds_mock else [])

    print("\n=== Pipeline complete ===")
    print(f"  tournament.db → {settings.tournament_db_path}")
    print(f"  worldcup.db   → {settings.db_path}")
    print(f"  snapshots     → {settings.tournament_snapshot_dir}/")
    if args.fetch_odds:
        print("  odds          → odds_snapshots table")


def main() -> None:
    parser = argparse.ArgumentParser(description="Run full worldcup data pipeline")
    parser.add_argument("--year", type=int, default=None)
    parser.add_argument("--skip-etl", action="store_true")
    parser.add_argument("--skip-standings", action="store_true")
    parser.add_argument("--skip-stats", action="store_true")
    parser.add_argument("--skip-rag-smoke", action="store_true")
    parser.add_argument("--build-docs", action="store_true", help="Regenerate docs/teams/*.md")
    parser.add_argument("--embeddings", action="store_true", help="Rebuild Chroma vectors (calls DashScope)")
    parser.add_argument("--fetch-odds", action="store_true", help="Fetch odds into tournament.db")
    parser.add_argument("--odds-mock", action="store_true", help="Use mock odds with --fetch-odds")
    args = parser.parse_args()
    asyncio.run(main_async(args))


if __name__ == "__main__":
    main()
