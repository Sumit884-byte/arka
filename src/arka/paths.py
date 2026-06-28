"""Cross-platform paths for Arka (macOS, Windows, Linux)."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path


def _platformdirs():
    from platformdirs import user_cache_dir, user_config_dir

    return user_config_dir, user_cache_dir


def package_dir() -> Path:
    return Path(__file__).resolve().parent


def bundled_dir() -> Path:
    """Runtime scripts shipped inside the installed package."""
    return package_dir() / "bundled"


def checkout_root() -> Path | None:
    """Git repo root when running from a clone (editable install)."""
    root = package_dir().parent.parent
    if (root / "pyproject.toml").is_file():
        return root
    return None


def arka_home() -> Path:
    """Directory containing arka_*.py — always the package bundle unless ARKA_HOME is set."""
    if env := os.environ.get("ARKA_HOME", "").strip():
        return Path(env).expanduser().resolve()

    bundled = bundled_dir()
    if (bundled / "arka_chat.py").is_file():
        return bundled

    # Editable dev: repo root when bundled not synced yet
    root = checkout_root()
    if root and (root / "arka_chat.py").is_file():
        return root

    return bundled


def config_dir() -> Path:
    """User-writable config (.env, overrides) — not the package install dir."""
    if env := os.environ.get("ARKA_CONFIG_DIR", "").strip():
        return Path(env).expanduser().resolve()

    legacy = Path.home() / ".config" / "fish"
    if (legacy / ".env").is_file():
        return legacy

    user_config_dir, _ = _platformdirs()
    return Path(user_config_dir("arka", appauthor=False))


def cache_dir() -> Path:
    if env := os.environ.get("ARKA_CACHE_DIR", "").strip():
        return Path(env).expanduser().resolve()
    _, user_cache_dir = _platformdirs()
    legacy_cache = Path.home() / ".cache" / "fish-agent"
    if legacy_cache.is_dir() and not os.environ.get("ARKA_CACHE_DIR"):
        return legacy_cache
    return Path(user_cache_dir("arka", appauthor=False))


def script_path(name: str) -> Path:
    return arka_home() / name


def python_executable() -> str:
    return sys.executable


def env_file() -> Path:
    return config_dir() / ".env"


def fish_config() -> Path | None:
    for candidate in (
        arka_home() / "config.fish",
        config_dir() / "config.fish",
        Path.home() / ".config" / "fish" / "config.fish",
    ):
        if candidate.is_file():
            return candidate
    return None


def bundled_env_example() -> Path:
    return bundled_dir() / ".env.example"


def ensure_layout() -> Path:
    """Create user config/cache dirs and seed .env from package template."""
    config_dir().mkdir(parents=True, exist_ok=True)
    cache_dir().mkdir(parents=True, exist_ok=True)

    example = config_dir() / ".env.example"
    if not example.is_file():
        src = bundled_env_example()
        if src.is_file():
            shutil.copy2(src, example)

    env = env_file()
    if not env.is_file() and example.is_file():
        shutil.copy2(example, env)

    return arka_home()
