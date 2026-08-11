#!/usr/bin/env python3
"""Emit realistic Arka agent logs into SigNoz for UI screenshots (no demo wording)."""
from __future__ import annotations

import os
import sys
import time

REPO = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
if REPO not in sys.path:
    sys.path.insert(0, REPO)
sys.path.insert(0, os.path.join(REPO, "src"))


def _require_logs() -> bool:
    os.environ.setdefault("OTEL_TRACES_ENABLED", "1")
    os.environ.setdefault("OTEL_LOGS_ENABLED", "1")
    os.environ.setdefault("SIGNOZ_ENDPOINT", "http://localhost:4318")
    try:
        from arka.telemetry.logs import logs_enabled, logs_status
        from arka.telemetry import spans_enabled
    except ImportError:
        print("Install observability extras: pip install 'arka-agent[observability]'", file=sys.stderr)
        return False
    if not spans_enabled() or not logs_enabled():
        print("Enable OTEL logs:", logs_status(), file=sys.stderr)
        return False
    return True


def seed_logs() -> int:
    if not _require_logs():
        return 1

    from arka.telemetry import span
    from arka.telemetry.logs import emit_log, shutdown_logs
    from arka.telemetry.tracing import shutdown_tracing

    entries: list[tuple[str, str, dict[str, object], str | None]] = [
        (
            "arka.request",
            "info",
            "goal started: count lines in README.md",
            {"arka.command": "goal count lines in README.md", "arka.track": "01"},
            None,
        ),
        (
            "arka.route",
            "info",
            "symbolic route matched goal in 1.1ms",
            {"arka.route.decision": "symbolic", "arka.route.latency_ms": 1.1},
            None,
        ),
        (
            "arka.agent.goal.step",
            "info",
            "planning step 1 — run wc on README.md",
            {"arka.agent.step": 1, "arka.agent.status": "continue"},
            None,
        ),
        (
            "arka.llm.attempt",
            "info",
            "llm ok gemini/gemini-2.0-flash in=842 out=128 ttft=380ms",
            {
                "gen_ai.provider.name": "gemini",
                "gen_ai.request.model": "gemini-2.0-flash",
                "gen_ai.usage.input_tokens": 842,
                "gen_ai.usage.output_tokens": 128,
                "arka.event": "llm.completion",
            },
            None,
        ),
        (
            "arka.llm.attempt",
            "warn",
            "gemini quota warning — failover chain armed",
            {
                "gen_ai.provider.name": "gemini",
                "gen_ai.request.model": "gemini-2.0-flash",
                "http.status_code": 429,
                "arka.event": "llm.quota",
            },
            None,
        ),
        (
            "arka.llm.attempt",
            "error",
            "llm attempt failed HTTP 429 — failing over to groq",
            {
                "gen_ai.provider.name": "gemini",
                "gen_ai.request.model": "gemini-2.0-flash",
                "http.status_code": 429,
                "arka.event": "llm.failover",
            },
            None,
        ),
        (
            "arka.llm.attempt",
            "info",
            "llm ok groq/llama-3.3-70b-versatile in=842 out=131 ttft=920ms",
            {
                "gen_ai.provider.name": "groq",
                "gen_ai.request.model": "llama-3.3-70b-versatile",
                "gen_ai.usage.input_tokens": 842,
                "gen_ai.usage.output_tokens": 131,
                "arka.event": "llm.completion",
            },
            None,
        ),
        (
            "arka.supermemory.vector_lookup",
            "info",
            "supermemory recall 3 hits for session context",
            {"arka.supermemory.hits": 3, "arka.event": "memory.recall"},
            None,
        ),
        (
            "arka.tool.shell",
            "info",
            "shell ok wc -l README.md exit=0",
            {"arka.tool.command": "wc -l README.md", "arka.tool.exit_code": 0, "arka.event": "tool.shell"},
            None,
        ),
        (
            "arka.tool.shell",
            "error",
            "shell failed: git: command not found",
            {"arka.tool.command": "git status", "arka.tool.exit_code": 127, "arka.event": "tool.shell"},
            None,
        ),
        (
            "arka.agent.goal.step",
            "warn",
            "agent.self_heal — retrying after shell failure",
            {"arka.agent.step": 2, "arka.event": "agent.self_heal"},
            None,
        ),
        (
            "arka.mcp.call",
            "info",
            "mcp signoz_ask completed in 240ms",
            {"arka.mcp.server": "signoz", "arka.mcp.tool": "signoz_ask", "arka.mcp.duration_ms": 240},
            None,
        ),
    ]

    base_attrs = {"service.name": "arka", "deployment.environment": "local"}

    for span_name, level, message, attrs, exc in entries:
        merged = {**base_attrs, **attrs}
        with span(span_name, attributes={k: v for k, v in merged.items() if not k.startswith("service.")}):
            emit_log(message, level=level, attributes=merged)
            if exc:
                pass
        time.sleep(0.05)

    shutdown_logs()
    shutdown_tracing()
    print(f"Seeded {len(entries)} log records for service.name=arka")
    return 0


if __name__ == "__main__":
    raise SystemExit(seed_logs())
