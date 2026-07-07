import asyncio
import json
import uuid
from collections.abc import AsyncIterator

import structlog
from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from app.api.tournament import router as tournament_router
from app.config import settings
from app.dependencies import lifespan
from app.logging_setup import configure_logging
from app.models.request import AgentRequest
from app.models.response import AgentResponse, ToolResult
from app.orchestrator import _rag_query, _team_ids, handle_request
from app.tools.rag import rag_search
from app.tools.stats import fetch_stats
from app.tools.suggest import stream_suggestion_tokens

configure_logging(debug=settings.debug)
logger = structlog.get_logger()

app = FastAPI(title=settings.app_name, lifespan=lifespan)

_origins = [o.strip() for o in settings.cors_origins.split(",") if o.strip()]
app.add_middleware(
    CORSMiddleware,
    allow_origins=_origins or ["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)
app.include_router(tournament_router)


@app.middleware("http")
async def trace_middleware(request: Request, call_next):
    trace_id = request.headers.get("X-Trace-Id", uuid.uuid4().hex)
    structlog.contextvars.clear_contextvars()
    structlog.contextvars.bind_contextvars(
        trace_id=trace_id,
        path=request.url.path,
        method=request.method,
    )
    response = await call_next(request)
    response.headers["X-Trace-Id"] = trace_id
    return response


@app.get("/health")
async def health() -> dict[str, str]:
    return {"status": "ok", "app": settings.app_name}


@app.post("/agent", response_model=AgentResponse)
async def agent_endpoint(request: Request, req: AgentRequest) -> AgentResponse:
    """World Cup team comparison: stats + RAG + LLM report."""
    state = request.app.state.resources
    sem = state.request_semaphore

    try:
        await asyncio.wait_for(sem.acquire(), timeout=settings.queue_put_timeout)
    except asyncio.TimeoutError:
        logger.warning("request_capacity_full", max_concurrent=settings.queue_maxsize)
        raise HTTPException(status_code=503, detail="系统繁忙，请稍后重试") from None
    try:
        return await handle_request(req, state)
    finally:
        sem.release()


@app.post("/agent/stream")
async def agent_stream_endpoint(request: Request, req: AgentRequest) -> StreamingResponse:
    """SSE: emit stats/rag results then stream report tokens."""

    async def event_stream() -> AsyncIterator[str]:
        state = request.app.state.resources
        query = _rag_query(req)
        team_ids = _team_ids(req)

        stats_task = asyncio.create_task(fetch_stats(req.team_a, req.team_b, state.stats_db))
        rag_task = asyncio.create_task(rag_search(query, state.vector_store, team_ids=team_ids))

        stats_result, rag_result = await asyncio.gather(stats_task, rag_task, return_exceptions=True)

        for event_type, payload in [("stats", stats_result), ("rag", rag_result)]:
            if isinstance(payload, BaseException):
                data = {"success": False, "error": str(payload)}
            elif isinstance(payload, ToolResult):
                data = payload.model_dump()
            else:
                data = {"success": False, "error": "unknown"}
            yield f"event: {event_type}\ndata: {json.dumps(data, ensure_ascii=False)}\n\n"

        stats_tr = stats_result if isinstance(stats_result, ToolResult) else None
        rag_tr = rag_result if isinstance(rag_result, ToolResult) else None

        async for token in stream_suggestion_tokens(req, stats_tr, rag_tr, state.llm_semaphore):
            if await request.is_disconnected():
                break
            yield f"event: token\ndata: {json.dumps({'text': token}, ensure_ascii=False)}\n\n"

        yield f"event: done\ndata: {json.dumps({'status': 'complete'})}\n\n"

    return StreamingResponse(
        event_stream(),
        media_type="text/event-stream",
        headers={"Cache-Control": "no-cache", "X-Accel-Buffering": "no"},
    )
