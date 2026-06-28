"""Cross-platform paths for Arka (macOS, Windows, Linux)."""

from __future__ import annotations

import os
import shutil
import sys
from pathlib import Path

SCRIPT_NAMES = [
    "arka_agent.py",
    "arka_aie.py",
    "arka_batch_summarize.py",
    "arka_chat.py",
    "arka_compute.py",
    "arka_disk.py",
    "arka_generate_image.py",
    "arka_generate_video.py",
    "arka_hf_bridge.py",
    "arka_llm.py",
    "arka_macro_events.py",
    "arka_market_emotion.py",
    "arka_media.py",
    "arka_media_qa.py",
    "arka_password_vault.py",
    "arka_pdf_rag.py",
    "arka_phone.py",
    "arka_predictions.py",
    "arka_progress.py",
    "arka_remote_server.py",
    "arka_stt_map.py",
    "arka_stock_bridge.py",
    "arka_stock_context_worker.py",
    "arka_stock_fundamentals.py",
    "arka_competition_funding.py",
    "arka_summarize.py",
    "arka_talents.py",
    "arka_turboquant_install.py",
    "arka_turboquant_rag.py",
    "arka_usage.py",
    "arka_wake.py",
    "arka_whatsapp_inbox.py",
    "arka_youtube.py",
    "arka_youtube_bulk.py",
    "arka_youtube_research.py",
    "edge_speak.py",
    "indic_tts.py",
    "sarvam_speak.py",
    "sarvam_stt.py",
    "web_answer.py",
]

OPTIONAL_FILES = [
    "config.fish",
    "arka_boot.sh",
    "arka_voice_hf.sh",
    "arka_chat_requirements.txt",
    "arka_turboquant_requirements.txt",
    ".env.example",
]


def _platformdirs():
    from platformdirs import user_cache_dir, user_config_dir, user_data_dir

    return user_config_dir, user_cache_dir, user_data_dir


def package_dir() -> Path:
    return Path(__file__).resolve().parent


def bundled_dir() -> Path:
    return package_dir() / "bundled"


def checkout_root() -> Path | None:
    """Project root when running from a git checkout (editable install)."""
    root = package_dir().parent.parent
    if (root / "pyproject.toml").is_file() and (root / "arka_chat.py").is_file():
        return root
    return None


def legacy_fish_home() -> Path | None:
    """Existing Linux install at ~/.config/fish."""
    home = Path.home() / ".config" / "fish"
    if home.is_dir() and (home / "arka_chat.py").is_file():
        return home
    return None


def arka_home() -> Path:
    """Directory containing arka_*.py scripts."""
    if env := os.environ.get("ARKA_HOME", "").strip():
        return Path(env).expanduser().resolve()

    if legacy := legacy_fish_home():
        return legacy

    if checkout := checkout_root():
        return checkout

    _, _, user_data_dir = _platformdirs()
    data = Path(user_data_dir("arka", appauthor=False))
    if (data / "arka_chat.py").is_file():
        return data

    if bundled := bundled_dir():
        if (bundled / "arka_chat.py").is_file():
            return bundled

    return data


def config_dir() -> Path:
    """Config + .env location."""
    if env := os.environ.get("ARKA_CONFIG_DIR", "").strip():
        return Path(env).expanduser().resolve()

    if legacy := legacy_fish_home():
        if (legacy / "config.fish").is_file() or (legacy / ".env").is_file():
            return legacy

    user_config_dir, _, _ = _platformdirs()
    return Path(user_config_dir("arka", appauthor=False))


def cache_dir() -> Path:
    if env := os.environ.get("ARKA_CACHE_DIR", "").strip():
        return Path(env).expanduser().resolve()
    _, user_cache_dir, _ = _platformdirs()
    # Keep legacy cache path when migrating from fish install
    legacy_cache = Path.home() / ".cache" / "fish-agent"
    if legacy_cache.is_dir() and not os.environ.get("ARKA_CACHE_DIR"):
        return legacy_cache
    return Path(user_cache_dir("arka", appauthor=False))


def script_path(name: str) -> Path:
    return arka_home() / name


def env_file() -> Path:
    return config_dir() / ".env"


def python_executable() -> str:
    venv = arka_home() / "venv-arka" / ("Scripts" if sys.platform == "win32" else "bin") / "python"
    if venv.is_file() or (sys.platform == "win32" and venv.with_suffix(".exe").is_file()):
        return str(venv.with_suffix(".exe") if sys.platform == "win32" else venv)
    return sys.executable


def fish_config() -> Path | None:
    for candidate in (config_dir() / "config.fish", Path.home() / ".config" / "fish" / "config.fish"):
        if candidate.is_file():
            return candidate
    return None


def sync_scripts_to(target: Path, source: Path | None = None) -> list[str]:
    """Copy script bundle into target dir. Returns list of copied filenames."""
    source = source or checkout_root() or bundled_dir()
    if not source.is_dir():
        return []

    target.mkdir(parents=True, exist_ok=True)
    copied: list[str] = []
    for name in SCRIPT_NAMES + OPTIONAL_FILES:
        src = source / name
        if not src.is_file():
            continue
        dst = target / name
        if not dst.exists() or src.stat().st_mtime > dst.stat().st_mtime:
            shutil.copy2(src, dst)
            copied.append(name)
    return copied


def ensure_layout() -> Path:
    """Create config/cache dirs and sync scripts if needed."""
    config_dir().mkdir(parents=True, exist_ok=True)
    cache_dir().mkdir(parents=True, exist_ok=True)

    home = arka_home()
    if not (home / "arka_chat.py").is_file():
        source = checkout_root() or bundled_dir()
        if source.is_dir():
            sync_scripts_to(home, source)

    example = config_dir() / ".env.example"
    if not example.is_file():
        for src in (checkout_root(), bundled_dir(), config_dir()):
            if src and (src / ".env.example").is_file():
                shutil.copy2(src / ".env.example", example)
                break

    env = env_file()
    if not env.is_file() and example.is_file():
        shutil.copy2(example, env)

    return home
