"""Persistent cache for social code lookup results."""

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


def social_code_cache_path() -> Path:
    return config_dir() / "social_code_cache.json"


def social_code_cache_enabled() -> bool:
    raw = os.environ.get("ARKA_SOCIAL_CODE_CACHE", os.environ.get("ARKA_ANSWER_CACHE", "1"))
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def social_code_cache_ttl() -> float:
    raw = os.environ.get(
        "ARKA_SOCIAL_CODE_CACHE_TTL",
        os.environ.get("ARKA_ANSWER_CACHE_TTL", "86400"),
    ).strip()
    try:
        ttl = float(raw)
    except ValueError:
        ttl = 86400.0
    return max(0.0, ttl)


def normalize_cache_key(query: str, platforms: list[str] | None = None) -> str:
    q = re.sub(r"\s+", " ", (query or "").strip().casefold())
    q = q.rstrip("?.!")
    if platforms:
        joined = ",".join(sorted(p.casefold() for p in platforms if p))
        if joined:
            return f"{q}|{joined}"
    return q


def _load_store() -> dict[str, Any]:
    path = social_code_cache_path()
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
    path = social_code_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8")


def get_cached_payload(query: str, platforms: list[str] | None = None) -> dict[str, Any] | None:
    if not social_code_cache_enabled():
        return None
    ttl = social_code_cache_ttl()
    if ttl <= 0:
        return None
    key = normalize_cache_key(query, platforms)
    if not key:
        return None
    entry = _load_store().get("entries", {}).get(key)
    if not isinstance(entry, dict):
        return None
    payload = entry.get("payload")
    if not isinstance(payload, dict):
        return None
    try:
        updated = float(entry.get("updated", 0))
    except (TypeError, ValueError):
        return None
    if time.time() - updated >= ttl:
        return None
    cached = dict(payload)
    cached["cached"] = True
    return cached


def set_cached_payload(query: str, payload: dict[str, Any], platforms: list[str] | None = None) -> None:
    if not social_code_cache_enabled():
        return
    if social_code_cache_ttl() <= 0:
        return
    if not isinstance(payload, dict) or not payload.get("results"):
        return
    key = normalize_cache_key(query, platforms)
    if not key:
        return
    store = _load_store()
    entries = store.setdefault("entries", {})
    if not isinstance(entries, dict):
        entries = {}
        store["entries"] = entries
    to_store = dict(payload)
    to_store["cached"] = False
    entries[key] = {"payload": to_store, "updated": time.time()}
    _save_store(store)


def clear_social_code_cache() -> None:
    path = social_code_cache_path()
    if path.is_file():
        path.unlink()
