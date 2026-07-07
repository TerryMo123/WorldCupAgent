import asyncio
from pathlib import Path

import pytest

from app.config import Settings
from app.dependencies import AppState
from app.models.request import AgentRequest
from app.orchestrator import handle_request
from app.tools.rag import TeamDocStore
from app.tools.stats import StatsDatabase
from app.tools.tournament_db import TournamentDatabase


@pytest.fixture
async def app_state(fast_settings, monkeypatch):
    monkeypatch.setattr("app.orchestrator.settings", fast_settings)
    fast_settings.request_timeout = 5.0

    db = StatsDatabase(fast_settings.db_path, fast_settings.data_dir)
    await db.connect()
    store = TeamDocStore(fast_settings.docs_dir)
    await store.connect()
    tdb = TournamentDatabase(fast_settings.tournament_db_path)
    await tdb.connect()
    state = AppState(
        stats_db=db,
        vector_store=store,
        tournament_db=tdb,
        llm_semaphore=asyncio.Semaphore(10),
        request_semaphore=asyncio.Semaphore(100),
    )
    yield state
    await store.close()
    await tdb.close()
    await db.close()
    if fast_settings.db_path.exists():
        fast_settings.db_path.unlink()


@pytest.mark.asyncio
async def test_handle_request_success(app_state):
    req = AgentRequest(team_a="巴西", team_b="法国")
    resp = await handle_request(req, app_state)
    assert resp.answer
    assert resp.stats.success is True
    assert resp.rag.success is True
    assert resp.suggestion.success is True
    assert resp.degraded == []
    assert "巴西" in resp.answer or "法国" in resp.answer


@pytest.mark.asyncio
async def test_handle_request_partial_degradation(app_state):
    req = AgentRequest(team_a="巴西", team_b="无效球队")
    resp = await handle_request(req, app_state)
    assert resp.stats.success is False
    assert "stats" in resp.degraded
    assert resp.answer


@pytest.mark.asyncio
async def test_handle_request_timeout(app_state, fast_settings, monkeypatch):
    fast_settings.mock_llm_delay = 5.0
    fast_settings.request_timeout = 0.5
    monkeypatch.setattr("app.orchestrator.settings", fast_settings)
    monkeypatch.setattr("app.tools.suggest.settings", fast_settings)
    req = AgentRequest(team_a="阿根廷", team_b="德国")
    resp = await handle_request(req, app_state)
    assert resp.suggestion.success is False or "suggestion" in resp.degraded
