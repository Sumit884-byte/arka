#!/usr/bin/env python3
"""Auto-copy primary selection to clipboard before paste (Linux X11)."""

from __future__ import annotations

import shutil
import subprocess
import time

from _common import host_platform, log, poll_interval


def _read_primary() -> str:
    for cmd in (["xclip", "-selection", "primary", "-o"], ["xsel", "-p"]):
        if shutil.which(cmd[0]):
            proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
            if proc.returncode == 0:
                return proc.stdout
    return ""


def _write_clipboard(text: str) -> bool:
    if not text:
        return False
    if shutil.which("xclip"):
        proc = subprocess.run(
            ["xclip", "-selection", "clipboard"],
            input=text,
            text=True,
            capture_output=True,
            check=False,
        )
        return proc.returncode == 0
    if shutil.which("wl-copy"):
        proc = subprocess.run(
            ["wl-copy"],
            input=text,
            text=True,
            capture_output=True,
            check=False,
        )
        return proc.returncode == 0
    return False


def _linux_loop() -> int:
    if not (shutil.which("xclip") or shutil.which("xsel")):
        log("aie/copy: install xclip or xsel (Linux) or set ARKA_AIE_DIR to external scripts")
        return 1
    last_clip = subprocess.run(
        ["xclip", "-selection", "clipboard", "-o"] if shutil.which("xclip") else ["true"],
        capture_output=True,
        text=True,
        check=False,
    ).stdout
    log("aie/copy: syncing primary selection → clipboard (Ctrl+C to stop)")
    try:
        while True:
            primary = _read_primary()
            if primary and primary != last_clip:
                if _write_clipboard(primary):
                    last_clip = primary
                    log("aie/copy: copied selection to clipboard")
            time.sleep(poll_interval())
    except KeyboardInterrupt:
        log("aie/copy: stopped")
        return 0


def main() -> int:
    plat = host_platform()
    if plat == "linux":
        return _linux_loop()
    log(f"aie/copy: not supported on {plat} (Linux X11/Wayland only)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
