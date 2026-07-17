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
    """Directory containing arka_*.py — always the package bundle unless INSTALL_HOME is set."""
    if env := os.environ.get("INSTALL_HOME", "").strip():
        return Path(env).expanduser().resolve()

    bundled = bundled_dir()
    if (bundled / "config.fish").is_file():
        return bundled

    # Editable dev: repo root when bundled not synced yet
    root = checkout_root()
    if root and (root / "pyproject.toml").is_file():
        return root

    return bundled


def _config_dir_override() -> Path | None:
    """Explicit config root from CONFIG_DIR or ARKA_CONFIG_DIR."""
    for key in ("CONFIG_DIR", "ARKA_CONFIG_DIR"):
        if env := os.environ.get(key, "").strip():
            return Path(env).expanduser().resolve()
    return None


def _platform_config_dir() -> Path:
    user_config_dir, _ = _platformdirs()
    return Path(user_config_dir("arka", appauthor=False))


def checkout_state_dir() -> Path | None:
    """Gitignored runtime state folder for editable checkouts (``<repo>/.arka``)."""
    root = checkout_root()
    if root is None:
        return None
    return root / ".arka"


# Runtime JSON / state files that historically landed at repo root during dev.
_RUNTIME_JSON_FILES = (
    "code-project.json",
    "council-memory.json",
    "mcp.json",
    "personalize.json",
    "platform.json",
    "repo-index.json",
    "self-improve-memory.json",
    "config.json",
    "learned_routes.json",
    "skills.json",
    "benchmark-results.json",
    "llm-skill-models.json",
)

_RUNTIME_STATE_DIRS = (
    "message-sessions",
    "quiz-memory",
    "agent-memory",
    "teams",
    "workflows",
    "skills",
    "personas",
    "backups",
    "benchmarks",
    "memory-scratchpad",
)

_RUNTIME_STATE_FILES = (
    "last-refetch",
    "platform.env",
    "mode",
    "thinking_level",
)

# Repo ``hub/`` ships adapter snippets; runtime hub exports live under config_dir()/hub/.
_HUB_RUNTIME_FILES = ("agents.json", "mcp.json", "launch.env")
_HUB_RUNTIME_DIRS = ("memory", "skills")


def config_dir() -> Path:
    """User-writable config (.env, overrides) — not the package install dir."""
    if override := _config_dir_override():
        return override

    legacy = Path.home() / ".config" / "fish"
    if (legacy / ".env").is_file():
        return legacy

    if state := checkout_state_dir():
        return state

    return _platform_config_dir()


def _move_if_missing(src: Path, dst: Path, *, moved: list[str]) -> None:
    if not src.is_file() or dst.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    moved.append(str(dst))


def _move_dir_if_missing(src: Path, dst: Path, *, moved: list[str]) -> None:
    if not src.is_dir() or dst.exists():
        return
    dst.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dst))
    moved.append(str(dst))


def _migrate_hub_runtime(src_hub: Path, dst_hub: Path, *, moved: list[str]) -> None:
    if not src_hub.is_dir():
        return
    dst_hub.mkdir(parents=True, exist_ok=True)
    for name in _HUB_RUNTIME_FILES:
        _move_if_missing(src_hub / name, dst_hub / name, moved=moved)
    for name in _HUB_RUNTIME_DIRS:
        _move_dir_if_missing(src_hub / name, dst_hub / name, moved=moved)


def migrate_scattered_state(*, target: Path | None = None) -> list[str]:
    """Move dev runtime state from repo root into ``config_dir()`` (``.arka/`` in checkouts)."""
    root = checkout_root()
    state_root = checkout_state_dir()
    if root is None or state_root is None:
        return []

    target = (target or config_dir()).resolve()
    if target != state_root.resolve():
        return []

    moved: list[str] = []
    target.mkdir(parents=True, exist_ok=True)

    for name in _RUNTIME_JSON_FILES:
        _move_if_missing(root / name, target / name, moved=moved)

    for name in _RUNTIME_STATE_FILES:
        _move_if_missing(root / name, target / name, moved=moved)

    for name in _RUNTIME_STATE_DIRS:
        _move_dir_if_missing(root / name, target / name, moved=moved)

    _migrate_hub_runtime(root / "hub", target / "hub", moved=moved)

    return moved


def cache_dir() -> Path:
    if env := os.environ.get("CACHE_DIR", "").strip():
        return Path(env).expanduser().resolve()
    _, user_cache_dir = _platformdirs()
    legacy_cache = Path.home() / ".cache" / "fish-agent"
    if legacy_cache.is_dir() and not os.environ.get("CACHE_DIR"):
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
    migrate_scattered_state()
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
    raw = os.environ.get("STOCK_PROJECT", "").strip()
    if raw:
        configured = Path(raw).expanduser()
        if configured.is_dir():
            return configured.resolve()
    return default


def downloads_dir() -> Path:
    """User Downloads folder (macOS/Linux: ~/Downloads, Windows: %USERPROFILE%\\Downloads)."""
    override = os.environ.get("AIE_DOWNLOADS_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    if sys.platform == "win32":
        profile = os.environ.get("USERPROFILE", "").strip()
        if profile:
            return Path(profile) / "Downloads"
    return Path.home() / "Downloads"


def generated_data_dir() -> Path:
    """Default folder for saved tabular/data exports (view_data, generate_data)."""
    override = os.environ.get("DATA_OUTPUT_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    return Path.home() / "arka-generated"


def load_env_file() -> None:
    from arka.env import load_env

    load_env()