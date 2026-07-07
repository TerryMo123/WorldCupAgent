#!/usr/bin/env python3
"""Inspect Chroma vector store: collection stats and trial semantic search."""

from __future__ import annotations

import argparse
import sys
from collections import Counter
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402


def _open_collection():
    import chromadb

    if not settings.chroma_persist_dir.exists():
        print(f"Chroma 目录不存在: {settings.chroma_persist_dir}")
        print("请先运行: python scripts/ingest_embeddings.py --force")
        sys.exit(1)

    client = chromadb.PersistentClient(path=str(settings.chroma_persist_dir))
    try:
        return client.get_collection(settings.chroma_collection)
    except Exception:
        print(f"集合不存在: {settings.chroma_collection}")
        print("请先运行: python scripts/ingest_embeddings.py --force")
        sys.exit(1)


def print_stats(collection) -> None:
    """集合统计：向量库里有多少数据、怎么分布的。"""
    count = collection.count()
    if count == 0:
        print("集合为空，请运行 ingest_embeddings.py")
        return

    rows = collection.get(include=["metadatas"])
    metas = rows["metadatas"] or []

    team_counts = Counter(m.get("team_id", "?") for m in metas)
    section_counts = Counter(m.get("section", "?") for m in metas)

    persist = settings.chroma_persist_dir.resolve()
    size_mb = sum(f.stat().st_size for f in persist.rglob("*") if f.is_file()) / (1024 * 1024)

    print("=== 集合统计 ===")
    print(f"集合名称:     {settings.chroma_collection}")
    print(f"存储路径:     {persist}")
    print(f"磁盘占用:     {size_mb:.2f} MB")
    print(f"向量总数:     {count}")
    print(f"球队数量:     {len(team_counts)}")
    print(f"小节类型数:   {len(section_counts)}")
    print()
    print("--- 各球队 chunk 数（前 10）---")
    for team_id, n in team_counts.most_common(10):
        print(f"  {team_id}: {n}")
    if len(team_counts) > 10:
        print(f"  ... 共 {len(team_counts)} 支球队")
    print()
    print("--- 各小节 chunk 数 ---")
    for section, n in section_counts.most_common():
        print(f"  {section}: {n}")


def print_samples(collection, limit: int) -> None:
    """展示若干条原始记录，方便肉眼核对。"""
    rows = collection.get(limit=limit, include=["metadatas", "documents"])
    print(f"\n=== 样本记录（前 {limit} 条）===")
    for doc_id, meta, doc in zip(rows["ids"], rows["metadatas"], rows["documents"], strict=True):
        preview = (doc or "").replace("\n", " ")[:120]
        print(f"\n[{doc_id}]")
        print(f"  team_id: {meta.get('team_id')} | section: {meta.get('section')}")
        print(f"  text:    {preview}...")


def trial_search(collection, query: str, top_k: int, team_ids: list[str] | None) -> None:
    """试检索：用一句问话测试 RAG 能否找到相关文档片段。"""
    if not settings.dashscope_api_key:
        print("试检索需要 DASHSCOPE_API_KEY（用于把问句转成向量）", file=sys.stderr)
        sys.exit(1)

    from app.llm.client import embed_texts_sync

    print(f"\n=== 试检索 ===")
    print(f"问句:     {query}")
    print(f"返回条数: {top_k}")
    if team_ids:
        print(f"限定球队: {', '.join(team_ids)}")

    query_vec = embed_texts_sync([query])[0]
    where = {"team_id": {"$in": team_ids}} if team_ids else None

    result = collection.query(
        query_embeddings=[query_vec],
        n_results=top_k,
        where=where,
        include=["metadatas", "documents", "distances"],
    )

    if not result["ids"] or not result["ids"][0]:
        print("未命中任何片段")
        return

    for i, doc_id in enumerate(result["ids"][0]):
        meta = result["metadatas"][0][i]
        dist = result["distances"][0][i]
        doc = result["documents"][0][i]
        score = round(1 - dist, 4) if dist is not None else 0.0
        preview = (doc or "").replace("\n", " ")[:160]
        print(f"\n#{i + 1}  [{doc_id}]  相似度≈{score}")
        print(f"    team: {meta.get('team_id')} | section: {meta.get('section')}")
        print(f"    {preview}...")


def main() -> None:
    parser = argparse.ArgumentParser(
        description="查看 Chroma 向量库统计，或试跑一次语义检索",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
示例:
  python scripts/inspect_chroma.py
  python scripts/inspect_chroma.py --sample 5
  python scripts/inspect_chroma.py --query "巴西 进攻 优势"
  python scripts/inspect_chroma.py --query "法国 防守" --team france,brazil --top 3
        """,
    )
    parser.add_argument("--query", "-q", help="试检索：输入一句问话，看最相关的文档片段")
    parser.add_argument("--team", "-t", help="试检索时限定球队 ID，逗号分隔，如 brazil,france")
    parser.add_argument("--top", type=int, default=5, help="试检索返回条数（默认 5）")
    parser.add_argument("--sample", type=int, default=0, help="展示前 N 条原始记录")
    parser.add_argument("--stats-only", action="store_true", help="只打印统计，不展示样本")
    args = parser.parse_args()

    collection = _open_collection()
    print_stats(collection)

    if args.sample > 0:
        print_samples(collection, args.sample)

    if args.query:
        team_ids = [t.strip() for t in args.team.split(",") if t.strip()] if args.team else None
        trial_search(collection, args.query, args.top, team_ids)
    elif not args.stats_only and args.sample == 0:
        print("\n提示: 加 --query \"巴西 战术 优势\" 可试检索；加 --sample 3 可看原始片段")


if __name__ == "__main__":
    main()
