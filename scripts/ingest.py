#!/usr/bin/env python3
"""Rebuild SQLite from CSV and sync tournament snapshot. Run pipeline.py for full flow."""

from __future__ import annotations

import argparse
import asyncio
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


async def main(skip_tournament: bool) -> None:
    print(f"Data dir: {settings.data_dir}")
    print(f"DB path:  {settings.db_path}")
    print(f"Tournament DB: {settings.tournament_db_path}")

    reload_team_registry()

    db = StatsDatabase(settings.db_path, settings.data_dir)
    await db.connect()
    sample = await db.compare_async("brazil", "france")
    a = sample["team_a"]
    b = sample["team_b"]
    print(f"Teams loaded: {a.get('name_zh') or a['name_en']} vs {b.get('name_zh') or b['name_en']}")
    print(f"H2H meetings: {sample['head_to_head']['total_meetings']}")
    await db.close()

    if not skip_tournament:
        tdb = TournamentDatabase(settings.tournament_db_path)
        await tdb.connect()
        try:
            result = await sync_tournament_to_db(tdb, export_json=True)
            print(f"Tournament synced: {result['counts']}")
        finally:
            await tdb.close()

    store = create_vector_store()
    await store.connect()
    chunks = await store.search("Brazil France", team_ids=["brazil", "france"])
    print(f"RAG backend: {settings.rag_backend}, sample chunks: {len(chunks)}")
    if settings.rag_backend == "chroma":
        print("Tip: run python scripts/ingest_embeddings.py --force to rebuild vectors")
    await store.close()

    print("Ingest OK.")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--skip-tournament", action="store_true")
    args = parser.parse_args()
    asyncio.run(main(args.skip_tournament))
