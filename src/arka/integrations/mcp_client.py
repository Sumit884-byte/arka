"""HTTP MCP client with OpenTelemetry spans for connect, list_tools, and call_tool."""

from __future__ import annotations

import json
import os
import time
import urllib.error
import urllib.request
from dataclasses import dataclass, field
from typing import Any

from arka.telemetry.mcp_obs import (
    mcp_api_key,
    mcp_connect_attrs,
    mcp_server_url,
    mcp_tool_attrs,
    record_mcp_request,
)

MCP_PROTOCOL_VERSION = "2024-11-05"
DEFAULT_TIMEOUT = 30


@dataclass
class McpTool:
    name: str
    description: str = ""
    input_schema: dict[str, Any] = field(default_factory=dict)


@dataclass
class McpHttpClient:
    server: str = "signoz"
    url: str = ""
    api_key: str = ""
    headers: dict[str, str] = field(default_factory=dict)
    timeout: float = DEFAULT_TIMEOUT
    session_id: str = ""
    _request_id: int = 0

    def __post_init__(self) -> None:
        if not self.url:
            self.url = mcp_server_url(self.server)
        if not self.api_key:
            self.api_key = mcp_api_key(self.server)

    def _next_id(self) -> int:
        self._request_id += 1
        return self._request_id

    def _headers(self, *, include_session: bool = True) -> dict[str, str]:
        headers = {
            "Content-Type": "application/json",
            "Accept": "application/json, text/event-stream",
        }
        if self.headers:
            headers.update(self.headers)
        if self.api_key:
            headers.setdefault("SIGNOZ-API-KEY", self.api_key)
        if include_session and self.session_id:
            headers["Mcp-Session-Id"] = self.session_id
        return headers

    def _rpc(
        self,
        method: str,
        params: dict[str, Any] | None = None,
        *,
        request_id: int | None = None,
        span_name: str = "arka.mcp.request",
        span_attrs: dict[str, Any] | None = None,
    ) -> Any:
        from contextlib import nullcontext

        try:
            from arka.telemetry import mark_error, mark_ok, span
            from arka.telemetry.tracing import duration_ms, set_http_span_attributes, set_timing_attrs
        except ImportError:
            span = None  # type: ignore[assignment,misc]
            nullcontext = __import__("contextlib").nullcontext
            mark_ok = mark_error = set_http_span_attributes = set_timing_attrs = duration_ms = None  # type: ignore

        payload: dict[str, Any] = {"jsonrpc": "2.0", "method": method}
        if request_id is not None:
            payload["id"] = request_id
        if params is not None:
            payload["params"] = params

        attrs = dict(span_attrs or {})
        attrs.setdefault("arka.mcp.method", method)
        attrs.setdefault("arka.mcp.server", self.server)

        span_ctx = (
            span(span_name, attributes=attrs)
            if span is not None
            else nullcontext()
        )
        start = time.perf_counter()
        with span_ctx as current:
            data = json.dumps(payload).encode("utf-8")
            request = urllib.request.Request(
                self.url,
                data=data,
                headers=self._headers(include_session=method != "initialize"),
                method="POST",
            )
            try:
                with urllib.request.urlopen(request, timeout=self.timeout) as resp:
                    session = resp.headers.get("Mcp-Session-Id") or resp.headers.get("mcp-session-id")
                    if session:
                        self.session_id = session.strip()
                    raw = resp.read()
                    if isinstance(raw, bytes):
                        raw = raw.decode("utf-8", errors="replace")
                    else:
                        raw = str(raw or "")
                    status = getattr(resp, "status", 200)
                    if current is not None and set_http_span_attributes is not None:
                        set_http_span_attributes(
                            current,
                            method="POST",
                            status_code=status,
                            url=self.url,
                        )
                    body = _parse_mcp_body(raw)
                    if "error" in body:
                        message = str(body["error"].get("message", body["error"]))
                        if current is not None and mark_error is not None:
                            mark_error(current, message[:500])
                            current.set_attribute("arka.mcp.error", message[:500])
                        raise RuntimeError(message)
                    if current is not None:
                        if set_timing_attrs is not None and duration_ms is not None:
                            set_timing_attrs(current, start=start, end=time.perf_counter())
                        if mark_ok is not None:
                            mark_ok(current)
                    return body.get("result")
            except urllib.error.HTTPError as exc:
                detail = exc.read().decode("utf-8", errors="replace").strip() or str(exc)
                if current is not None:
                    if set_http_span_attributes is not None:
                        set_http_span_attributes(
                            current,
                            method="POST",
                            status_code=exc.code,
                            url=self.url,
                        )
                    if mark_error is not None:
                        mark_error(current, detail[:500])
                    current.set_attribute("arka.mcp.error", detail[:500])
                raise RuntimeError(f"MCP HTTP {exc.code}: {detail}") from exc
            except urllib.error.URLError as exc:
                if current is not None and mark_error is not None:
                    mark_error(current, str(exc)[:500], exc=exc)
                raise RuntimeError(f"MCP unreachable: {exc}") from exc

    def connect(self) -> dict[str, Any]:
        from contextlib import nullcontext

        try:
            from arka.telemetry import mark_error, mark_ok, span
            from arka.telemetry.tracing import duration_ms, set_timing_attrs
        except ImportError:
            span = None  # type: ignore[assignment,misc]
            nullcontext = __import__("contextlib").nullcontext
            mark_ok = mark_error = set_timing_attrs = duration_ms = None  # type: ignore

        attrs = mcp_connect_attrs(server=self.server, transport="http", url=self.url)
        span_ctx = span("arka.mcp.connect", attributes=attrs) if span is not None else nullcontext()
        start = time.perf_counter()
        with span_ctx as current:
            try:
                result = self._rpc(
                    "initialize",
                    {
                        "protocolVersion": MCP_PROTOCOL_VERSION,
                        "capabilities": {},
                        "clientInfo": {"name": "arka", "version": "0.1.0"},
                    },
                    request_id=self._next_id(),
                    span_name="arka.mcp.initialize",
                )
                self._rpc(
                    "notifications/initialized",
                    {},
                    request_id=None,
                    span_name="arka.mcp.initialized",
                )
                if current is not None:
                    if set_timing_attrs is not None and duration_ms is not None:
                        elapsed = duration_ms(start, time.perf_counter())
                        current.set_attribute("arka.mcp.connect_ms", elapsed)
                    if mark_ok is not None:
                        mark_ok(current)
                    if self.session_id:
                        current.set_attribute("arka.mcp.session_id", self.session_id[:80])
                record_mcp_request(server=self.server, operation="connect", success=True)
                return result if isinstance(result, dict) else {}
            except Exception as exc:
                record_mcp_request(server=self.server, operation="connect", success=False)
                if current is not None and mark_error is not None:
                    mark_error(current, str(exc)[:500])
                raise

    def list_tools(self) -> list[McpTool]:
        from contextlib import nullcontext

        try:
            from arka.telemetry import mark_error, mark_ok, span
            from arka.telemetry.tracing import duration_ms, set_timing_attrs
        except ImportError:
            span = None  # type: ignore[assignment,misc]
            nullcontext = __import__("contextlib").nullcontext
            mark_ok = mark_error = set_timing_attrs = duration_ms = None  # type: ignore

        attrs = mcp_connect_attrs(server=self.server, transport="http", url=self.url)
        span_ctx = span("arka.mcp.list_tools", attributes=attrs) if span is not None else nullcontext()
        start = time.perf_counter()
        with span_ctx as current:
            try:
                if not self.session_id:
                    self.connect()
                result = self._rpc(
                    "tools/list",
                    {},
                    request_id=self._next_id(),
                    span_name="arka.mcp.tools_list",
                )
                tools = _parse_tools(result)
                if current is not None:
                    current.set_attribute("arka.mcp.tool_count", len(tools))
                    if set_timing_attrs is not None and duration_ms is not None:
                        current.set_attribute("arka.mcp.duration_ms", duration_ms(start, time.perf_counter()))
                    if mark_ok is not None:
                        mark_ok(current)
                record_mcp_request(server=self.server, operation="list_tools", success=True)
                return tools
            except Exception as exc:
                record_mcp_request(server=self.server, operation="list_tools", success=False)
                if current is not None and mark_error is not None:
                    mark_error(current, str(exc)[:500])
                raise

    def call_tool(self, name: str, arguments: dict[str, Any] | None = None) -> Any:
        from contextlib import nullcontext

        try:
            from arka.telemetry import mark_error, mark_ok, span
            from arka.telemetry.tracing import duration_ms, set_timing_attrs
        except ImportError:
            span = None  # type: ignore[assignment,misc]
            nullcontext = __import__("contextlib").nullcontext
            mark_ok = mark_error = set_timing_attrs = duration_ms = None  # type: ignore

        tool_name = name.strip()
        attrs = mcp_tool_attrs(server=self.server, tool_name=tool_name, transport="http")
        if arguments:
            attrs["arka.mcp.args_keys"] = ",".join(sorted(arguments.keys())[:20])[:200]

        span_ctx = span("arka.mcp.call_tool", attributes=attrs) if span is not None else nullcontext()
        start = time.perf_counter()
        with span_ctx as current:
            try:
                if not self.session_id:
                    self.connect()
                result = self._rpc(
                    "tools/call",
                    {"name": tool_name, "arguments": arguments or {}},
                    request_id=self._next_id(),
                    span_name="arka.tool.mcp",
                    span_attrs=attrs,
                )
                text = _tool_result_text(result)
                if current is not None:
                    current.set_attribute("arka.mcp.result_chars", len(text))
                    if set_timing_attrs is not None and duration_ms is not None:
                        current.set_attribute("arka.mcp.duration_ms", duration_ms(start, time.perf_counter()))
                    if mark_ok is not None:
                        mark_ok(current)
                record_mcp_request(
                    server=self.server,
                    operation="call_tool",
                    success=True,
                    tool_name=tool_name,
                )
                return result
            except Exception as exc:
                record_mcp_request(
                    server=self.server,
                    operation="call_tool",
                    success=False,
                    tool_name=tool_name,
                )
                if current is not None and mark_error is not None:
                    mark_error(current, str(exc)[:500])
                raise


    def close(self) -> None:
        """No persistent HTTP connection to tear down."""
        self.session_id = ""


def _parse_mcp_body(raw: str) -> dict[str, Any]:
    text = (raw or "").strip()
    if not text:
        return {}
    if text.startswith("{"):
        parsed = json.loads(text)
        return parsed if isinstance(parsed, dict) else {"result": parsed}
    # SSE fallback: event: message\ndata: {...}
    for line in text.splitlines():
        if line.startswith("data:"):
            payload = line[5:].strip()
            if payload:
                parsed = json.loads(payload)
                return parsed if isinstance(parsed, dict) else {"result": parsed}
    raise RuntimeError(f"Unrecognized MCP response: {text[:200]}")


def _parse_tools(result: Any) -> list[McpTool]:
    if not isinstance(result, dict):
        return []
    items = result.get("tools") or []
    tools: list[McpTool] = []
    for item in items:
        if not isinstance(item, dict):
            continue
        name = str(item.get("name", "")).strip()
        if not name:
            continue
        schema = item.get("inputSchema") or item.get("input_schema") or {}
        tools.append(
            McpTool(
                name=name,
                description=str(item.get("description", ""))[:500],
                input_schema=schema if isinstance(schema, dict) else {},
            )
        )
    return tools


def _tool_result_text(result: Any) -> str:
    if not isinstance(result, dict):
        return str(result)
    content = result.get("content") or []
    chunks: list[str] = []
    for item in content:
        if isinstance(item, dict) and item.get("type") == "text":
            chunks.append(str(item.get("text", "")))
    if chunks:
        return "\n".join(chunks)
    if "structuredContent" in result:
        return json.dumps(result["structuredContent"], ensure_ascii=False)
    return json.dumps(result, ensure_ascii=False)


def mcp_self_heal_enabled() -> bool:
    raw = os.environ.get("ARKA_MCP_SELF_HEAL", os.environ.get("MCP_SELF_HEAL", "")).strip().lower()
    return raw in {"1", "true", "yes", "on"}


def signoz_mcp_client() -> McpHttpClient:
    return McpHttpClient(server="signoz")


def signoz_mcp_ping() -> dict[str, Any]:
    client = signoz_mcp_client()
    info = client.connect()
    tools = client.list_tools()
    return {
        "server": client.server,
        "url": client.url,
        "session_id": client.session_id,
        "server_info": info.get("serverInfo") if isinstance(info, dict) else info,
        "tool_count": len(tools),
        "tools": [tool.name for tool in tools[:50]],
    }
