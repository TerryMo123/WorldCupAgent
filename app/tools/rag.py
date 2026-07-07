import asyncio
import re
import time
from abc import ABC, abstractmethod
from pathlib import Path
from typing import Any

import structlog

from app.config import settings
from app.models.response import ToolResult

logger = structlog.get_logger()


class VectorStore(ABC):
    @abstractmethod
    async def connect(self) -> None: ...

    @abstractmethod
    async def close(self) -> None: ...

    @abstractmethod
    async def search(
        self,
        query: str,
        top_k: int = 3,
        team_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]: ...


class TeamDocStore(VectorStore):
    """In-memory keyword search over team markdown (mock / tests)."""

    def __init__(self, docs_dir: Path | None = None) -> None:
        self.docs_dir = docs_dir or settings.docs_dir
        self._docs: list[dict[str, Any]] = []

    async def connect(self) -> None:
        self._docs.clear()
        if not self.docs_dir.exists():
            logger.warning("docs_dir_missing", path=str(self.docs_dir))
            return
        for path in sorted(self.docs_dir.glob("*.md")):
            text = path.read_text(encoding="utf-8")
            title = ""
            for line in text.splitlines():
                if line.startswith("# "):
                    title = line[2:].strip()
                    break
            self._docs.append(
                {
                    "team_id": path.stem,
                    "title": title or path.stem,
                    "content": text,
                    "source": str(path),
                }
            )
        logger.info("rag_docs_loaded", count=len(self._docs), backend="mock")

    async def close(self) -> None:
        self._docs.clear()

    def _score(self, query: str, doc: dict[str, Any]) -> float:
        q_tokens = set(re.findall(r"[\w\u4e00-\u9fff]+", query.lower()))
        if not q_tokens:
            return 0.0
        text = f"{doc['title']} {doc['content']}".lower()
        hits = sum(1 for t in q_tokens if t in text)
        return hits / len(q_tokens)

    async def search(
        self,
        query: str,
        top_k: int = 3,
        team_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        candidates = self._docs
        if team_ids:
            id_set = set(team_ids)
            candidates = [d for d in candidates if d["team_id"] in id_set]
        scored = [(self._score(query, d), d) for d in candidates]
        scored.sort(key=lambda x: x[0], reverse=True)
        results = []
        for score, doc in scored[:top_k]:
            if score <= 0:
                continue
            results.append({**doc, "score": round(score, 4)})
        return results


class ChromaVectorStore(VectorStore):
    """Semantic search via Chroma + DashScope embeddings."""

    def __init__(
        self,
        persist_dir: Path | None = None,
        collection_name: str | None = None,
    ) -> None:
        self.persist_dir = persist_dir or settings.chroma_persist_dir
        self.collection_name = collection_name or settings.chroma_collection
        self._client: Any = None
        self._collection: Any = None

    async def connect(self) -> None:
        import chromadb

        self.persist_dir.mkdir(parents=True, exist_ok=True)
        self._client = chromadb.PersistentClient(path=str(self.persist_dir))
        self._collection = self._client.get_or_create_collection(
            name=self.collection_name,
            metadata={"hnsw:space": "cosine"},
        )
        count = self._collection.count()
        logger.info(
            "chroma_connected",
            path=str(self.persist_dir),
            collection=self.collection_name,
            count=count,
        )
        if count == 0:
            logger.warning(
                "chroma_empty",
                hint="Run: python scripts/ingest_embeddings.py",
            )

    async def close(self) -> None:
        self._collection = None
        self._client = None

    async def search(
        self,
        query: str,
        top_k: int = 3,
        team_ids: list[str] | None = None,
    ) -> list[dict[str, Any]]:
        if self._collection is None or self._collection.count() == 0:
            return []

        from app.llm.client import embed_text_async

        query_vec = await embed_text_async(query)
        where: dict[str, Any] | None = None
        if team_ids:
            where = {"team_id": {"$in": team_ids}}

        result = self._collection.query(
            query_embeddings=[query_vec],
            n_results=top_k,
            where=where,
            include=["documents", "metadatas", "distances"],
        )

        chunks: list[dict[str, Any]] = []
        if not result["ids"] or not result["ids"][0]:
            return chunks

        for i, doc_id in enumerate(result["ids"][0]):
            meta = (result["metadatas"] or [[]])[0][i] or {}
            dist = (result["distances"] or [[]])[0][i]
            chunks.append(
                {
                    "team_id": meta.get("team_id", ""),
                    "title": meta.get("title", ""),
                    "section": meta.get("section", ""),
                    "content": (result["documents"] or [[]])[0][i] or "",
                    "source": meta.get("source_file", ""),
                    "score": round(1 - dist, 4) if dist is not None else 0.0,
                }
            )
        return chunks


def create_vector_store() -> VectorStore:
    if settings.rag_backend == "chroma":
        return ChromaVectorStore()
    return TeamDocStore()


async def rag_search(
    query: str,
    vector_store: VectorStore,
    team_ids: list[str] | None = None,
) -> ToolResult:
    """Search team tactical docs (mock keyword or Chroma semantic)."""
    import random

    start = time.perf_counter()
    tool_name = "rag"

    try:
        if settings.rag_backend == "mock":
            await asyncio.sleep(settings.mock_rag_delay)
            if settings.mock_failure_rate > 0 and random.random() < settings.mock_failure_rate:
                raise RuntimeError("RAG service unavailable")
        chunks = await vector_store.search(query, top_k=4, team_ids=team_ids)
        latency_ms = (time.perf_counter() - start) * 1000
        logger.info(
            "tool_completed",
            tool=tool_name,
            latency_ms=round(latency_ms, 2),
            chunks=len(chunks),
            backend=settings.rag_backend,
            success=True,
        )
        return ToolResult(
            tool_name=tool_name,
            success=True,
            data={"query": query, "chunks": chunks},
            latency_ms=latency_ms,
        )
    except Exception as exc:
        latency_ms = (time.perf_counter() - start) * 1000
        logger.warning("tool_failed", tool=tool_name, latency_ms=round(latency_ms, 2), error=str(exc))
        return ToolResult(
            tool_name=tool_name,
            success=False,
            data={"query": query, "chunks": []},
            error=str(exc),
            latency_ms=latency_ms,
        )
