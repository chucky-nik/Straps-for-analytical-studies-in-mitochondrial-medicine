from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from mito_harness.config import settings

_TEXT_CACHE: dict[str, str] = {}
_JSON_CACHE: dict[str, dict[str, Any]] = {}


def _skills_dir() -> Path:
    return Path(settings()["skills_dir"])


def load_skill(name: str) -> str:
    """Runtime-инъекция Markdown skill из /skills (name без .md)."""
    key = name[:-3] if name.endswith(".md") else name
    if key in _TEXT_CACHE:
        return _TEXT_CACHE[key]
    path = _skills_dir() / f"{key}.md"
    if not path.exists():
        raise FileNotFoundError(f"Skill not found: {path}")
    text = path.read_text(encoding="utf-8")
    _TEXT_CACHE[key] = text
    return text


def load_json_skill(name: str) -> dict[str, Any]:
    """Runtime-инъекция JSON skill (name с или без .json)."""
    key = name if name.endswith(".json") else f"{name}.json"
    cache_key = key[:-5]
    if cache_key in _JSON_CACHE:
        return _JSON_CACHE[cache_key]
    path = _skills_dir() / key
    if not path.exists():
        raise FileNotFoundError(f"JSON skill not found: {path}")
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise ValueError(f"JSON skill must be object: {path}")
    _JSON_CACHE[cache_key] = data
    return data


def list_skills() -> list[str]:
    d = _skills_dir()
    names = {p.stem for p in d.glob("*.md")} | {p.stem for p in d.glob("*.json")}
    return sorted(names)
