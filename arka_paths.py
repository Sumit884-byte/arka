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


def load_env_file() -> None:
    path = env_file()
    if not path.is_file():
        bundled = arka_home() / ".env.example"
        if bundled.is_file():
            path = bundled
        else:
            return
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'\"")
        val = re.sub(r"\s+#.*$", "", val).strip()
        if key and not os.environ.get(key, "").strip():
            os.environ[key] = val
