"""One-shot stderr hints when OTLP env is partially configured."""

from __future__ import annotations

import os
import sys
from typing import Any

_hint_emitted = False


def maybe_emit_telemetry_setup_hint() -> None:
    """Suggest enabling traces when endpoint vars are set but export is off."""
    global _hint_emitted
    if _hint_emitted:
        return
    if os.environ.get("ARKA_TELEMETRY_HINT", "1").strip().lower() in {"0", "false", "no", "off"}:
        return

    from arka.telemetry._otlp import telemetry_master_enabled

    if telemetry_master_enabled():
        return

    has_endpoint = bool(
        os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
        or os.environ.get("SIGNOZ_ENDPOINT", "").strip()
    )
    if not has_endpoint:
        return

    _hint_emitted = True
    print(
        "arka telemetry: OTLP endpoint detected but tracing is off — "
        "set OTEL_TRACES_ENABLED=1 then run: arka signoz demo",
        file=sys.stderr,
    )


def reset_telemetry_hints_for_tests() -> None:
    global _hint_emitted
    _hint_emitted = False


def agent_observability_guide() -> dict[str, Any]:
    """Short reference for AI agent observability with Arka + SigNoz."""
    return {
        "title": "AI Agent Observability with Arka + SigNoz",
        "env": {
            "OTEL_TRACES_ENABLED": "1",
            "OTEL_METRICS_ENABLED": "1",
            "OTEL_LOGS_ENABLED": "1",
            "OTEL_SERVICE_NAME": "arka",
            "SIGNOZ_ENDPOINT": "http://localhost:4318",
            "SIGNOZ_UI_URL": "http://localhost:8080",
            "SIGNOZ_MCP_URL": "http://localhost:8000",
            "SIGNOZ_AUTOSTART": "1",
        },
        "commands": [
            "arka signoz setup -y",
            "arka signoz autostart install",
            "arka signoz autostart status",
            "arka signoz status",
            "python -m arka.telemetry.observability_doctor agent",
            "arka signoz demo",
            "arka signoz demo-e2e --synthetic",
            "arka signoz dashboard install --alerts",
            "arka goal -y -n 3 \"count lines in README.md\"",
        ],
        "sigNoz_filters": {
            "e2e_request": "service.name = 'arka' AND name = 'arka.request'",
            "skills": "service.name = 'arka' AND name LIKE 'arka.skill.%'",
            "llm": "service.name = 'arka' AND name = 'arka.llm.attempt'",
            "mcp_server": "service.name = 'arka' AND name = 'arka.mcp.server.tool'",
            "mcp_client": "service.name = 'arka' AND name = 'arka.mcp.call_tool'",
        },
        "docs": "signoz/README.md",
    }


def print_agent_observability_guide(*, file: Any | None = None) -> None:
    guide = agent_observability_guide()
    out = file if file is not None else sys.stderr
    print(f"# {guide['title']}", file=out)
    print("Env (add to ~/.config/arka/.env or repo .env):", file=out)
    for key, value in guide["env"].items():
        print(f"  {key}={value}", file=out)
    print(
        "  # SIGNOZ_AUTOSTART: 0/false/off/no disables login autostart (default on when unset)",
        file=out,
    )
    print("Verify:", file=out)
    for cmd in guide["commands"]:
        print(f"  {cmd}", file=out)
    print("SigNoz trace filters:", file=out)
    for label, expr in guide["sigNoz_filters"].items():
        print(f"  {label}: {expr}", file=out)
    print(f"Full guide: {guide['docs']}", file=out)
