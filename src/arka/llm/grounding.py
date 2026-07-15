"""Deterministic anti-hallucination policy for model-facing requests."""
from __future__ import annotations
import os
import re

LIVE_RE = re.compile(r"(?i)\b(?:latest|current|live|today|real[- ]time|production|actual)\b")
MOCK_RE = re.compile(r"(?i)\b(?:mock|fake|sample|placeholder|dummy)\s+(?:data|api|response|url|values?)\b")

def enabled() -> bool:
    return os.environ.get("ARKA_GROUNDED_MODE", "1").lower() not in {"0", "false", "off", "no"}

def guard(user: str) -> tuple[bool, str]:
    if not enabled():
        return True, "disabled"
    if MOCK_RE.search(user) and not re.search(r"(?i)\b(?:example|illustrat|show|demonstrat)\b", user):
        return False, "mock data is blocked; explicitly request an example or provide a real source"
    return True, "ok"

def instruction(user: str) -> str:
    if not enabled():
        return ""
    live = " Call a configured API/tool and report its source." if LIVE_RE.search(user) else ""
    return ("Grounded mode: never invent URLs, files, APIs, model IDs, or factual values. "
            "Before writing code, inspect Arka's preexisting skills, MCP tools, and integration/library adapters; "
            "reuse and integrate the relevant tool instead of recreating equivalent functionality. "
            "Unless the user explicitly asks for a mock, prototype, placeholder, or example design, "
            "bias toward real data, real API integrations, and production-shaped error handling. "
            "Use symbolic tools and user-provided sources. If a real source is unavailable, say so "
            "instead of fabricating data. Do not return mock data unless explicitly requested." + live)
