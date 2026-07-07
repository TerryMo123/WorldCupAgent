import pytest

from app.models.request import AgentRequest
from app.models.response import ToolResult
from app.tools.suggest import generate_suggestion


@pytest.fixture
def compare_request():
    return AgentRequest(team_a="巴西", team_b="法国", query="谁更可能赢")


@pytest.fixture
def stats_ok():
    return ToolResult(
        tool_name="stats",
        success=True,
        data={
            "team_a": {
                "name_zh": "巴西",
                "fifa_rank": 3,
                "form": {"played": 6, "win_rate": 0.5, "goals_for": 10, "goals_against": 2},
            },
            "team_b": {
                "name_zh": "法国",
                "fifa_rank": 2,
                "form": {"played": 6, "win_rate": 0.667, "goals_for": 9, "goals_against": 1},
            },
            "head_to_head": {"total_meetings": 0, "team_a_wins": 0, "team_b_wins": 0, "draws": 0, "meetings": []},
            "model_hint": {"team_a_win_prob": 0.45, "team_b_win_prob": 0.55, "note": "测试"},
        },
        latency_ms=10,
    )


@pytest.fixture
def rag_ok():
    return ToolResult(
        tool_name="rag",
        success=True,
        data={
            "chunks": [
                {
                    "title": "巴西",
                    "content": "## 优势\n- 进攻强\n- 经验足\n## 劣势\n- 防守偶有空档",
                }
            ]
        },
        latency_ms=10,
    )


@pytest.mark.asyncio
async def test_generate_suggestion_success(compare_request, stats_ok, rag_ok, llm_semaphore, fast_settings):
    result = await generate_suggestion(compare_request, stats_ok, rag_ok, llm_semaphore)
    assert result.success is True
    assert "巴西" in result.data["answer"]
    assert "法国" in result.data["answer"]
    assert "免责声明" in result.data["answer"]


@pytest.mark.asyncio
async def test_generate_suggestion_degraded(compare_request, llm_semaphore, fast_settings):
    result = await generate_suggestion(compare_request, None, None, llm_semaphore)
    assert result.success is True
    assert "数据摘要" in result.data["answer"]


@pytest.mark.asyncio
async def test_generate_suggestion_llm_failure(
    compare_request, stats_ok, rag_ok, llm_semaphore, fast_settings, monkeypatch
):
    fast_settings.mock_failure_rate = 1.0
    monkeypatch.setattr("app.tools.suggest.settings", fast_settings)
    result = await generate_suggestion(compare_request, stats_ok, rag_ok, llm_semaphore)
    assert result.success is False
    assert "抱歉" in result.data["answer"]
