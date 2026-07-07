import asyncio
import json
import random
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any

import structlog

from app.config import settings
from app.models.request import AgentRequest
from app.models.response import ToolResult

logger = structlog.get_logger()

_SKILL_CACHE: str | None = None


def load_skill(path: Path | None = None) -> str:
    global _SKILL_CACHE
    if _SKILL_CACHE is not None:
        return _SKILL_CACHE
    skill_path = path or settings.skill_path
    if skill_path.exists():
        _SKILL_CACHE = skill_path.read_text(encoding="utf-8")
    else:
        _SKILL_CACHE = ""
    return _SKILL_CACHE


def _team_label(team: dict[str, Any]) -> str:
    return team.get("name_zh") or team.get("name_en") or team.get("team_id", "?")


def _build_user_prompt(
    req: AgentRequest,
    stats_data: dict[str, Any] | None,
    rag_data: dict[str, Any] | None,
) -> str:
    title = req.query or f"{req.team_a} vs {req.team_b} 优劣对比"
    parts = [f"请撰写世界杯球队对比报告，主题：{title}\n"]

    if stats_data:
        parts.append("## 结构化统计数据（JSON）\n")
        parts.append(json.dumps(stats_data, ensure_ascii=False, indent=2))
        parts.append("\n")
    else:
        parts.append("## 结构化统计数据\n暂无\n")

    if rag_data and rag_data.get("chunks"):
        parts.append("\n## RAG 检索文档片段\n")
        for i, chunk in enumerate(rag_data["chunks"][:4], 1):
            parts.append(f"### 片段 {i} — {chunk.get('title', '')} / {chunk.get('section', '')}\n")
            parts.append(chunk.get("content", ""))
            parts.append("\n\n")
    else:
        parts.append("\n## RAG 检索文档片段\n暂无\n")

    parts.append(
        "\n请用中文输出 Markdown 报告，包含：数据摘要、优势对比、劣势对比、综合判断。"
        "末尾加免责声明：以上分析仅供参考，非投注建议。"
    )
    return "".join(parts)


async def _generate_answer_mock(
    req: AgentRequest,
    stats_data: dict[str, Any] | None,
    rag_data: dict[str, Any] | None,
) -> str:
    """Mock LLM: structured World Cup comparison report."""
    await asyncio.sleep(settings.mock_llm_delay)
    if settings.mock_failure_rate > 0 and random.random() < settings.mock_failure_rate:
        raise RuntimeError("LLM API rate limited")

    skill = load_skill()
    parts: list[str] = []

    title = req.query or f"{req.team_a} vs {req.team_b} 优劣对比"
    parts.append(f"## {title}\n")

    if stats_data:
        a = stats_data["team_a"]
        b = stats_data["team_b"]
        h2h = stats_data["head_to_head"]
        hint = stats_data.get("model_hint", {})
        parts.append("### 数据摘要\n")
        parts.append(
            f"- **{_team_label(a)}**：FIFA 第{a.get('fifa_rank', '—')}，"
            f"近{a['form']['played']}场胜率 {a['form']['win_rate']*100:.1f}%，"
            f"进{a['form']['goals_for']}失{a['form']['goals_against']}\n"
        )
        parts.append(
            f"- **{_team_label(b)}**：FIFA 第{b.get('fifa_rank', '—')}，"
            f"近{b['form']['played']}场胜率 {b['form']['win_rate']*100:.1f}%，"
            f"进{b['form']['goals_for']}失{b['form']['goals_against']}\n"
        )
        parts.append(
            f"- **历史交锋**：共{h2h['total_meetings']}场，"
            f"{_team_label(a)} {h2h['team_a_wins']}胜，"
            f"{_team_label(b)} {h2h['team_b_wins']}胜，"
            f"平局 {h2h['draws']}\n"
        )
        if h2h.get("meetings"):
            top = h2h["meetings"][0]
            parts.append(f"- 最近交锋：{top['date']} {top['score']}（{top['competition']}）\n")
        if hint:
            parts.append(
                f"- **模型参考胜率**：{_team_label(a)} {hint.get('team_a_win_prob', 0)*100:.1f}% vs "
                f"{_team_label(b)} {hint.get('team_b_win_prob', 0)*100:.1f}%（{hint.get('note', '')}）\n"
            )
    else:
        parts.append("### 数据摘要\n暂无结构化统计数据。\n")

    def _extract_section(content: str, heading: str) -> list[str]:
        lines = content.splitlines()
        items: list[str] = []
        in_section = False
        for line in lines:
            if line.strip().startswith("## "):
                in_section = heading in line
                continue
            if in_section and line.strip().startswith("- "):
                items.append(line.strip()[2:])
        return items

    parts.append("\n### 优势对比\n")
    if rag_data and rag_data.get("chunks"):
        for chunk in rag_data["chunks"][:2]:
            title = chunk.get("title", chunk.get("team_id", ""))
            pros = _extract_section(chunk.get("content", ""), "优势")
            parts.append(f"**{title}**：\n")
            for p in pros[:3]:
                parts.append(f"- {p}\n")
    else:
        parts.append("暂无文档数据。\n")

    parts.append("\n### 劣势对比\n")
    if rag_data and rag_data.get("chunks"):
        for chunk in rag_data["chunks"][:2]:
            title = chunk.get("title", chunk.get("team_id", ""))
            cons = _extract_section(chunk.get("content", ""), "劣势")
            parts.append(f"**{title}**：\n")
            for c in cons[:3]:
                parts.append(f"- {c}\n")

    parts.append("\n### 综合判断\n")
    if stats_data and stats_data.get("model_hint"):
        ha = stats_data["model_hint"].get("team_a_win_prob", 0.5)
        name_a = _team_label(stats_data["team_a"])
        name_b = _team_label(stats_data["team_b"])
        if ha > 0.55:
            parts.append(f"数据倾向 **{name_a}** 略占上风，但大赛存在不确定性。\n")
        elif ha < 0.45:
            parts.append(f"数据倾向 **{name_b}** 略占上风，但大赛存在不确定性。\n")
        else:
            parts.append(f"**{name_a}** 与 **{name_b}** 实力接近，临场发挥与伤病是关键变量。\n")
    else:
        parts.append("数据不足，无法给出可靠倾向。\n")

    parts.append("\n> 免责声明：以上分析仅供参考，非投注建议。\n")
    if skill and settings.debug:
        parts.append(f"\n<!-- skill loaded: {len(skill)} chars -->")

    return "".join(parts)


async def _generate_answer_qwen(
    req: AgentRequest,
    stats_data: dict[str, Any] | None,
    rag_data: dict[str, Any] | None,
) -> str:
    from app.llm.client import get_async_openai_client

    skill = load_skill()
    system = (
        "你是世界杯足球分析助手，根据统计数据与战术文档撰写客观、专业的中文对比报告。"
        "不要编造数据中不存在的事实。"
    )
    if skill:
        system += f"\n\n## 分析指南\n{skill}"

    client = get_async_openai_client()
    user_prompt = _build_user_prompt(req, stats_data, rag_data)

    response = await client.chat.completions.create(
        model=settings.llm_model,
        messages=[
            {"role": "system", "content": system},
            {"role": "user", "content": user_prompt},
        ],
        max_tokens=settings.llm_max_tokens,
        temperature=settings.llm_temperature,
    )
    content = response.choices[0].message.content or ""
    if not content.strip():
        raise RuntimeError("Empty LLM response")
    return content


async def _generate_answer(
    req: AgentRequest,
    stats_data: dict[str, Any] | None,
    rag_data: dict[str, Any] | None,
) -> str:
    if settings.llm_backend == "qwen":
        return await _generate_answer_qwen(req, stats_data, rag_data)
    return await _generate_answer_mock(req, stats_data, rag_data)


async def generate_suggestion(
    req: AgentRequest,
    stats_result: ToolResult | None,
    rag_result: ToolResult | None,
    llm_semaphore: asyncio.Semaphore,
) -> ToolResult:
    """Generate comparison report via LLM, guarded by semaphore."""
    start = time.perf_counter()
    tool_name = "suggestion"
    stats_data = stats_result.data if stats_result and stats_result.success else None
    rag_data = rag_result.data if rag_result and rag_result.success else None

    try:
        async with llm_semaphore:
            answer = await _generate_answer(req, stats_data, rag_data)
        latency_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "tool_completed",
            tool=tool_name,
            latency_ms=round(latency_ms, 2),
            backend=settings.llm_backend,
            success=True,
        )
        return ToolResult(
            tool_name=tool_name,
            success=True,
            data={"answer": answer},
            latency_ms=latency_ms,
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - start) * 1000
        logger.warning("tool_failed", tool=tool_name, latency_ms=round(latency_ms, 2), error=str(exc))
        fallback = (
            f"抱歉，暂时无法生成 {req.team_a} vs {req.team_b} 的完整对比报告，请稍后重试。"
        )
        return ToolResult(
            tool_name=tool_name,
            success=False,
            data={"answer": fallback},
            error=str(exc),
            latency_ms=latency_ms,
        )


async def stream_suggestion_tokens(
    req: AgentRequest,
    stats_result: ToolResult | None,
    rag_result: ToolResult | None,
    llm_semaphore: asyncio.Semaphore,
) -> AsyncIterator[str]:
    """Stream LLM tokens for SSE endpoint."""
    stats_data = stats_result.data if stats_result and stats_result.success else None
    rag_data = rag_result.data if rag_result and rag_result.success else None

    async with llm_semaphore:
        if settings.llm_backend == "qwen":
            from app.llm.client import get_async_openai_client

            skill = load_skill()
            system = (
                "你是世界杯足球分析助手，根据统计数据与战术文档撰写客观、专业的中文对比报告。"
            )
            if skill:
                system += f"\n\n## 分析指南\n{skill}"
            client = get_async_openai_client()
            user_prompt = _build_user_prompt(req, stats_data, rag_data)
            stream = await client.chat.completions.create(
                model=settings.llm_model,
                messages=[
                    {"role": "system", "content": system},
                    {"role": "user", "content": user_prompt},
                ],
                max_tokens=settings.llm_max_tokens,
                temperature=settings.llm_temperature,
                stream=True,
            )
            async for chunk in stream:
                delta = chunk.choices[0].delta.content
                if delta:
                    yield delta
        else:
            full = await _generate_answer_mock(req, stats_data, rag_data)
            chunk_size = 12
            for i in range(0, len(full), chunk_size):
                await asyncio.sleep(0.03)
                yield full[i : i + chunk_size]
