"""OpenTelemetry helpers for MCP client connections and tool calls."""

from __future__ import annotations

import os
from typing import Any


def mcp_server_url(server: str = "signoz") -> str:
    if server == "signoz":
        base = os.environ.get("SIGNOZ_MCP_URL", "http://localhost:8000").strip().rstrip("/")
        return f"{base}/mcp"
    raw = os.environ.get(f"MCP_{server.upper()}_URL", "").strip().rstrip("/")
    if raw:
        return raw if raw.endswith("/mcp") else f"{raw}/mcp"
    return ""


def mcp_api_key(server: str = "signoz") -> str:
    for key in (
        os.environ.get("SIGNOZ_API_KEY", "").strip(),
        os.environ.get("SIGNOZ_ACCESS_TOKEN", "").strip(),
        os.environ.get(f"MCP_{server.upper()}_API_KEY", "").strip(),
    ):
        if key:
            return key
    return ""


def mcp_connect_attrs(
    *,
    server: str,
    transport: str = "http",
    url: str = "",
) -> dict[str, Any]:
    endpoint = url or mcp_server_url(server)
    attrs: dict[str, Any] = {
        "arka.mcp.server": server,
        "arka.mcp.transport": transport,
        "http.method": "POST",
        "http.request.method": "POST",
    }
    if endpoint:
        attrs["http.url"] = endpoint
        attrs["url.full"] = endpoint
    return attrs


def mcp_tool_attrs(
    *,
    server: str,
    tool_name: str,
    transport: str = "http",
) -> dict[str, Any]:
    return {
        "arka.mcp.server": server,
        "arka.mcp.transport": transport,
        "arka.mcp.tool_name": tool_name[:200],
    }


def record_mcp_request(
    *,
    server: str,
    operation: str,
    success: bool = True,
    tool_name: str = "",
) -> None:
    try:
        from arka.telemetry.metrics import record_mcp_op

        record_mcp_op(server=server, operation=operation, success=success, tool_name=tool_name)
    except ImportError:
        pass


def emit_mcp_log(
    message: str,
    *,
    level: str = "info",
    server: str = "",
    operation: str = "",
    tool_name: str = "",
    success: bool | None = None,
) -> None:
    try:
        from arka.telemetry.logs import emit_log

        attrs: dict[str, Any] = {"arka.component": "mcp"}
        if server:
            attrs["arka.mcp.server"] = server
        if operation:
            attrs["arka.mcp.operation"] = operation
        if tool_name:
            attrs["arka.mcp.tool_name"] = tool_name
        if success is not None:
            attrs["arka.mcp.success"] = success
        emit_log(message, level=level, attributes=attrs)
    except ImportError:
        pass


def mcp_status_lines() -> list[tuple[str, str]]:
    from arka.telemetry.signoz_setup import signoz_mcp_status

    base = os.environ.get("SIGNOZ_MCP_URL", "http://localhost:8000").strip().rstrip("/")
    key_set = bool(mcp_api_key("signoz"))
    return [
        ("mcp_signoz_url", f"{base}/mcp"),
        ("mcp_signoz_api_key", "set" if key_set else "not_set"),
        ("mcp_signoz_livez", signoz_mcp_status(base)),
    ]
