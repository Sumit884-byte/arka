"""Persistent cache for encyclopedic Q&A (who/what definitional questions)."""

from __future__ import annotations

import json
import os
import re
import time
from pathlib import Path
from typing import Any

try:
    from arka.paths import config_dir
except ImportError:

    def config_dir() -> Path:
        return Path.home() / ".config" / "arka"


def answer_cache_path() -> Path:
    return config_dir() / "answer_cache.json"


def answer_cache_enabled() -> bool:
    return os.environ.get("ARKA_ANSWER_CACHE", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def answer_cache_ttl() -> float:
    raw = os.environ.get("ARKA_ANSWER_CACHE_TTL", "86400").strip()
    try:
        ttl = float(raw)
    except ValueError:
        ttl = 86400.0
    return max(0.0, ttl)


def normalize_cache_key(query: str) -> str:
    q = re.sub(r"\s+", " ", (query or "").strip().casefold())
    return q.rstrip("?.!")


def is_encyclopedic_query(query: str) -> bool:
    try:
        from arka.core.habitat import is_definitional_query

        return is_definitional_query(query)
    except ImportError:
        q = (query or "").strip()
        return bool(
            re.match(
                r"(?i)^(?:what|who|where|when|why|how|explain|describe|tell\s+me\s+about)\s+",
                q,
            )
        )


def _load_store() -> dict[str, Any]:
    path = answer_cache_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            entries = data.get("entries")
            if isinstance(entries, dict):
                return {"version": 1, "entries": entries}
    except (OSError, json.JSONDecodeError):
        pass
    return {"version": 1, "entries": {}}


def _save_store(store: dict[str, Any]) -> None:
    path = answer_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8")


def get_cached_answer(query: str) -> str | None:
    if not answer_cache_enabled():
        return None
    ttl = answer_cache_ttl()
    if ttl <= 0:
        return None
    key = normalize_cache_key(query)
    if not key:
        return None
    entry = _load_store().get("entries", {}).get(key)
    if not isinstance(entry, dict):
        return None
    answer = entry.get("answer")
    if not isinstance(answer, str) or not answer.strip():
        return None
    try:
        updated = float(entry.get("updated", 0))
    except (TypeError, ValueError):
        return None
    if time.time() - updated >= ttl:
        return None
    return answer


def set_cached_answer(query: str, answer: str) -> None:
    if not answer_cache_enabled():
        return
    if answer_cache_ttl() <= 0:
        return
    text = (answer or "").strip()
    if not text:
        return
    key = normalize_cache_key(query)
    if not key:
        return
    store = _load_store()
    entries = store.setdefault("entries", {})
    if not isinstance(entries, dict):
        entries = {}
        store["entries"] = entries
    entries[key] = {"answer": text, "updated": time.time()}
    _save_store(store)


def clear_answer_cache() -> None:
    path = answer_cache_path()
    if path.is_file():
        path.unlink()
