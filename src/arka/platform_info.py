"""Platform detection and capability flags."""

from __future__ import annotations

import json
import shutil
import sys
from pathlib import Path


def _platform_json_path() -> Path:
    from arka.paths import config_dir

    return config_dir() / "platform.json"


def _live_system() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform


def system() -> str:
    path = _platform_json_path()
    if path.is_file():
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            plat = data.get("platform")
            if isinstance(plat, str) and plat:
                return plat
        except (OSError, json.JSONDecodeError):
            pass
    return _live_system()


def ensure_platform_cache(*, force: bool = False) -> dict:
    """Detect platform on first run and write ~/.config/arka/platform.json."""
    path = _platform_json_path()
    if path.is_file() and not force:
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("platform"):
                return data
        except (OSError, json.JSONDecodeError):
            pass

    script = Path(__file__).resolve().parent / "core" / "platform.py"
    if script.is_file():
        import subprocess

        cmd = [sys.executable, str(script), "detect"]
        if force:
            cmd.append("--force")
        subprocess.run(cmd, check=False)

    if path.is_file():
        return json.loads(path.read_text(encoding="utf-8"))
    return {"platform": _live_system()}


def has_fish() -> bool:
    return shutil.which("fish") is not None


def has_full_fish_agent() -> bool:
    """True when fish is installed and bundled (or user) config.fish is present — all platforms."""
    from arka.paths import fish_config

    return has_fish() and fish_config() is not None


def skill_mode() -> str:
    """'full' (70+ skills via bundled config.fish) or 'portable' (Python fallbacks only)."""
    return "full" if has_full_fish_agent() else "portable"


def fish_install_hint() -> str:
    s = system()
    if s == "macos":
        return "brew install fish"
    if s == "windows":
        return "scoop install fish  (or: winget install fishshell)"
    if s == "linux":
        return "sudo apt install fish  (or your distro package manager)"
    return "install fish shell from https://fishshell.com"
