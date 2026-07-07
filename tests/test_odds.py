"""Tests for odds mock generation, DB persistence, and API."""

from __future__ import annotations

import pytest

from app.tools.odds import (
    attach_odds_to_cards,
    generate_mock_odds,
    match_api_event_to_card,
)
from app.tools.tournament_db import TournamentDatabase


def _sample_card(match_id: str = "m1", home_id: str = "brazil", away_id: str = "argentina") -> dict:
    return {
        "match_id": match_id,
        "kickoff_utc": "2026-07-05T19:00:00+00:00",
        "home": {"team_id": home_id, "name_zh": "巴西", "name_en": "Brazil", "score": None},
        "away": {"team_id": away_id, "name_zh": "阿根廷", "name_en": "Argentina", "score": None},
    }


def test_generate_mock_odds_deterministic():
    cards = [_sample_card()]
    rows = generate_mock_odds(cards)
    assert len(rows) == 1
    assert rows[0]["match_id"] == "m1"
    assert rows[0]["bookmaker"] == "mock"
    assert rows[0]["home"] is not None
    again = generate_mock_odds(cards)
    assert again[0]["home"] == rows[0]["home"]


def test_generate_mock_odds_skips_finished():
    card = _sample_card()
    card["home"]["score"] = 2
    card["away"]["score"] = 1
    assert generate_mock_odds([card]) == []


def test_attach_odds_to_cards():
    cards = [_sample_card()]
    odds_map = {
        "m1": {
            "home": 2.1,
            "draw": 3.2,
            "away": 3.5,
            "bookmaker": "mock",
            "updated_at": "2026-07-03 12:00",
        }
    }
    out = attach_odds_to_cards(cards, odds_map)
    assert out[0]["odds"]["home"] == 2.1
    assert out[0]["odds"]["bookmaker"] == "mock"


def test_match_api_event_to_card_by_teams():
    cards = [_sample_card(home_id="brazil", away_id="argentina")]
    event = {
        "home_team": "Brazil",
        "away_team": "Argentina",
        "commence_time": "2026-07-05T19:00:00Z",
    }
    matched = match_api_event_to_card(event, cards)
    assert matched is not None
    assert matched["match_id"] == "m1"


@pytest.mark.asyncio
async def test_upsert_and_fetch_odds(tmp_path):
    db_path = tmp_path / "t.db"
    db = TournamentDatabase(db_path)
    await db.connect()
    try:
        records = generate_mock_odds([_sample_card("wc-001")])
        n = await db.upsert_odds(records)
        assert n == 1
        assert db.has_odds()
        odds_map = await db.fetch_odds_map(["wc-001"])
        assert "wc-001" in odds_map
        assert odds_map["wc-001"]["bookmaker"] == "mock"
    finally:
        await db.close()


@pytest.mark.asyncio
async def test_odds_api_endpoint(api_client):
    res = await api_client.get("/api/odds")
    assert res.status_code == 200
    body = res.json()
    assert "available" in body
    assert "items" in body
