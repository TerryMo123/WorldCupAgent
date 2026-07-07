"""Team name normalization loaded from teams.csv registry."""

from __future__ import annotations

import csv
from functools import lru_cache
from pathlib import Path

from app.config import settings

# Manual aliases (Chinese / common shortcuts) merged with CSV registry
MANUAL_ALIASES: dict[str, str] = {
    "巴西": "brazil",
    "法国": "france",
    "阿根廷": "argentina",
    "德国": "germany",
    "usa": "usa",
    "美国": "usa",
    "韩国": "south_korea",
    "korea republic": "south_korea",
    "荷兰": "netherlands",
    "英格兰": "england",
    "西班牙": "spain",
    "意大利": "italy",
    "葡萄牙": "portugal",
    "克罗地亚": "croatia",
    "摩洛哥": "morocco",
    "日本": "japan",
    "墨西哥": "mexico",
}


@lru_cache
def _registry_path() -> Path:
    return settings.data_dir / "teams.csv"


def reload_team_registry() -> None:
    _build_registry.cache_clear()


@lru_cache
def _build_registry() -> dict[str, str]:
    mapping = {k.lower(): v for k, v in MANUAL_ALIASES.items()}
    mapping.update(MANUAL_ALIASES)

    path = _registry_path()
    if not path.exists():
        return mapping

    with path.open(encoding="utf-8") as f:
        for row in csv.DictReader(f):
            tid = row["team_id"].strip()
            mapping[tid] = tid
            mapping[tid.lower()] = tid
            name_en = row.get("name_en", "").strip()
            if name_en:
                mapping[name_en.lower()] = tid
            name_zh = row.get("name_zh", "").strip()
            if name_zh:
                mapping[name_zh] = tid
            fifa_code = row.get("fifa_code", "").strip()
            if fifa_code:
                mapping[fifa_code.lower()] = tid
    return mapping


def normalize_team_id(name: str) -> str | None:
    stripped = name.strip()
    if not stripped:
        return None
    registry = _build_registry()
    if stripped in registry:
        return registry[stripped]
    key = stripped.lower()
    if key in registry:
        return registry[key]
    # slug fallback for direct id input
    slug = key.replace(" ", "_").replace("-", "_")
    if slug in registry:
        return registry[slug]
    return None


def normalize_pair(team_a: str, team_b: str) -> tuple[str | None, str | None]:
    return normalize_team_id(team_a), normalize_team_id(team_b)
