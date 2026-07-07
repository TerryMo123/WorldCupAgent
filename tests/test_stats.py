import pytest

from app.tools.stats import fetch_stats


@pytest.mark.asyncio
async def test_fetch_stats_success(stats_db, fast_settings):
    result = await fetch_stats("巴西", "法国", stats_db)
    assert result.success is True
    assert result.data is not None
    assert result.data["team_a"]["name_zh"] == "巴西" or result.data["team_a"]["name_en"] == "Brazil"
    assert result.data["team_b"]["name_zh"] == "法国" or result.data["team_b"]["name_en"] == "France"
    assert "head_to_head" in result.data
    assert "model_hint" in result.data


@pytest.mark.asyncio
async def test_fetch_stats_unknown_team(stats_db, fast_settings):
    result = await fetch_stats("巴西", "不存在的队", stats_db)
    assert result.success is False
    assert result.error is not None
