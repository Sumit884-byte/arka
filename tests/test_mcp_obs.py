"""Tests for MCP client observability."""

from __future__ import annotations

import json
from contextlib import contextmanager
from unittest.mock import MagicMock, patch


def test_mcp_connect_attrs():
    from arka.telemetry.mcp_obs import mcp_connect_attrs, mcp_tool_attrs

    attrs = mcp_connect_attrs(server="signoz", transport="http", url="http://localhost:8000/mcp")
    assert attrs["arka.mcp.server"] == "signoz"
    assert attrs["arka.mcp.transport"] == "http"
    assert "8000" in attrs["http.url"]

    tool_attrs = mcp_tool_attrs(server="signoz", tool_name="signoz_search_traces")
    assert tool_attrs["arka.mcp.tool_name"] == "signoz_search_traces"


def test_parse_mcp_body_json_and_sse():
    from arka.integrations.mcp_client import _parse_mcp_body, _parse_tools, _tool_result_text

    body = _parse_mcp_body('{"jsonrpc":"2.0","id":1,"result":{"tools":[{"name":"a"}]}}')
    assert body["result"]["tools"][0]["name"] == "a"

    sse = 'event: message\ndata: {"jsonrpc":"2.0","id":2,"result":{"protocolVersion":"2024-11-05"}}\n\n'
    parsed = _parse_mcp_body(sse)
    assert parsed["result"]["protocolVersion"] == "2024-11-05"

    tools = _parse_tools({"tools": [{"name": "signoz_ask", "description": "Ask SigNoz"}]})
    assert tools[0].name == "signoz_ask"

    text = _tool_result_text({"content": [{"type": "text", "text": "hello"}]})
    assert text == "hello"


def _mock_resp(body: dict | None = None, *, session: str = "", status: int = 200):
    resp = MagicMock()
    resp.status = status
    resp.headers = {"Mcp-Session-Id": session} if session else {}
    payload = json.dumps(body).encode() if body is not None else b""
    resp.read.return_value = payload
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_mcp_client_connect_with_mock_http():
    from arka.integrations.mcp_client import McpHttpClient

    client = McpHttpClient(server="signoz", url="http://localhost:8000/mcp", api_key="test-key")

    with patch(
        "urllib.request.urlopen",
        side_effect=[
            _mock_resp(
                {"jsonrpc": "2.0", "id": 1, "result": {"protocolVersion": "2024-11-05", "serverInfo": {"name": "signoz-mcp"}}},
                session="sess-123",
            ),
            _mock_resp(None),
            _mock_resp({"jsonrpc": "2.0", "id": 2, "result": {"tools": [{"name": "signoz_ask", "inputSchema": {}}]}}),
        ],
    ):
        tools = client.list_tools()
    assert client.session_id == "sess-123"
    assert [tool.name for tool in tools] == ["signoz_ask"]


def test_observe_mcp_server_request_records_metrics(monkeypatch):
    from arka.telemetry import mcp_obs

    calls: list[dict] = []
    span_calls: list[dict] = []

    def fake_record(**kwargs):
        calls.append(kwargs)

    def fake_emit_span(**kwargs):
        span_calls.append(kwargs)

    monkeypatch.setattr(mcp_obs, "record_mcp_request", fake_record)
    monkeypatch.setattr(mcp_obs, "emit_mcp_log", lambda *args, **kwargs: None)
    monkeypatch.setattr(mcp_obs, "_emit_mcp_server_span", fake_emit_span)

    mcp_obs.observe_mcp_server_request(
        method="tools/call",
        tool_name="arka_route",
        success=True,
        duration_ms=12,
    )

    assert calls == [
        {
            "server": "arka",
            "operation": "tools_call",
            "success": True,
            "tool_name": "arka_route",
        }
    ]
    assert span_calls[0]["tool_name"] == "arka_route"
    assert span_calls[0]["duration_ms"] == 12.0


def test_trace_mcp_server_tool_call_records_on_success(monkeypatch):
    from arka.telemetry import mcp_obs

    calls: list[dict] = []
    monkeypatch.setattr(mcp_obs, "record_mcp_request", lambda **kwargs: calls.append(kwargs))
    monkeypatch.setattr(mcp_obs, "emit_mcp_log", lambda *args, **kwargs: None)

    class _NoOpSpan:
        def set_attribute(self, *_args, **_kwargs):
            pass

        def set_status(self, *_args, **_kwargs):
            pass

        def record_exception(self, *_args, **_kwargs):
            pass

    @contextmanager
    def fake_span(_name, *, attributes=None):
        yield _NoOpSpan()

    monkeypatch.setattr("arka.telemetry.tracing.span", fake_span)
    monkeypatch.setattr("arka.telemetry.tracing.mark_ok", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("arka.telemetry.tracing.mark_error", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("arka.telemetry.tracing.set_span_attributes", lambda *_args, **_kwargs: None)
    monkeypatch.setattr("arka.telemetry.tracing.duration_ms", lambda *_args, **_kwargs: 5.0)

    with mcp_obs.trace_mcp_server_tool_call(tool_name="arka_ask"):
        pass

    assert calls[-1]["tool_name"] == "arka_ask"
    assert calls[-1]["success"] is True


def test_mcp_server_log_status(tmp_path, monkeypatch):
    from arka.telemetry.mcp_obs import mcp_server_log_status

    log_file = tmp_path / "mcp.jsonl"
    log_file.write_text("{}\n", encoding="utf-8")
    monkeypatch.setattr("arka.integrations.mcp_logs.mcp_log_path", lambda: log_file)

    status = mcp_server_log_status()
    assert status["log_exists"] is True
    assert status["log_bytes"] > 0
    assert str(log_file) == status["log_path"]


def test_signoz_mcp_self_heal_disabled():
    from arka.integrations.signoz_mcp import diagnose_failed_step

    assert diagnose_failed_step(step=1, exit_code=1, command="false") == ""
