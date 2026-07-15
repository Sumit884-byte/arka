"""Best-effort desktop notifications for long-running Arka workflows."""
from __future__ import annotations

import os
import platform
import subprocess


def notify(title: str, message: str) -> None:
    if os.environ.get("ARKA_NOTIFICATIONS", "1").strip().lower() in {"0", "false", "no", "off"}:
        return
    title = title.replace('"', "'")[:80]
    message = message.replace('"', "'")[:180]
    try:
        system = platform.system()
        if system == "Darwin":
            subprocess.run(["osascript", "-e", f'display notification "{message}" with title "{title}"'], check=False, timeout=2)
        elif system == "Linux":
            subprocess.run(["notify-send", title, message], check=False, timeout=2)
        else:
            print(f"Arka notification: {title}: {message}")
    except (OSError, subprocess.SubprocessError):
        print(f"Arka notification: {title}: {message}")
