"""Tests for generic MCP server management."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def mcp_config(tmp_path, monkeypatch):
    cfg = tmp_path / "mcp.json"
    monkeypatch.setattr("arka.integrations.mcp_manager.mcp_config_path", lambda: cfg)
    return cfg


def test_mcp_config_crud(mcp_config):
    from arka.integrations.mcp_manager import (
        add_server,
        get_server_config,
        list_server_names,
        load_mcp_config,
        remove_server,
    )

    assert list_server_names() == []

    add_server("demo", command="echo", args=["hello"])
    assert list_server_names() == ["demo"]
    cfg = get_server_config("demo")
    assert cfg.command == "echo"
    assert cfg.args == ["hello"]
    assert cfg.transport == "stdio"

    add_server("remote", url="http://localhost:9000/mcp", headers={"X-Auth": "tok"})
    remote = get_server_config("remote")
    assert remote.url == "http://localhost:9000/mcp"
    assert remote.headers["X-Auth"] == "tok"
    assert remote.transport == "http"

    data = load_mcp_config()
    assert set(data["mcpServers"]) == {"demo", "remote"}
    assert mcp_config.is_file()

    assert remove_server("demo") is True
    assert list_server_names() == ["remote"]
    assert remove_server("missing") is False


def test_mcp_config_invalid_entry(mcp_config):
    from arka.integrations.mcp_manager import McpServerConfig

    mcp_config.write_text(
        json.dumps({"mcpServers": {"bad": {"args": []}}}),
        encoding="utf-8",
    )
    with pytest.raises(ValueError, match="needs command or url"):
        McpServerConfig.from_entry("bad", {"args": []})


def test_nl_to_argv_routes():
    from arka.integrations.mcp_manager import nl_to_argv

    assert nl_to_argv("mcp status") == ["status"]
    assert nl_to_argv("check mcp connection health") == ["status"]
    assert nl_to_argv("list configured mcp servers") == ["list"]
    assert nl_to_argv("list mcp tools from signoz") == ["tools", "signoz"]
    assert nl_to_argv("mcp tools github") == ["tools", "github"]
    assert nl_to_argv("list arka mcp tools") == ["self-tools"]
    assert nl_to_argv("show arka self mcp tools") == ["self-tools"]
    assert nl_to_argv("hello world") is None
    assert nl_to_argv("invoke tool search on github") == ["call", "github", "search"]
    assert nl_to_argv("what MCP tools are available from signoz") == ["tools", "signoz"]
    assert nl_to_argv("show mcp logs") == ["logs"]
    assert nl_to_argv("use baryhuang/mcp-threejs") == ["preset", "threejs"]
    assert nl_to_argv("configure mcp-server-threejs") == ["preset", "threejs", "--apply"]
    assert nl_to_argv("make it use spline mcp by default") == ["preset", "spline", "--apply"]


def test_spline_mcp_preset(mcp_config):
    from arka.integrations.mcp_manager import configure_preset, format_preset, get_server_config

    cfg, path = configure_preset("spline", apply=False)
    assert cfg.name == "spline"
    assert cfg.command.endswith("spline-mcp")
    assert path is None
    assert "arka mcp preset spline --apply" in format_preset("spline")

    installed, path = configure_preset("spline", apply=True)
    assert installed.name == "spline"
    assert path == mcp_config
    assert get_server_config("spline").command.endswith("spline-mcp")


def test_mcp_logs_write_read_and_redact(tmp_path, monkeypatch):
    from arka.integrations.mcp_logs import log_mcp_event, read_mcp_logs

    monkeypatch.setenv("ARKA_MCP_LOG_PATH", str(tmp_path / "mcp.jsonl"))
    log_mcp_event("client.call_tool", server="demo", tool="search", status="error", api_key="secret")
    text = read_mcp_logs(limit=5)
    assert "client.call_tool" in text
    assert "search" in text
    data = json.loads(read_mcp_logs(limit=5, json_output=True))
    assert data["count"] == 1
    assert data["events"][0]["api_key"] == "[redacted]"


def test_threejs_mcp_preset_preview_and_apply(mcp_config):
    from arka.integrations.mcp_manager import format_preset, get_server_config, list_server_names

    preview = format_preset("baryhuang/mcp-threejs", apply=False)
    assert "mode\tpreview" in preview
    assert "buryhuang/mcp-server-threejs:latest" in preview
    assert list_server_names() == []

    applied = format_preset("threejs", apply=True)
    assert "mode\tapplied" in applied
    assert list_server_names() == ["threejs"]
    cfg = get_server_config("threejs")
    assert cfg.command == "docker"
    assert "buryhuang/mcp-server-threejs:latest" in cfg.args
    assert cfg.env["SKETCHFAB_ACCESS_TOKEN"] == "${env:SKETCHFAB_ACCESS_TOKEN}"
    assert cfg.env["SKETCHFAB_CLIENT_ID"] == "${env:SKETCHFAB_CLIENT_ID}"


def test_stdio_client_rpc_mock():
    from arka.integrations.mcp_manager import McpStdioClient

    client = McpStdioClient(server="demo", command="fake", args=[])

    proc = MagicMock()
    proc.poll.return_value = None
    proc.stdin = MagicMock()
    proc.stdout = MagicMock()
    proc.stdout.readline.side_effect = [
        '{"jsonrpc":"2.0","id":1,"result":{"protocolVersion":"2024-11-05","serverInfo":{"name":"demo"}}}\n',
        '{"jsonrpc":"2.0","id":2,"result":{"tools":[{"name":"ping","description":"Ping"}]}}\n',
        '{"jsonrpc":"2.0","id":3,"result":{"content":[{"type":"text","text":"pong"}]}}\n',
    ]
    client._proc = proc

    info = client.connect()
    assert info["serverInfo"]["name"] == "demo"

    tools = client.list_tools()
    assert [t.name for t in tools] == ["ping"]

    result = client.call_tool("ping")
    assert result["content"][0]["text"] == "pong"


def test_call_tool_reconnects_once_after_connection_closed(monkeypatch):
    from arka.integrations import mcp_manager

    first = MagicMock()
    first.call_tool.side_effect = RuntimeError("MCP error -32000: Connection closed")
    second = MagicMock()
    second.call_tool.return_value = {"content": [{"type": "text", "text": "recovered"}]}
    clients = iter((first, second))
    monkeypatch.setattr(mcp_manager, "connect_client", lambda _name: next(clients))
    assert mcp_manager.call_tool("demo", "ping") == "recovered"
    first.close.assert_called_once()
    second.close.assert_called_once()


def test_context7_resolve_requires_query_before_remote_call(monkeypatch):
    from arka.integrations import mcp_manager

    with pytest.raises(ValueError, match="requires query/libraryName"):
        mcp_manager.call_tool("context7", "resolve-library-id", {})


def test_context7_resolve_sends_both_schema_field_names(monkeypatch):
    from arka.integrations import mcp_manager

    client = MagicMock()
    client.call_tool.return_value = {"content": [{"type": "text", "text": "ok"}]}
    monkeypatch.setattr(mcp_manager, "connect_client", lambda _name: client)
    assert mcp_manager.call_tool("context7", "resolve-library-id", {"query": "react"}) == "ok"
    assert client.call_tool.call_args.args[1]["libraryName"] == "react"


def test_context7_resolve_infers_dependency_from_package_json(tmp_path, monkeypatch):
    from arka.integrations import mcp_manager

    (tmp_path / "package.json").write_text(json.dumps({"dependencies": {"react": "^18"}}))
    monkeypatch.chdir(tmp_path)
    client = MagicMock()
    client.call_tool.return_value = {"content": [{"type": "text", "text": "ok"}]}
    monkeypatch.setattr(mcp_manager, "connect_client", lambda _name: client)
    assert mcp_manager.call_tool("context7", "resolve-library-id", {}) == "ok"
    assert client.call_tool.call_args.args[1]["query"] == "react"


def _mock_http_resp(body: dict | None = None, *, session: str = "", status: int = 200):
    resp = MagicMock()
    resp.status = status
    resp.headers = {"Mcp-Session-Id": session} if session else {}
    payload = json.dumps(body).encode() if body is not None else b""
    resp.read.return_value = payload
    resp.__enter__ = MagicMock(return_value=resp)
    resp.__exit__ = MagicMock(return_value=False)
    return resp


def test_connect_http_client_from_config(mcp_config):
    from arka.integrations.mcp_manager import add_server, connect_client

    add_server("signoz", url="http://localhost:8000/mcp", headers={"SIGNOZ-API-KEY": "k"})

    with patch(
        "urllib.request.urlopen",
        side_effect=[
            _mock_http_resp(
                {
                    "jsonrpc": "2.0",
                    "id": 1,
                    "result": {"protocolVersion": "2024-11-05", "serverInfo": {"name": "signoz"}},
                },
                session="sess-1",
            ),
            _mock_http_resp(None),
            _mock_http_resp(
                {"jsonrpc": "2.0", "id": 2, "result": {"tools": [{"name": "signoz_ask", "inputSchema": {}}]}}
            ),
        ],
    ):
        client = connect_client("signoz")
        try:
            tools = client.list_tools()
        finally:
            client.close()

    assert [t.name for t in tools] == ["signoz_ask"]


def test_server_status_healthy(mcp_config):
    from arka.integrations.mcp_manager import add_server, server_status

    add_server("remote", url="http://localhost:8000/mcp")

    with patch(
        "urllib.request.urlopen",
        side_effect=[
            _mock_http_resp(
                {"jsonrpc": "2.0", "id": 1, "result": {"serverInfo": {"name": "remote"}}},
                session="s",
            ),
            _mock_http_resp(None),
            _mock_http_resp({"jsonrpc": "2.0", "id": 2, "result": {"tools": []}}),
        ],
    ):
        row = server_status("remote")

    assert row["healthy"] is True
    assert row["transport"] == "http"
    assert row["tool_count"] == 0


def test_server_status_unhealthy(mcp_config):
    import urllib.error

    from arka.integrations.mcp_manager import add_server, server_status

    add_server("bad", url="http://localhost:9999/mcp")

    with patch(
        "urllib.request.urlopen",
        side_effect=urllib.error.URLError("connection refused"),
    ):
        row = server_status("bad")

    assert row["healthy"] is False
    assert "connection refused" in row["error"]


def test_mcp_cli_list(capsys, mcp_config):
    from arka.integrations.mcp_cli import main

    from arka.integrations.mcp_manager import add_server

    add_server("demo", command="echo", args=["hi"])
    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "demo" in out
    assert "stdio" in out


def test_mcp_cli_self_tools(capsys):
    from arka.integrations.mcp_cli import main

    assert main(["self-tools"]) == 0
    out = capsys.readouterr().out
    assert "server\tarka" in out
    assert "tool\tarka_ask" in out
    count = next(int(line.split("\t", 1)[1]) for line in out.splitlines() if line.startswith("tool_count\t"))
    assert count >= 37


def test_mcp_cli_parse(capsys):
    from arka.integrations.mcp_cli import main

    assert main(["parse", "mcp status"]) == 0
    assert capsys.readouterr().out.strip() == "mcp status"


def test_mcp_sdk_available_returns_bool():
    from arka.integrations.mcp_manager import mcp_sdk_available

    assert isinstance(mcp_sdk_available(), bool)
