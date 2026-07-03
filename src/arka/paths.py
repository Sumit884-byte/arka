"""Cross-platform paths for Arka (macOS, Windows, Linux)."""

from __future__ import annotations

import os
import re
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
    if (bundled / "config.fish").is_file():
        return bundled

    # Editable dev: repo root when bundled not synced yet
    root = checkout_root()
    if root and (root / "pyproject.toml").is_file():
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
    return entry_script(name)


def entry_script(name: str) -> Path:
    """Resolve a legacy CLI shim (dev: bin/, pip bundle: flat in bundled/)."""
    for base in (arka_home(), bundled_dir()):
        for candidate in (base / "bin" / name, base / name):
            if candidate.is_file():
                return candidate
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

    from arka.platform_info import ensure_platform_cache

    ensure_platform_cache()

    return arka_home()


def stock_project_dir() -> Path:
    """Optional stock_analysis checkout (bridge commands need this directory)."""
    try:
        from arka.agent.profession_projects import profession_project_path

        inv = profession_project_path("investor")
        if inv:
            return inv
    except ImportError:
        pass
    default = Path.home() / "Projects/professions/investor/stock_analyzer"
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
    return checkout_root()


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
    from arka.env import normalize_env_aliases

    normalize_env_aliases()
