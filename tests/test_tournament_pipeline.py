import pytest

from app.services.tournament import build_tournament_snapshot, sync_tournament_to_db
from app.tools.tournament_db import TournamentDatabase


@pytest.fixture
def tournament_db_path(tmp_path):
    return tmp_path / "tournament.db"


@pytest.mark.asyncio
async def test_build_and_sync_tournament_snapshot(tournament_db_path):
    snapshot = build_tournament_snapshot(2026)
    assert snapshot["year"] == 2026
    assert len(snapshot["matches"]) > 50
    assert len(snapshot["standings"]) == 12
    assert len(snapshot["teams"]) >= 48

    db = TournamentDatabase(tournament_db_path)
    await db.connect()
    try:
        result = await sync_tournament_to_db(db, 2026, export_json=False)
        assert result["counts"]["matches"] == len(snapshot["matches"])
        assert db.is_populated(2026)

        groups = await db.fetch_standings(2026)
        assert len(groups) == 12

        teams = await db.fetch_teams(2026)
        assert len(teams) >= 48

        today = await db.fetch_matches_on_date("2026-07-04")
        assert len(today["matches"]) >= 1
        assert today["matches"][0]["kickoff_display"].startswith("2026-07-04")
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_overview_from_db(tournament_db_path):
    from app.services.tournament import get_overview_from_db

    db = TournamentDatabase(tournament_db_path)
    await db.connect()
    await sync_tournament_to_db(db, 2026, export_json=False)
    overview = await get_overview_from_db(db, target_date=__import__("datetime").date(2026, 7, 4))
    assert overview is not None
    assert overview["meta"]["source"] == "sqlite"
    assert len(overview["today"]["matches"]) >= 1
    await db.close()
