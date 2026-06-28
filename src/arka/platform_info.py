"""Platform detection and capability flags."""

from __future__ import annotations

import shutil
import sys


def system() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform


def has_fish() -> bool:
    return shutil.which("fish") is not None


def has_full_fish_agent() -> bool:
    from arka.paths import fish_config

    return has_fish() and fish_config() is not None
