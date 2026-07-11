"""Tests for Arka local MCP server."""

from __future__ import annotations

import io
import json
from unittest.mock import patch

import pytest


def test_list_tool_definitions_schema():
    from arka.integrations.mcp_server import list_tool_definitions, list_tool_names

    tools = list_tool_definitions()
    names = list_tool_names()
    assert len(tools) == len(names) == 6
    assert "arka_ask" in names
    assert "arka_recall" in names
    for tool in tools:
        assert tool["name"]
        assert tool["description"]
        schema = tool["inputSchema"]
        assert schema["type"] == "object"
        assert "properties" in schema


def test_mcp_server_initialize_and_list_tools():
    from arka.integrations.mcp_server import ArkaMcpServer

    server = ArkaMcpServer(stdin=io.StringIO(), stdout=io.StringIO())
    init = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 1,
            "method": "initialize",
            "params": {
                "protocolVersion": "2024-11-05",
                "capabilities": {},
                "clientInfo": {"name": "test", "version": "0"},
            },
        }
    )
    assert init is not None
    assert init["result"]["serverInfo"]["name"] == "arka"
    assert init["result"]["protocolVersion"] == "2024-11-05"

    listed = server.handle_message({"jsonrpc": "2.0", "id": 2, "method": "tools/list", "params": {}})
    assert listed is not None
    tool_names = [t["name"] for t in listed["result"]["tools"]]
    assert "arka_ask" in tool_names
    assert "arka_repo_map" in tool_names


def test_mcp_server_call_tool_mock_handlers():
    from arka.integrations.mcp_server import ArkaMcpServer

    with patch("arka.core.unified_memory.recall", return_value="dark mode"):
        server = ArkaMcpServer(stdin=io.StringIO(), stdout=io.StringIO())
        result = server.handle_message(
            {
                "jsonrpc": "2.0",
                "id": 3,
                "method": "tools/call",
                "params": {"name": "arka_recall", "arguments": {"goal": "theme"}},
            }
        )
    assert result is not None
    assert result["result"]["content"][0]["text"] == "dark mode"

    server = ArkaMcpServer(stdin=io.StringIO(), stdout=io.StringIO())
    bad = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 4,
            "method": "tools/call",
            "params": {"name": "missing_tool", "arguments": {}},
        }
    )
    assert bad is not None
    assert "error" in bad


def test_mcp_server_stdio_roundtrip():
    from arka.integrations.mcp_server import ArkaMcpServer

    inp = io.StringIO(
        json.dumps(
            {
                "jsonrpc": "2.0",
                "id": 1,
                "method": "tools/list",
                "params": {},
            }
        )
        + "\n"
    )
    out = io.StringIO()
    server = ArkaMcpServer(stdin=inp, stdout=out)
    response = server.process_line(inp.getvalue().strip())
    assert response is not None
    assert len(response["result"]["tools"]) == 6


def test_install_config_snippet():
    from arka.integrations.mcp_server import ARKA_MCP_SERVER_KEY, install_config_snippet

    raw = install_config_snippet(agent="cursor")
    data = json.loads(raw)
    entry = data["mcpServers"][ARKA_MCP_SERVER_KEY]
    assert "command" in entry
    assert entry["args"] == ["mcp", "serve"] or entry["args"] == ["-m", "arka", "mcp", "serve"]


def test_ensure_arka_self_in_config(tmp_path, monkeypatch):
    from arka.integrations.mcp_manager import load_mcp_config
    from arka.integrations.mcp_server import ARKA_MCP_SERVER_KEY, ensure_arka_self_in_config

    cfg = tmp_path / "mcp.json"
    monkeypatch.setattr("arka.integrations.mcp_manager.mcp_config_path", lambda: cfg)

    assert ensure_arka_self_in_config() is True
    data = load_mcp_config()
    assert ARKA_MCP_SERVER_KEY in data["mcpServers"]
    assert ensure_arka_self_in_config() is False


def test_mcp_server_launch_spec():
    from arka.integrations.mcp_server import mcp_server_launch_spec

    spec = mcp_server_launch_spec()
    assert spec["command"]
    assert spec["args"][-2:] == ["mcp", "serve"]


def test_handle_arka_repo_map(tmp_path):
    from arka.integrations.mcp_server import _handle_arka_repo_map

    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    text = _handle_arka_repo_map({"path": str(tmp_path), "depth": 1, "symbols": False})
    assert "Repo map" in text
    assert "pyproject.toml" in text


def test_handle_arka_remember_mock():
    from arka.integrations.mcp_server import _handle_arka_remember

    with patch("arka.core.unified_memory.remember", return_value=(0, None)):
        text = _handle_arka_remember({"text": "I prefer dark mode"})
    assert "Remembered" in text


def test_doctor_spawns_client(monkeypatch):
    from arka.integrations.mcp_client import McpTool
    from arka.integrations.mcp_server import doctor

    class FakeClient:
        server = "arka"

        def __init__(self, **kwargs):
            pass

        def connect(self):
            return {"serverInfo": {"name": "arka"}}

        def list_tools(self):
            return [McpTool(name=n) for n in [
                "arka_ask",
                "arka_remember",
                "arka_recall",
                "arka_skill",
                "arka_repo_map",
                "arka_team_run",
            ]]

        def close(self):
            pass

    monkeypatch.setattr("arka.integrations.mcp_manager.McpStdioClient", FakeClient)
    text, code = doctor()
    assert code == 0
    assert "summary\tok" in text


def test_agent_hub_sync_includes_arka_self(tmp_path, monkeypatch):
    from arka.integrations.agent_hub import hub_mcp_path, sync_mcp
    from arka.integrations.mcp_server import ARKA_MCP_SERVER_KEY

    hub = tmp_path / "hub"
    cfg = tmp_path / "mcp.json"
    monkeypatch.setenv("ARKA_HUB_DIR", str(hub))
    monkeypatch.setattr("arka.integrations.mcp_manager.mcp_config_path", lambda: cfg)
    monkeypatch.setattr("arka.paths.config_dir", lambda: tmp_path)

    cfg.write_text('{"mcpServers": {}}\n', encoding="utf-8")
    result = sync_mcp()
    assert result["ok"] is True
    hub_data = json.loads(hub_mcp_path().read_text(encoding="utf-8"))
    assert ARKA_MCP_SERVER_KEY in hub_data["mcpServers"]
