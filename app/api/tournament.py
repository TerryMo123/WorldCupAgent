from datetime import date

from fastapi import APIRouter, Query, Request

from app.config import settings
from app.models.tournament import (
    StandingsResponse,
    TeamSummary,
    TeamsResponse,
    TodayMatchesResponse,
    TournamentInfo,
    TournamentOverview,
)
from app.services import tournament as svc
from app.tools.odds import attach_odds_to_cards
from app.tools.tournament_db import TournamentDatabase
from app.utils.timezone import to_beijing_display

router = APIRouter(prefix="/api", tags=["tournament"])


def _tournament_db(request: Request) -> TournamentDatabase:
    return request.app.state.resources.tournament_db


@router.get("/pipeline/status")
async def pipeline_status(request: Request) -> dict:
    db = _tournament_db(request)
    meta = await db.get_meta()
    populated = db.is_populated()
    counts = {}
    if populated:
        raw = meta.get(f"counts_{settings.tournament_year}", {}).get("value")
        if raw:
            import json

            counts = json.loads(raw)
    raw_sync = meta.get("last_sync_at", {}).get("value")
    return {
        "tournament_year": settings.tournament_year,
        "db_path": str(settings.tournament_db_path),
        "populated": populated,
        "timezone": "Asia/Shanghai",
        "last_sync_at": to_beijing_display(raw_sync),
        "odds_available": db.has_odds(),
        "odds_backend": settings.odds_backend,
        "last_odds_fetch_at": to_beijing_display(meta.get("last_odds_fetch_at", {}).get("value")),
        "counts": counts,
        "meta": meta,
    }


@router.get("/tournament/current", response_model=TournamentInfo)
async def tournament_current(request: Request) -> TournamentInfo:
    db = _tournament_db(request)
    info = await db.fetch_tournament_info() if db.is_populated() else None
    if info:
        return TournamentInfo(**info)
    return TournamentInfo(**svc.get_tournament_info())


@router.get("/matches/today", response_model=TodayMatchesResponse)
async def matches_today(
    request: Request,
    date_str: str | None = Query(default=None, alias="date"),
    tz: str = Query(default="Asia/Shanghai"),
) -> TodayMatchesResponse:
    db = _tournament_db(request)
    target = date.fromisoformat(date_str) if date_str else None
    if db.is_populated():
        from datetime import datetime
        from zoneinfo import ZoneInfo

        tzinfo = ZoneInfo(tz)
        d = target or datetime.now(tzinfo).date()
        data = await db.fetch_matches_on_date(d.isoformat(), tz_name=tz)
        return TodayMatchesResponse(**data)
    data = svc.get_matches_on_date(target, tz_name=tz)
    if db.has_odds():
        match_ids = [m["match_id"] for m in data["matches"]]
        odds_map = await db.fetch_odds_map(match_ids)
        data["matches"] = attach_odds_to_cards(data["matches"], odds_map)
    return TodayMatchesResponse(**data)


@router.get("/standings", response_model=StandingsResponse)
async def standings(request: Request) -> StandingsResponse:
    db = _tournament_db(request)
    if db.is_populated():
        groups = await db.fetch_standings()
        return StandingsResponse(year=settings.tournament_year, groups=groups)
    return StandingsResponse(year=settings.tournament_year, groups=svc.get_standings())


@router.get("/teams", response_model=TeamsResponse)
async def teams(
    request: Request,
    status: str | None = Query(default=None, description="active|qualified|eliminated|champion"),
) -> TeamsResponse:
    db = _tournament_db(request)
    if db.is_populated():
        all_teams = await db.fetch_teams(status=status)
        return TeamsResponse(
            year=settings.tournament_year,
            teams=[TeamSummary(**t) for t in all_teams],
        )
    all_teams = svc.get_all_teams()
    if status:
        all_teams = [t for t in all_teams if t["status"] == status]
    return TeamsResponse(year=settings.tournament_year, teams=[TeamSummary(**t) for t in all_teams])


@router.get("/overview", response_model=TournamentOverview)
async def overview(
    request: Request,
    date_str: str | None = Query(default=None, alias="date"),
) -> TournamentOverview:
    db = _tournament_db(request)
    target = date.fromisoformat(date_str) if date_str else None
    data = await svc.get_overview_from_db(db, target)
    if not data:
        data = svc.get_overview(target)
        if db.has_odds():
            match_ids = [m["match_id"] for m in data["today"]["matches"]]
            odds_map = await db.fetch_odds_map(match_ids)
            data["today"]["matches"] = attach_odds_to_cards(data["today"]["matches"], odds_map)
            data["meta"]["odds_available"] = True
            data["meta"]["odds_backend"] = settings.odds_backend
    return TournamentOverview(**data)


@router.get("/odds")
async def match_odds(
    request: Request,
    match_id: str | None = Query(default=None, description="Single match; omit for all stored odds"),
) -> dict:
    db = _tournament_db(request)
    if not db.has_odds():
        return {"available": False, "count": 0, "items": []}
    if match_id:
        odds_map = await db.fetch_odds_map([match_id])
        item = odds_map.get(match_id)
        return {"available": True, "count": 1 if item else 0, "items": [item] if item else []}
    cards = await db.fetch_all_match_cards()
    odds_map = await db.fetch_odds_map([c["match_id"] for c in cards])
    items = [
        {"match_id": mid, **odds}
        for mid, odds in sorted(odds_map.items())
    ]
    return {"available": True, "count": len(items), "items": items}
