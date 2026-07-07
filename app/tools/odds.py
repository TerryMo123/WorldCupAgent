"""Odds fetching (The Odds API) and mock provider for development."""

from __future__ import annotations

import hashlib
import logging
from datetime import datetime, timezone
from typing import Any

import httpx

from app.config import settings
from app.tools.teams import normalize_team_id
from app.utils.timezone import parse_iso_datetime, to_beijing_display, utc_now_iso

logger = logging.getLogger(__name__)


def _pair_key(home_id: str | None, away_id: str | None) -> str | None:
    if not home_id or not away_id:
        return None
    a, b = sorted([home_id, away_id])
    return f"{a}|{b}"


def _mock_odds_for_match(match_id: str, home_id: str | None, away_id: str | None) -> dict[str, Any]:
    """Deterministic demo odds for scheduled matches (no API key required)."""
    seed = hashlib.md5(f"{match_id}:{home_id}:{away_id}".encode()).hexdigest()
    base = 1.4 + (int(seed[:4], 16) % 200) / 100.0
    draw = round(2.8 + (int(seed[4:8], 16) % 150) / 100.0, 2)
    away = round(base + 0.3 + (int(seed[8:12], 16) % 100) / 100.0, 2)
    home = round(base, 2)
    fetched = utc_now_iso()
    return {
        "bookmaker": "mock",
        "home": home,
        "draw": draw,
        "away": away,
        "fetched_at": fetched,
        "updated_at": to_beijing_display(fetched),
    }


def generate_mock_odds(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Generate mock 1X2 odds for matches without final scores."""
    rows: list[dict[str, Any]] = []
    for card in cards:
        if card.get("home", {}).get("score") is not None:
            continue
        home_id = card.get("home", {}).get("team_id")
        away_id = card.get("away", {}).get("team_id")
        if not home_id or not away_id:
            continue
        odds = _mock_odds_for_match(card["match_id"], home_id, away_id)
        rows.append({"match_id": card["match_id"], **odds})
    return rows


def _parse_h2h_outcomes(
    home_name: str,
    away_name: str,
    outcomes: list[dict[str, Any]],
) -> tuple[float | None, float | None, float | None]:
    home_odds = draw_odds = away_odds = None
    home_id = normalize_team_id(home_name)
    away_id = normalize_team_id(away_name)
    for o in outcomes:
        name = o.get("name", "")
        price = o.get("price")
        if price is None:
            continue
        if name.lower() == "draw":
            draw_odds = float(price)
            continue
        oid = normalize_team_id(name)
        if oid and home_id and oid == home_id:
            home_odds = float(price)
        elif oid and away_id and oid == away_id:
            away_odds = float(price)
        elif name == home_name:
            home_odds = float(price)
        elif name == away_name:
            away_odds = float(price)
    return home_odds, draw_odds, away_odds


def _extract_best_h2h(event: dict[str, Any]) -> tuple[str, float | None, float | None, float | None]:
    home = event.get("home_team", "")
    away = event.get("away_team", "")
    bookmakers = event.get("bookmakers") or []
    if not bookmakers:
        return "", None, None, None
    bk = bookmakers[0]
    bookmaker = bk.get("title") or bk.get("key") or "unknown"
    for market in bk.get("markets") or []:
        if market.get("key") == "h2h":
            return bookmaker, *_parse_h2h_outcomes(home, away, market.get("outcomes") or [])
    return bookmaker, None, None, None


def match_api_event_to_card(event: dict[str, Any], cards: list[dict[str, Any]]) -> dict[str, Any] | None:
    """Align an Odds API event to our match card by team pair (+ optional kickoff)."""
    home_name = event.get("home_team", "")
    away_name = event.get("away_team", "")
    e_home = normalize_team_id(home_name)
    e_away = normalize_team_id(away_name)
    if not e_home or not e_away:
        return None
    pair = _pair_key(e_home, e_away)
    commence = parse_iso_datetime(event.get("commence_time", ""))

    candidates = []
    for card in cards:
        h = card.get("home", {}).get("team_id")
        a = card.get("away", {}).get("team_id")
        if _pair_key(h, a) != pair:
            continue
        if commence and card.get("kickoff_utc"):
            kick = parse_iso_datetime(card["kickoff_utc"])
            if kick and abs((kick - commence).total_seconds()) > 48 * 3600:
                continue
        candidates.append(card)
    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        return candidates[0]
    return None


async def fetch_odds_from_api(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fetch h2h odds from The Odds API and align to match_id."""
    if not settings.odds_api_key:
        raise RuntimeError("ODDS_API_KEY is not configured")

    url = (
        f"{settings.odds_api_base_url.rstrip('/')}/sports/{settings.odds_sport_key}/odds"
    )
    params = {
        "apiKey": settings.odds_api_key,
        "regions": settings.odds_regions,
        "markets": settings.odds_markets,
        "oddsFormat": "decimal",
    }
    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.get(url, params=params)
        resp.raise_for_status()
        events = resp.json()

    fetched = utc_now_iso()
    rows: list[dict[str, Any]] = []
    for event in events:
        card = match_api_event_to_card(event, cards)
        if not card:
            continue
        bookmaker, home, draw, away = _extract_best_h2h(event)
        if home is None and away is None:
            continue
        rows.append(
            {
                "match_id": card["match_id"],
                "bookmaker": bookmaker,
                "home": home,
                "draw": draw,
                "away": away,
                "fetched_at": fetched,
                "updated_at": to_beijing_display(fetched),
            }
        )
    return rows


async def fetch_odds_for_cards(cards: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Fetch odds using configured backend (mock or The Odds API)."""
    scheduled = [c for c in cards if c.get("home", {}).get("score") is None]
    if not scheduled:
        return []
    if settings.odds_backend == "the_odds_api":
        try:
            return await fetch_odds_from_api(scheduled)
        except Exception as exc:
            logger.warning("odds_api_failed_fallback_mock", error=str(exc))
    return generate_mock_odds(scheduled)


def attach_odds_to_cards(cards: list[dict[str, Any]], odds_map: dict[str, dict[str, Any]]) -> list[dict[str, Any]]:
    out: list[dict[str, Any]] = []
    for card in cards:
        c = dict(card)
        odds = odds_map.get(card["match_id"])
        if odds:
            c["odds"] = {
                "home": odds.get("home"),
                "draw": odds.get("draw"),
                "away": odds.get("away"),
                "bookmaker": odds.get("bookmaker"),
                "updated_at": odds.get("updated_at"),
            }
        else:
            c["odds"] = None
        out.append(c)
    return out
