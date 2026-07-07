import asyncio
from contextlib import asynccontextmanager
from dataclasses import dataclass
from typing import Any

from app.config import settings
from app.tools.rag import VectorStore, create_vector_store
from app.tools.stats import StatsDatabase
from app.tools.tournament_db import TournamentDatabase


@dataclass
class AppState:
    stats_db: StatsDatabase
    vector_store: VectorStore
    tournament_db: TournamentDatabase
    llm_semaphore: asyncio.Semaphore
    request_semaphore: asyncio.Semaphore


@asynccontextmanager
async def lifespan(app: Any):
    stats_db = StatsDatabase(settings.db_path, settings.data_dir)
    await stats_db.connect()

    tournament_db = TournamentDatabase(settings.tournament_db_path)
    await tournament_db.connect()

    vector_store = create_vector_store()
    await vector_store.connect()

    llm_semaphore = asyncio.Semaphore(settings.llm_max_concurrency)
    request_semaphore = asyncio.Semaphore(settings.queue_maxsize)

    app.state.resources = AppState(
        stats_db=stats_db,
        vector_store=vector_store,
        tournament_db=tournament_db,
        llm_semaphore=llm_semaphore,
        request_semaphore=request_semaphore,
    )

    yield

    await vector_store.close()
    await tournament_db.close()
    await stats_db.close()
