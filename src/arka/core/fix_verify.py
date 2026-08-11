#!/usr/bin/env python3
"""Bias agents to verify every fix and iterate until verification passes."""

from __future__ import annotations

import os

_COMPACT_RULE = (
    "After any fix, run relevant verification (tests, CLI repro, log check, etc.). "
    "If verification fails, iterate — do not mark done or say 'fixed' until it passes. "
    "Report what was verified and how."
)


def _enabled() -> bool:
    return os.environ.get("FIX_VERIFY_BIAS", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def compact_rule() -> str:
    if not _enabled():
        return ""
    return _COMPACT_RULE


def context_for(goal: str = "", *, limit_chars: int = 800) -> str:
    if not _enabled():
        return ""
    text = _COMPACT_RULE
    if len(text) > limit_chars:
        text = text[:limit_chars].rstrip() + "…"
    return text
