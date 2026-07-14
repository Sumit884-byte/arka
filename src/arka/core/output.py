#!/usr/bin/env python3
"""User-facing terminal output — clean by default, verbose in debug mode."""

from __future__ import annotations

import re
import sys


def _debug_enabled() -> bool:
    try:
        from arka.core.mode import is_debug_mode

        return is_debug_mode()
    except ImportError:
        return False


def user_msg(msg: str, *, stream=None) -> None:
    """Always print a user-facing status line."""
    print(msg, file=stream or sys.stderr)


def debug_msg(msg: str, *, stream=None) -> None:
    """Print technical detail only in debug mode."""
    if _debug_enabled():
        print(msg, file=stream or sys.stderr)


def summarize_pytest(output: str, *, passed: bool | None = None) -> str:
    """Extract a one-line pytest summary (failure count + first error hint)."""
    text = (output or "").strip()
    if passed is True:
        return "OK"
    if not text:
        return "not run"
    if passed is False:
        pass
    elif re.search(r"\b(\d+)\s+passed\b", text, re.I) and not re.search(r"\b\d+\s+failed\b", text, re.I):
        if "error" not in text.lower()[:200]:
            return "OK"

    if re.search(r"PermissionError.*Operation not permitted", text, re.I) and re.search(
        r"\.cursor|/tmp/|/var/folders/", text
    ):
        return "environment restriction (not a code bug)"

    fail_match = re.search(r"(\d+)\s+failed", text, re.I)
    count = int(fail_match.group(1)) if fail_match else 1
    base = "1 failure" if count == 1 else f"{count} failures"

    detail = ""
    for pattern in (
        r"ImportError:\s*(?:cannot import name\s+)?['\"]?(\w+)",
        r"ModuleNotFoundError:\s*No module named\s+['\"]?(\S+)",
        r"FAILED\s+(\S+)",
        r"ERROR collecting\s+(\S+)",
        r"(\w+Error):\s*(.{0,80})",
    ):
        match = re.search(pattern, text)
        if match:
            if match.lastindex and match.lastindex >= 2:
                detail = match.group(1).strip()
            else:
                detail = match.group(1).strip()
            detail = detail.rstrip(":")
            break

    if detail:
        return f"{base} ({detail})"
    return base


def summarize_goal(goal: str, *, max_len: int = 80) -> str:
    """Short goal summary for normal-mode status (strips internal context blocks)."""
    text = (goal or "").strip()
    for marker in (
        "=== llm.txt",
        "=== Diagnostics",
        "=== git log",
        "=== routing analysis",
        "=== prior attempts",
        "Repository:",
    ):
        idx = text.find(marker)
        if idx > 0:
            text = text[:idx].strip()
    if not text:
        return "(empty goal)"
    if len(text) <= max_len:
        return text
    return text[: max_len - 1] + "…"


def debug_hint() -> str:
    return "Run with `arka mode debug` for full diagnostics."
