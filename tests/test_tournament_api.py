import pytest


@pytest.mark.asyncio
async def test_tournament_overview(api_client):
    res = await api_client.get("/api/overview?date=2026-07-03")
    assert res.status_code == 200
    data = res.json()
    assert data["tournament"]["year"] == 2026
    assert len(data["today"]["matches"]) >= 1
    assert len(data["standings"]["groups"]) == 12


@pytest.mark.asyncio
async def test_teams_api(api_client):
    res = await api_client.get("/api/teams")
    assert res.status_code == 200
    teams = res.json()["teams"]
    assert len(teams) >= 40
    assert "team_id" in teams[0]


@pytest.mark.asyncio
async def test_pipeline_status(api_client):
    res = await api_client.get("/api/pipeline/status")
    assert res.status_code == 200
    body = res.json()
    assert body["tournament_year"] == 2026
    assert "populated" in body
