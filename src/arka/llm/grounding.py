"""Deterministic anti-hallucination policy for model-facing requests."""
from __future__ import annotations
import os
import re
import json

LIVE_RE = re.compile(r"(?i)\b(?:latest|current|live|today|real[- ]time|production|actual)\b")
MOCK_RE = re.compile(r"(?i)\b(?:mock|fake|sample|placeholder|dummy)\s+(?:data|api|response|url|values?)\b")

def enabled() -> bool:
    return os.environ.get("ARKA_GROUNDED_MODE", "1").lower() not in {"0", "false", "off", "no"}


def production_mode() -> bool:
    return os.environ.get("ARKA_PRODUCTION_MODE", "1").lower() not in {"0", "false", "off", "no"}


def minimize_data(text: str) -> str:
    """Replace embedded JSON/CSV-like values with a schema summary."""
    if os.environ.get("ARKA_DATA_MODE", "schema").lower() in {"full", "raw", "off"}:
        return text
    def replace_json(match: re.Match[str]) -> str:
        try:
            value = json.loads(match.group(0))
        except (TypeError, json.JSONDecodeError):
            return "[structured data redacted; provide schema only]"
        if isinstance(value, dict):
            fields = {key: type(item).__name__ for key, item in value.items()}
            return f"[JSON schema: {json.dumps(fields, sort_keys=True)}]"
        if isinstance(value, list):
            return f"[JSON array: {len(value)} item(s); values redacted]"
        return "[JSON scalar redacted]"
    return re.sub(r"\{[^{}]{1,20000}\}|\[[^\[\]]{1,20000}\]", replace_json, text)

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
    production = (" Default production contract: include authentication/authorization boundaries, secret-safe data handling, "
                  "input and prompt-injection validation, output validation, audit logging, error handling, tests, and observability." if production_mode() else "")
    return ("Grounded mode: never invent URLs, files, APIs, model IDs, or factual values. "
            "Data minimization is enabled: use schemas, field names, types, counts, and constraints instead of trade-secret values. "
            "Before writing code, inspect Arka's preexisting skills, MCP tools, and integration/library adapters; "
            "reuse and integrate the relevant tool instead of recreating equivalent functionality. "
            "Unless the user explicitly asks for a mock, prototype, placeholder, or example design, "
            "bias toward real data, real API integrations, and production-shaped error handling. "
            "Use symbolic tools and user-provided sources. If a real source is unavailable, say so "
            "instead of fabricating data. Do not return mock data unless explicitly requested." + production + live)
