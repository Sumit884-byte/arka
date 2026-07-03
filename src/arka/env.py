"""Load .env into os.environ (cross-platform)."""

from __future__ import annotations

import os
import re
from pathlib import Path

from arka.paths import arka_home, cache_dir, checkout_root, config_dir, env_file

_PLACEHOLDER_RE = re.compile(
    r"your_.*_here|^changeme$|^xxx+$|^replace[_-]?me$",
    re.IGNORECASE,
)

# Short names in .env (preferred) ↔ legacy ARKA_* names used in code.
_ENV_ALIASES: dict[str, str] = {
    "REMOTE_TOKEN": "ARKA_REMOTE_TOKEN",
    "REMOTE_PORT": "ARKA_REMOTE_PORT",
    "REMOTE_HOST": "ARKA_REMOTE_HOST",
    "REMOTE_URL": "ARKA_REMOTE_URL",
    "SPEAK_LANG": "ARKA_SPEAK_LANG",
    "SPEAK_VOICE": "ARKA_SPEAK_VOICE",
    "STT": "ARKA_STT",
    "LISTEN_ENGINE": "ARKA_LISTEN_ENGINE",
    "AUTO_START": "ARKA_AUTO_START",
    "REMOTE_AUTO": "ARKA_REMOTE_AUTO",
    "USAGE_TRACK": "ARKA_USAGE_TRACK",
    "WEB_TRACK": "ARKA_WEB_TRACK",
    "ROUTE_MODE": "ARKA_ROUTE_MODE",
    "CONFIG_DIR": "ARKA_CONFIG_DIR",
    "CACHE_DIR": "ARKA_CACHE_DIR",
    "HOME": "ARKA_HOME",
}


def _is_placeholder(val: str) -> bool:
    v = (val or "").strip()
    if not v:
        return True
    return bool(_PLACEHOLDER_RE.search(v))


def _apply_env_file(path: Path) -> None:
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'\"")
        val = re.sub(r"\s+#.*$", "", val).strip()
        if not key or _is_placeholder(val):
            continue
        current = os.environ.get(key, "").strip()
        if not current or _is_placeholder(current):
            os.environ[key] = val


def normalize_env_aliases() -> None:
    """Mirror short .env names (REMOTE_TOKEN) and legacy ARKA_* keys."""
    for short, legacy in _ENV_ALIASES.items():
        short_v = os.environ.get(short, "").strip()
        legacy_v = os.environ.get(legacy, "").strip()
        if short_v and not _is_placeholder(short_v):
            if not legacy_v or _is_placeholder(legacy_v):
                os.environ[legacy] = short_v
        elif legacy_v and not _is_placeholder(legacy_v):
            if not short_v or _is_placeholder(short_v):
                os.environ[short] = legacy_v


def env_get(*keys: str, default: str = "") -> str:
    """First non-empty env var among keys (after alias normalization)."""
    for key in keys:
        val = os.environ.get(key, "").strip()
        if val and not _is_placeholder(val):
            return val
    return default


def load_env(extra: Path | None = None) -> None:
    paths: list[Path] = []
    if extra:
        paths.append(extra)
    paths.append(env_file())
    legacy = Path.home() / ".config" / "fish" / ".env"
    if legacy.is_file():
        paths.append(legacy)
    root = checkout_root()
    if root:
        dev_env = root / ".env"
        if dev_env.is_file():
            paths.append(dev_env)
    home_env = arka_home() / ".env"
    if home_env.is_file():
        paths.append(home_env)

    seen: set[Path] = set()
    for path in paths:
        path = path.expanduser().resolve()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        _apply_env_file(path)

    normalize_env_aliases()

    os.environ.setdefault("ARKA_CONFIG_DIR", str(config_dir()))
    os.environ.setdefault("ARKA_CACHE_DIR", str(cache_dir()))
