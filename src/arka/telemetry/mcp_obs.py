"""OpenTelemetry helpers for MCP client connections and tool calls."""

from __future__ import annotations

import os
import time
from contextlib import contextmanager
from typing import Any, Iterator


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


def _mcp_server_operation(method: str) -> str:
    return method.replace("/", "_").strip("_") or "request"


def _emit_mcp_server_span(
    *,
    method: str,
    tool_name: str = "",
    success: bool = True,
    duration_ms: float = 0,
    error: str = "",
) -> None:
    operation = _mcp_server_operation(method)
    span_name = "arka.mcp.server.tool" if operation == "tools_call" else f"arka.mcp.server.{operation}"
    attrs: dict[str, Any] = {
        "arka.mcp.server": "arka",
        "arka.mcp.method": method,
        "arka.mcp.role": "server",
        "arka.mcp.transport": "stdio",
    }
    if tool_name:
        attrs.update(mcp_tool_attrs(server="arka", tool_name=tool_name, transport="stdio"))
    if duration_ms > 0:
        attrs["arka.mcp.duration_ms"] = round(duration_ms, 2)
    if error:
        attrs["arka.mcp.error"] = error[:500]

    try:
        from arka.telemetry.tracing import mark_error, mark_ok, set_span_attributes, span

        with span(span_name, attributes=attrs) as current:
            if duration_ms > 0:
                set_span_attributes(current, {"arka.mcp.duration_ms": round(duration_ms, 2)})
            if success:
                mark_ok(current)
            else:
                mark_error(current, error or operation)
    except ImportError:
        pass


def observe_mcp_server_request(
    *,
    method: str,
    tool_name: str = "",
    success: bool = True,
    duration_ms: int = 0,
    error: str = "",
) -> None:
    """Record spans, metrics, and logs for the Arka MCP server (stdio)."""
    server = "arka"
    operation = _mcp_server_operation(method)
    _emit_mcp_server_span(
        method=method,
        tool_name=tool_name,
        success=success,
        duration_ms=float(duration_ms),
        error=error,
    )
    record_mcp_request(
        server=server,
        operation=operation,
        success=success,
        tool_name=tool_name,
    )
    message = f"mcp server {operation}"
    if tool_name:
        message += f" tool={tool_name}"
    if error:
        message += f" error={error[:120]}"
    emit_mcp_log(
        message,
        level="info" if success else "warn",
        server=server,
        operation=operation,
        tool_name=tool_name,
        success=success,
    )


@contextmanager
def trace_mcp_server_tool_call(*, tool_name: str) -> Iterator[Any]:
    """Wrap an MCP tool handler with a live server-side span, metrics, and logs."""
    start = time.perf_counter()
    current: Any = None
    try:
        from arka.telemetry.tracing import duration_ms, mark_error, mark_ok, set_span_attributes, span
    except ImportError:
        yield None
        return

    attrs = mcp_tool_attrs(server="arka", tool_name=tool_name, transport="stdio")
    attrs["arka.mcp.role"] = "server"
    attrs["arka.mcp.method"] = "tools/call"
    with span("arka.mcp.server.tool", attributes=attrs) as span_obj:
        current = span_obj
        try:
            yield span_obj
        except BaseException as exc:
            elapsed = duration_ms(start)
            set_span_attributes(
                span_obj,
                {
                    "arka.mcp.duration_ms": elapsed,
                    "arka.mcp.success": False,
                    "arka.mcp.error": str(exc)[:500],
                },
            )
            mark_error(span_obj, str(exc)[:500], exc=exc if isinstance(exc, Exception) else None)
            record_mcp_request(
                server="arka",
                operation="tools_call",
                success=False,
                tool_name=tool_name,
            )
            emit_mcp_log(
                f"mcp server tools_call tool={tool_name} error={str(exc)[:120]}",
                level="warn",
                server="arka",
                operation="tools_call",
                tool_name=tool_name,
                success=False,
            )
            raise
        else:
            elapsed = duration_ms(start)
            set_span_attributes(
                span_obj,
                {"arka.mcp.duration_ms": elapsed, "arka.mcp.success": True},
            )
            mark_ok(span_obj)
            record_mcp_request(
                server="arka",
                operation="tools_call",
                success=True,
                tool_name=tool_name,
            )
            emit_mcp_log(
                f"mcp server tools_call tool={tool_name}",
                level="info",
                server="arka",
                operation="tools_call",
                tool_name=tool_name,
                success=True,
            )


def mcp_server_log_status() -> dict[str, Any]:
    try:
        from arka.integrations.mcp_logs import mcp_log_path
    except ImportError:
        return {"log_path": "", "log_exists": False, "log_bytes": 0}
    path = mcp_log_path()
    exists = path.is_file()
    return {
        "log_path": str(path),
        "log_exists": exists,
        "log_bytes": path.stat().st_size if exists else 0,
    }


def mcp_status_lines() -> list[tuple[str, str]]:
    from arka.telemetry.signoz_setup import signoz_mcp_status

    base = os.environ.get("SIGNOZ_MCP_URL", "http://localhost:8000").strip().rstrip("/")
    key_set = bool(mcp_api_key("signoz"))
    return [
        ("mcp_signoz_url", f"{base}/mcp"),
        ("mcp_signoz_api_key", "set" if key_set else "not_set"),
        ("mcp_signoz_livez", signoz_mcp_status(base)),
    ]
