#!/usr/bin/env python3
"""Chunk team docs, embed via DashScope, persist to Chroma."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from app.config import settings  # noqa: E402
from app.llm.client import embed_texts_sync  # noqa: E402
from app.tools.rag_chunks import chunk_docs_dir  # noqa: E402

BATCH_SIZE = 10


def main() -> None:
    parser = argparse.ArgumentParser(description="Ingest team docs into Chroma vector store")
    parser.add_argument("--force", action="store_true", help="Delete and recreate collection")
    parser.add_argument("--docs-dir", type=Path, default=None)
    args = parser.parse_args()

    if not settings.dashscope_api_key:
        print("Error: set DASHSCOPE_API_KEY in .env", file=sys.stderr)
        sys.exit(1)

    docs_dir = args.docs_dir or settings.docs_dir
    chunks = chunk_docs_dir(docs_dir)
    if not chunks:
        print(f"No markdown files in {docs_dir}")
        sys.exit(1)

    import chromadb

    settings.chroma_persist_dir.mkdir(parents=True, exist_ok=True)
    client = chromadb.PersistentClient(path=str(settings.chroma_persist_dir))

    if args.force:
        try:
            client.delete_collection(settings.chroma_collection)
            print(f"Deleted collection: {settings.chroma_collection}")
        except Exception:
            pass

    collection = client.get_or_create_collection(
        name=settings.chroma_collection,
        metadata={"hnsw:space": "cosine"},
    )

    if not args.force and collection.count() > 0:
        print(
            f"Collection already has {collection.count()} items. "
            "Use --force to rebuild."
        )
        sys.exit(0)

    ids: list[str] = []
    documents: list[str] = []
    metadatas: list[dict] = []

    for chunk in chunks:
        ids.append(chunk["id"])
        documents.append(chunk["content"])
        metadatas.append(
            {
                "team_id": chunk["team_id"],
                "title": chunk["title"],
                "section": chunk["section"],
                "source_file": f"{chunk['team_id']}.md",
            }
        )

    print(f"Embedding {len(documents)} chunks with {settings.embedding_model}...")
    all_embeddings: list[list[float]] = []
    for i in range(0, len(documents), BATCH_SIZE):
        batch = documents[i : i + BATCH_SIZE]
        vecs = embed_texts_sync(batch)
        all_embeddings.extend(vecs)
        print(f"  {min(i + BATCH_SIZE, len(documents))}/{len(documents)}")

    collection.add(
        ids=ids,
        embeddings=all_embeddings,
        documents=documents,
        metadatas=metadatas,
    )
    print(f"Done. {collection.count()} vectors in {settings.chroma_persist_dir}")


if __name__ == "__main__":
    main()
