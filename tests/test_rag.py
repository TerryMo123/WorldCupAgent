import pytest

from app.tools.rag import rag_search


@pytest.mark.asyncio
async def test_rag_search_team_docs(vector_store, fast_settings):
    result = await rag_search("战术 优势", vector_store, team_ids=["brazil", "france"])
    assert result.success is True
    assert result.data is not None
    assert len(result.data["chunks"]) >= 1


@pytest.mark.asyncio
async def test_rag_search_failure(vector_store, fast_settings, monkeypatch):
    fast_settings.mock_failure_rate = 1.0
    monkeypatch.setattr("app.tools.rag.settings", fast_settings)
    result = await rag_search("测试", vector_store, team_ids=["brazil"])
    assert result.success is False
    assert result.error is not None
