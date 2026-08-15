"""Cached folder resolution and short aliases for `arka to` / `to`."""

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


# Short alias -> folder names to try under $HOME (first existing wins).
DEFAULT_ALIASES: dict[str, list[str]] = {
    "dev": ["dev", "Developer", "Developers", "development"],
    "dl": ["Downloads"],
    "docs": ["Documents"],
    "desk": ["Desktop"],
    "pics": ["Pictures"],
    "proj": ["Projects"],
    "downloads": ["Downloads"],
    "documents": ["Documents"],
    "desktop": ["Desktop"],
    "pictures": ["Pictures"],
    "projects": ["Projects"],
    "music": ["Music"],
    "videos": ["Videos"],
}


def folder_cache_path() -> Path:
    return config_dir() / "folder_cache.json"


def folder_cache_enabled() -> bool:
    return os.environ.get("ARKA_FOLDER_CACHE", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def normalize_folder_key(name: str) -> str:
    return re.sub(r"\s+", " ", (name or "").strip().casefold())


def _canonical_dir(path: Path) -> Path | None:
    try:
        p = path.expanduser()
        if not p.is_dir():
            return None
        return p.resolve()
    except OSError:
        return None


def _load_store() -> dict[str, Any]:
    path = folder_cache_path()
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            entries = data.get("entries")
            aliases = data.get("aliases")
            return {
                "version": 1,
                "entries": entries if isinstance(entries, dict) else {},
                "aliases": aliases if isinstance(aliases, dict) else {},
            }
    except (OSError, json.JSONDecodeError):
        pass
    return {"version": 1, "entries": {}, "aliases": {}}


def _save_store(store: dict[str, Any]) -> None:
    path = folder_cache_path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(store, indent=2, ensure_ascii=False), encoding="utf-8")


def get_cached_folder(name: str) -> Path | None:
    if not folder_cache_enabled():
        return None
    key = normalize_folder_key(name)
    if not key:
        return None
    entry = _load_store().get("entries", {}).get(key)
    if not isinstance(entry, dict):
        return None
    raw = entry.get("path")
    if not isinstance(raw, str) or not raw.strip():
        return None
    return _canonical_dir(Path(raw))


def remember_folder(name: str, path: Path) -> None:
    if not folder_cache_enabled():
        return
    canon = _canonical_dir(path)
    if canon is None:
        return
    key = normalize_folder_key(name)
    if not key:
        return
    store = _load_store()
    entries = store.setdefault("entries", {})
    if not isinstance(entries, dict):
        entries = {}
        store["entries"] = entries
    entries[key] = {"path": str(canon), "updated": time.time()}
    _save_store(store)


def _user_alias_targets(name: str) -> list[str]:
    key = normalize_folder_key(name)
    store = _load_store()
    aliases = store.get("aliases") or {}
    if not isinstance(aliases, dict):
        return []
    target = aliases.get(key)
    if isinstance(target, str) and target.strip():
        return [target.strip()]
    return []


def resolve_alias(name: str, *, home: Path | None = None) -> Path | None:
    home = home or Path.home()
    key = normalize_folder_key(name)
    if not key:
        return None

    candidates: list[Path] = []
    seen: set[Path] = set()

    def _add(path: Path) -> None:
        canon = _canonical_dir(path)
        if canon and canon not in seen:
            seen.add(canon)
            candidates.append(canon)

    for target in _user_alias_targets(name):
        _add(Path(target))
        if not Path(target).is_absolute():
            _add(home / target)

    for folder_name in DEFAULT_ALIASES.get(key, []):
        _add(home / folder_name)

    if len(candidates) == 1:
        return candidates[0]
    if candidates:
        return candidates[0]
    return None


def fuzzy_home_match(name: str, *, home: Path | None = None) -> Path | None:
    """Prefix-match home subdirs for short names (e.g. dev -> ~/dev, ~/Developer)."""
    key = normalize_folder_key(name)
    if not key or len(key) > 6:
        return None
    home = home or Path.home()
    if not home.is_dir():
        return None

    exact: list[Path] = []
    prefix: list[Path] = []
    try:
        for d in home.iterdir():
            if not d.is_dir():
                continue
            low = d.name.casefold()
            if low == key:
                canon = _canonical_dir(d)
                if canon:
                    exact.append(canon)
            elif low.startswith(key):
                canon = _canonical_dir(d)
                if canon:
                    prefix.append(canon)
    except OSError:
        return None

    if len(exact) == 1:
        return exact[0]
    if exact:
        return exact[0]
    if len(prefix) == 1:
        return prefix[0]
    if prefix:
        return sorted(prefix, key=lambda p: len(p.name))[0]
    return None
