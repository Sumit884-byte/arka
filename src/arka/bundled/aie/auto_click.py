#!/usr/bin/env python3
"""Auto-click when the cursor changes to a busy/loading shape (Linux X11 via xdotool)."""

from __future__ import annotations

import shutil
import subprocess
import time

from _common import host_platform, log, poll_interval

# xdotool cursor names that often indicate loading / wait state
BUSY_CURSORS = {
    "watch",
    "wait",
    "progress",
    "left_ptr_watch",
    "xterm",
}


def _linux_loop() -> int:
    if not shutil.which("xdotool"):
        log("aie/click: install xdotool (Linux X11) or set ARKA_AIE_DIR to external scripts")
        return 1
    if not shutil.which("xprop"):
        log("aie/click: xprop required on Linux")
        return 1
    last = ""
    log("aie/click: monitoring cursor shape (Ctrl+C to stop)")
    try:
        while True:
            proc = subprocess.run(
                ["xdotool", "getmouselocation", "--shell"],
                capture_output=True,
                text=True,
                check=False,
            )
            x = y = None
            for line in proc.stdout.splitlines():
                if line.startswith("X="):
                    x = line.split("=", 1)[1].strip()
                elif line.startswith("Y="):
                    y = line.split("=", 1)[1].strip()
            if x is not None and y is not None:
                cur = subprocess.run(
                    ["xprop", "-root", "cursor"],
                    capture_output=True,
                    text=True,
                    check=False,
                )
                shape = cur.stdout.strip().lower()
                if shape != last:
                    last = shape
                    if any(name in shape for name in BUSY_CURSORS):
                        subprocess.run(["xdotool", "click", "1"], check=False)
                        log("aie/click: busy cursor detected — clicked")
            time.sleep(poll_interval())
    except KeyboardInterrupt:
        log("aie/click: stopped")
        return 0


def main() -> int:
    plat = host_platform()
    if plat == "linux":
        return _linux_loop()
    log(f"aie/click: not supported on {plat} (Linux + xdotool only)")
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
