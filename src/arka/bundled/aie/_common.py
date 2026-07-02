"""Shared helpers for bundled AIE automation scripts."""

from __future__ import annotations

import os
import sys
import time
from pathlib import Path


def host_platform() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform


def downloads_dir() -> Path:
    override = os.environ.get("AIE_DOWNLOADS_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return Path.home() / "Downloads"


def watch_dir() -> Path:
    override = os.environ.get("AIE_WATCH_DIR", "").strip()
    if override:
        return Path(override).expanduser()
    return downloads_dir()


def poll_interval() -> float:
    try:
        return max(0.5, float(os.environ.get("AIE_POLL_SECONDS", "2")))
    except ValueError:
        return 2.0


def log(msg: str) -> None:
    print(msg, flush=True)


def run_forever(name: str, loop) -> int:
    log(f"aie/{name}: watching {watch_dir()} (Ctrl+C to stop)")
    try:
        while True:
            loop()
            time.sleep(poll_interval())
    except KeyboardInterrupt:
        log(f"aie/{name}: stopped")
        return 0
