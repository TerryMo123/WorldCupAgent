"""Split team markdown docs into RAG chunks."""

from __future__ import annotations

from pathlib import Path


def extract_title(text: str) -> str:
    for line in text.splitlines():
        if line.startswith("# "):
            return line[2:].strip()
    return ""


def chunk_markdown_file(path: Path) -> list[dict]:
    """Split by ## sections; fallback to whole document."""
    text = path.read_text(encoding="utf-8")
    team_id = path.stem
    doc_title = extract_title(text) or team_id
    chunks: list[dict] = []

    sections: list[tuple[str, str]] = []
    current_heading = "overview"
    current_lines: list[str] = []

    for line in text.splitlines():
        if line.startswith("## "):
            if current_lines:
                sections.append((current_heading, "\n".join(current_lines).strip()))
            current_heading = line[3:].strip()
            current_lines = []
        else:
            current_lines.append(line)

    if current_lines:
        sections.append((current_heading, "\n".join(current_lines).strip()))

    if not sections:
        sections = [("overview", text.strip())]

    for heading, body in sections:
        if not body:
            continue
        section_slug = heading.replace(" ", "_").lower()[:40]
        chunk_id = f"{team_id}-{section_slug}"
        content = f"## {heading}\n\n{body}" if heading != "overview" else body
        chunks.append(
            {
                "id": chunk_id,
                "team_id": team_id,
                "title": doc_title,
                "section": heading,
                "content": content,
            }
        )

    return chunks


def chunk_docs_dir(docs_dir: Path) -> list[dict]:
    all_chunks: list[dict] = []
    if not docs_dir.exists():
        return all_chunks
    for path in sorted(docs_dir.glob("*.md")):
        all_chunks.extend(chunk_markdown_file(path))
    return all_chunks
