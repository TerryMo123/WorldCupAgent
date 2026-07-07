from typing import Any, Literal

from pydantic import BaseModel, Field

TeamStatus = Literal["active", "qualified", "eliminated", "champion"]


class TeamBrief(BaseModel):
    team_id: str | None
    name_zh: str
    name_en: str
    score: int | None = None


class OddsBrief(BaseModel):
    home: float | None = None
    draw: float | None = None
    away: float | None = None
    bookmaker: str | None = None
    updated_at: str | None = None


class MatchCard(BaseModel):
    match_id: str
    date: str
    kickoff_display: str
    kickoff_utc: str | None = None
    home: TeamBrief
    away: TeamBrief
    status: Literal["scheduled", "live", "finished"]
    stage: str
    group: str | None = None
    venue: str | None = None
    odds: OddsBrief | None = None


class StandingRow(BaseModel):
    rank: int
    team_id: str
    name_zh: str
    name_en: str
    played: int
    won: int
    drawn: int
    lost: int
    goals_for: int
    goals_against: int
    goal_diff: int
    points: int
    status: TeamStatus


class GroupStandings(BaseModel):
    group: str
    rows: list[StandingRow]


class TeamSummary(BaseModel):
    team_id: str
    name_zh: str
    name_en: str
    group: str | None = None
    status: TeamStatus
    played: int = 0
    won: int = 0
    drawn: int = 0
    lost: int = 0
    goals_for: int = 0
    goals_against: int = 0
    points: int = 0
    win_rate: float | None = None


class TournamentInfo(BaseModel):
    year: int
    name: str
    phase: str
    total_teams: int
    data_updated_at: str | None = None


class TodayMatchesResponse(BaseModel):
    date: str
    timezone: str
    matches: list[MatchCard]


class StandingsResponse(BaseModel):
    year: int
    groups: list[GroupStandings]


class TeamsResponse(BaseModel):
    year: int
    teams: list[TeamSummary]


class TournamentOverview(BaseModel):
    tournament: TournamentInfo
    today: TodayMatchesResponse
    standings: StandingsResponse
    meta: dict[str, Any] = Field(default_factory=dict)
