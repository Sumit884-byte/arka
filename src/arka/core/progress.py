#!/usr/bin/env python3
"""Terminal progress bars for long-running Arka tasks."""

from __future__ import annotations

import os
import sys
import threading
import time


def progress_enabled() -> bool:
    if os.environ.get("NO_PROGRESS", "").strip().lower() in {"1", "true", "yes"}:
        return False
    if os.environ.get("PROGRESS", "1").strip().lower() in {"0", "false", "no"}:
        return False
    stream = sys.stderr
    return bool(getattr(stream, "isatty", lambda: False)())


class ProgressBar:
    WIDTH = 24

    def __init__(self, label: str, total: int = 100, *, unit: str = "done"):
        self.phase = label
        self.item_label = ""
        self.total = max(int(total), 1)
        self.current = 0
        self.unit = unit
        self.enabled = progress_enabled()
        self._last_draw = 0.0

    def clear(self) -> None:
        if not self.enabled:
            return
        sys.stderr.write("\r\033[2K")
        sys.stderr.flush()

    def set(self, current: int, total: int | None = None, label: str | None = None) -> None:
        if label is not None:
            self.item_label = label
        if total is not None:
            self.total = max(int(total), 1)
        self.current = max(0, min(int(current), self.total))
        self._render()

    def advance(self, n: int = 1, label: str | None = None) -> None:
        self.set(self.current + n, label=label)

    def fraction(self, frac: float, label: str | None = None) -> None:
        self.set(int(round(max(0.0, min(1.0, frac)) * self.total)), label=label)

    def done(self, label: str | None = None) -> None:
        if not self.enabled:
            return
        if label:
            self.phase = label
        self.current = self.total
        self._render(force=True)
        self.clear()
        sys.stderr.write(f"  ✓ {self.phase} ({self.total}/{self.total})\n")
        sys.stderr.flush()

    def _render(self, force: bool = False) -> None:
        if not self.enabled:
            return
        now = time.monotonic()
        if not force and now - self._last_draw < 0.08:
            return
        self._last_draw = now
        pct = int(self.current * 100 / self.total)
        filled = int(self.WIDTH * pct / 100)
        bar = "█" * filled + "░" * (self.WIDTH - filled)
        count = f"{self.current}/{self.total} {self.unit}"
        tail = self.item_label[:34] if self.item_label else ""
        head = f"{self.phase} " if self.phase else ""
        sys.stderr.write(f"\r\033[2K  {head}[{bar}] {count} · {pct:3d}%  {tail}")
        sys.stderr.flush()


def progress_clear() -> None:
    """Erase the active progress line before normal stderr output."""
    if progress_enabled():
        sys.stderr.write("\r\033[2K")
        sys.stderr.flush()


def progress_note(msg: str) -> None:
    """Print a status line without leaving progress-bar residue."""
    progress_clear()
    print(msg, file=sys.stderr)


def run_spinner(label: str, fn, *args, **kwargs):
    if not progress_enabled():
        return fn(*args, **kwargs)

    done = threading.Event()
    result: list = []
    error: list = []

    def worker() -> None:
        try:
            result.append(fn(*args, **kwargs))
        except Exception as exc:  # noqa: BLE001
            error.append(exc)
        finally:
            done.set()

    def spin() -> None:
        chars = "⠋⠙⠹⠸⠼⠴⠦⠧⠇⠏"
        i = 0
        start = time.monotonic()
        while not done.wait(0.12):
            elapsed = int(time.monotonic() - start)
            ch = chars[i % len(chars)]
            sys.stderr.write(f"\r  {label} {ch} {elapsed}s…   ")
            sys.stderr.flush()
            i += 1

    t = threading.Thread(target=spin, daemon=True)
    w = threading.Thread(target=worker, daemon=True)
    t.start()
    w.start()
    w.join()
    done.set()
    t.join(timeout=0.5)
    sys.stderr.write("\r" + " " * 72 + "\r")
    sys.stderr.flush()
    if error:
        raise error[0]
    return result[0]
