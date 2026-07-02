#!/usr/bin/env python3
"""Shared paths for arka_*.py scripts (lives in the package bundle)."""

from __future__ import annotations

import os
import re
from pathlib import Path


def arka_home() -> Path:
    """Directory containing bundled arka_*.py (package install dir)."""
    if v := os.environ.get("ARKA_HOME", "").strip():
        return Path(v).expanduser().resolve()
    return Path(__file__).resolve().parent


def config_dir() -> Path:
    if v := os.environ.get("ARKA_CONFIG_DIR", "").strip():
        return Path(v).expanduser().resolve()
    legacy = Path.home() / ".config" / "fish"
    if (legacy / ".env").is_file():
        return legacy
    try:
        from platformdirs import user_config_dir

        p = Path(user_config_dir("arka", appauthor=False))
    except ImportError:
        p = Path.home() / ".config" / "arka"
    p.mkdir(parents=True, exist_ok=True)
    return p


def cache_dir() -> Path:
    if v := os.environ.get("ARKA_CACHE_DIR", "").strip():
        return Path(v).expanduser().resolve()
    legacy = Path.home() / ".cache" / "fish-agent"
    if legacy.is_dir() and not os.environ.get("ARKA_CACHE_DIR"):
        return legacy
    try:
        from platformdirs import user_cache_dir

        p = Path(user_cache_dir("arka", appauthor=False))
    except ImportError:
        p = Path.home() / ".cache" / "arka"
    p.mkdir(parents=True, exist_ok=True)
    return p


def env_file() -> Path:
    return config_dir() / ".env"


def stock_project_dir() -> Path:
    """Optional stock_analysis checkout (bridge commands need this directory)."""
    default = Path.home() / "Projects/python/products/stock_analysis"
    raw = os.environ.get("ARKA_STOCK_PROJECT", "").strip()
    if raw:
        configured = Path(raw).expanduser()
        if configured.is_dir():
            return configured.resolve()
    return default


_PLACEHOLDER_RE = re.compile(
    r"your_.*_here|^changeme$|^xxx+$|^replace[_-]?me$",
    re.IGNORECASE,
)


def _is_placeholder(val: str) -> bool:
    v = (val or "").strip()
    if not v:
        return True
    return bool(_PLACEHOLDER_RE.search(v))


def _checkout_root() -> Path | None:
    root = Path(__file__).resolve().parent
    if (root / "pyproject.toml").is_file():
        return root
    return None


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


def load_env_file() -> None:
    paths: list[Path] = []
    cfg = env_file()
    if cfg.is_file():
        paths.append(cfg)
    legacy = Path.home() / ".config" / "fish" / ".env"
    if legacy.is_file():
        paths.append(legacy)
    root = _checkout_root()
    if root:
        dev_env = root / ".env"
        if dev_env.is_file():
            paths.append(dev_env)
    home_env = arka_home() / ".env"
    if home_env.is_file():
        paths.append(home_env)
    if not paths:
        example = arka_home() / ".env.example"
        if example.is_file():
            paths.append(example)
    seen: set[Path] = set()
    for path in paths:
        path = path.expanduser().resolve()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        _apply_env_file(path)
