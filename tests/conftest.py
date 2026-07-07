import asyncio
from pathlib import Path

import pytest
from httpx import ASGITransport, AsyncClient

from app.config import Settings
from app.dependencies import lifespan
from app.main import app
from app.tools.rag import TeamDocStore, rag_search
from app.tools.stats import StatsDatabase, fetch_stats


@pytest.fixture
async def api_client():
    async with lifespan(app):
        transport = ASGITransport(app=app)
        async with AsyncClient(transport=transport, base_url="http://test") as client:
            yield client


@pytest.fixture
def fast_settings(monkeypatch):
    s = Settings(
        data_dir=Path("data"),
        docs_dir=Path("docs/teams"),
        db_path=Path("data/test_worldcup.db"),
        tournament_db_path=Path("data/test_tournament.db"),
        rag_backend="mock",
        llm_backend="mock",
        mock_stats_delay=0.01,
        mock_rag_delay=0.01,
        mock_llm_delay=0.01,
        mock_failure_rate=0.0,
    )
    monkeypatch.setattr("app.tools.rag.settings", s)
    monkeypatch.setattr("app.tools.stats.settings", s)
    monkeypatch.setattr("app.tools.suggest.settings", s)
    return s


@pytest.fixture
async def stats_db(fast_settings):
    db = StatsDatabase(fast_settings.db_path, fast_settings.data_dir)
    await db.connect()
    yield db
    await db.close()
    if fast_settings.db_path.exists():
        fast_settings.db_path.unlink()
    if fast_settings.tournament_db_path.exists():
        fast_settings.tournament_db_path.unlink()


@pytest.fixture
async def vector_store(fast_settings):
    store = TeamDocStore(fast_settings.docs_dir)
    await store.connect()
    yield store
    await store.close()


@pytest.fixture
def llm_semaphore():
    return asyncio.Semaphore(10)
