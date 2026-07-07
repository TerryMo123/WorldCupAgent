import asyncio
import time
from typing import Any

import structlog

from app.config import settings
from app.dependencies import AppState
from app.models.request import AgentRequest
from app.models.response import AgentResponse, ToolResult
from app.tools.rag import rag_search
from app.tools.stats import fetch_stats
from app.tools.suggest import generate_suggestion
from app.tools.teams import normalize_pair

logger = structlog.get_logger()


def _rag_query(req: AgentRequest) -> str:
    if req.query:
        return req.query
    return f"{req.team_a} {req.team_b} 战术 优势 劣势 对比"


def _team_ids(req: AgentRequest) -> list[str]:
    a, b = normalize_pair(req.team_a, req.team_b)
    return [t for t in (a, b) if t]


def _fallback_answer(req: AgentRequest, degraded: list[str]) -> str:
    label = req.query or f"{req.team_a} vs {req.team_b}"
    if degraded:
        return (
            f"部分服务暂时不可用（{', '.join(degraded)}），"
            f"关于「{label}」的对比报告生成受限，请稍后重试。"
        )
    return f"关于「{label}」：请稍后重试。"


async def _run_suggestion_after_deps(
    req: AgentRequest,
    stats_coro: asyncio.Task[ToolResult],
    rag_coro: asyncio.Task[ToolResult],
    llm_semaphore: asyncio.Semaphore,
) -> ToolResult:
    stats_result, rag_result = await asyncio.gather(stats_coro, rag_coro, return_exceptions=True)
    if isinstance(stats_result, BaseException):
        stats_result = ToolResult(tool_name="stats", success=False, error=str(stats_result), latency_ms=0)
    if isinstance(rag_result, BaseException):
        rag_result = ToolResult(tool_name="rag", success=False, error=str(rag_result), latency_ms=0)
    return await generate_suggestion(req, stats_result, rag_result, llm_semaphore)


async def handle_request(req: AgentRequest, state: AppState) -> AgentResponse:
    """Orchestrate stats + RAG + LLM concurrently with timeout and graceful degradation."""
    start = time.perf_counter()
    log = logger.bind(user_id=req.user_id, team_a=req.team_a, team_b=req.team_b)

    query = _rag_query(req)
    team_ids = _team_ids(req)

    stats_task = asyncio.create_task(fetch_stats(req.team_a, req.team_b, state.stats_db))
    rag_task = asyncio.create_task(rag_search(query, state.vector_store, team_ids=team_ids))
    suggestion_task = asyncio.create_task(
        _run_suggestion_after_deps(req, stats_task, rag_task, state.llm_semaphore)
    )

    tasks = [stats_task, rag_task, suggestion_task]
    try:
        results = await asyncio.wait_for(
            asyncio.gather(*tasks, return_exceptions=True),
            timeout=settings.request_timeout,
        )
    except asyncio.TimeoutError:
        log.warning("request_timeout", timeout_s=settings.request_timeout)
        for t in tasks:
            if not t.done():
                t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        results = []
        for t in tasks:
            if t.cancelled() or t.exception():
                results.append(asyncio.TimeoutError("request timeout"))
            else:
                results.append(t.result())

    stats_result, rag_result, suggestion_result = _normalize_results(results)

    degraded: list[str] = []
    for name, result in [
        ("stats", stats_result),
        ("rag", rag_result),
        ("suggestion", suggestion_result),
    ]:
        if not result.success:
            degraded.append(name)

    if suggestion_result.success and suggestion_result.data:
        answer = suggestion_result.data.get("answer", "")
    elif suggestion_result.data and suggestion_result.data.get("answer"):
        answer = suggestion_result.data["answer"]
    else:
        answer = _fallback_answer(req, degraded)

    total_latency_ms = (time.perf_counter() - start) * 1000
    log.info(
        "request_completed",
        total_latency_ms=round(total_latency_ms, 2),
        degraded=degraded,
        stats_ms=round(stats_result.latency_ms, 2),
        rag_ms=round(rag_result.latency_ms, 2),
        suggestion_ms=round(suggestion_result.latency_ms, 2),
    )

    return AgentResponse(
        answer=answer,
        stats=stats_result,
        rag=rag_result,
        suggestion=suggestion_result,
        degraded=degraded,
        total_latency_ms=total_latency_ms,
    )


def _normalize_results(results: list[Any]) -> tuple[ToolResult, ToolResult, ToolResult]:
    names = ["stats", "rag", "suggestion"]
    normalized: list[ToolResult] = []
    for name, item in zip(names, results, strict=True):
        if isinstance(item, ToolResult):
            normalized.append(item)
        elif isinstance(item, BaseException):
            normalized.append(
                ToolResult(tool_name=name, success=False, error=str(item), latency_ms=0)
            )
        else:
            normalized.append(
                ToolResult(tool_name=name, success=False, error="unknown result", latency_ms=0)
            )
    return normalized[0], normalized[1], normalized[2]
