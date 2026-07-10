"""Tests for MCP client observability."""

from __future__ import annotations

import json
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


def test_signoz_mcp_self_heal_disabled():
    from arka.integrations.signoz_mcp import diagnose_failed_step

    assert diagnose_failed_step(step=1, exit_code=1, command="false") == ""
