"""SigNoz MCP helpers — traced queries for SRE Sidekick / goal self-heal."""

from __future__ import annotations

import json
import os
from typing import Any

from arka.integrations.mcp_client import (
    McpHttpClient,
    _tool_result_text,
    mcp_self_heal_enabled,
    signoz_mcp_client,
    signoz_mcp_ping,
)


def signoz_mcp_configured() -> bool:
    from arka.telemetry.mcp_obs import mcp_api_key, mcp_server_url

    return bool(mcp_server_url("signoz")) and (
        bool(mcp_api_key("signoz")) or os.environ.get("SIGNOZ_MCP_SERVER_AUTH", "").strip().lower() in {"1", "true", "yes"}
    )


def query_signoz_mcp(
    tool_name: str,
    arguments: dict[str, Any] | None = None,
    *,
    server: str = "signoz",
) -> str:
    """Call a SigNoz MCP tool and return text content."""
    from arka.telemetry import span

    query_preview = json.dumps({"tool": tool_name, "args": arguments or {}}, ensure_ascii=False)[:200]
    with span(
        "arka.tool.signoz_mcp",
        attributes={
            "arka.mcp.server": server,
            "arka.mcp.tool_name": tool_name[:200],
            "arka.mcp.query": query_preview,
        },
    ) as current:
        client = signoz_mcp_client() if server == "signoz" else McpHttpClient(server=server)
        result = client.call_tool(tool_name, arguments)
        text = _tool_result_text(result)
        current.set_attribute("arka.mcp.result_chars", len(text))
        return text


def diagnose_failed_step(
    *,
    step: int,
    exit_code: int,
    command: str,
) -> str:
    """Best-effort SigNoz MCP lookup after a failed goal step."""
    if not mcp_self_heal_enabled():
        return ""
    try:
        client = signoz_mcp_client()
        tools = {tool.name for tool in client.list_tools()}
    except Exception:
        return ""

    prompt = (
        f"Recent arka agent failures: step {step}, exit {exit_code}, command={command[:120]!r}. "
        "Summarize relevant error spans or logs in 3 bullet points."
    )

    for candidate, args in (
        (
            "signoz_search_traces",
            {
                "serviceName": os.environ.get("OTEL_SERVICE_NAME", "arka"),
                "limit": 5,
            },
        ),
        ("signoz_query_traces", {"query": "service.name = arka AND status = error", "limit": 5}),
        ("signoz_ask", {"question": prompt}),
    ):
        if candidate not in tools:
            continue
        try:
            return query_signoz_mcp(candidate, args)
        except Exception:
            continue
    return ""


__all__ = [
    "diagnose_failed_step",
    "query_signoz_mcp",
    "signoz_mcp_client",
    "signoz_mcp_configured",
    "signoz_mcp_ping",
]
