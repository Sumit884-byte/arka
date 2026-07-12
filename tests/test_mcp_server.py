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
    assert len(tools) == len(names) == 12
    assert "arka_ask" in names
    assert "arka_recall" in names
    assert "arka_heartbeat" in names
    assert "arka_sessions" in names
    assert "arka_routines" in names
    assert "arka_session_memory" in names
    assert "arka_subagent" in names
    assert "arka_project_rules" in names
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
    assert len(response["result"]["tools"]) == 12


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


def test_handle_arka_heartbeat_ping_and_status(tmp_path, monkeypatch):
    from arka.integrations.mcp_server import _handle_arka_heartbeat

    hb_file = tmp_path / "heartbeat.json"
    monkeypatch.setattr("arka.integrations.heartbeat.HEARTBEAT_FILE", hb_file)
    monkeypatch.setattr("arka.integrations.heartbeat.cache_dir", lambda: tmp_path)

    ping_text = _handle_arka_heartbeat({"action": "ping", "activity": "test.mcp"})
    assert "Heartbeat ping" in ping_text
    assert hb_file.is_file()

    status_text = _handle_arka_heartbeat({"action": "status"})
    assert "Last activity" in status_text

    json_text = _handle_arka_heartbeat({"action": "status", "json": True})
    data = json.loads(json_text)
    assert data.get("last_activity") == "test.mcp"


def test_handle_arka_sessions_list_and_context(tmp_path, monkeypatch):
    from arka.integrations.mcp_server import _handle_arka_sessions
    from arka.integrations.message_sessions import push

    monkeypatch.setenv("MESSAGE_SESSIONS_DIR", str(tmp_path))
    monkeypatch.setenv("MESSAGE_SESSIONS", "1")
    code, err = push("cli", "default", "user", "hello from mcp test", title="demo")
    assert code == 0, err

    listed = json.loads(_handle_arka_sessions({"action": "list", "limit": 10}))
    assert len(listed) == 1
    assert listed[0]["key"] == "cli:default"
    assert listed[0]["turns"] == 1

    status = json.loads(_handle_arka_sessions({"action": "status", "channel": "cli"}))
    assert status["sessions"] == 1
    assert status["session"]["turns"] == 1

    ctx = _handle_arka_sessions({"action": "context", "channel": "cli", "chat_id": "default"})
    assert "hello from mcp test" in ctx

    resumed = json.loads(
        _handle_arka_sessions(
            {"action": "resume", "channel": "cli", "chat_id": "default", "limit": 5}
        )
    )
    assert resumed["key"] == "cli:default"
    assert resumed["title"] == "demo"
    assert resumed["turn_count"] == 1
    assert resumed["turns"][0]["text"] == "hello from mcp test"
    assert resumed["turns"][0]["role"] == "user"


def test_handle_arka_sessions_push_and_reset(tmp_path, monkeypatch):
    from arka.integrations.mcp_server import _handle_arka_sessions

    monkeypatch.setenv("MESSAGE_SESSIONS_DIR", str(tmp_path))
    monkeypatch.setenv("MESSAGE_SESSIONS", "1")

    push_text = _handle_arka_sessions(
        {
            "action": "push",
            "channel": "cursor",
            "chat_id": "proj-1",
            "role": "assistant",
            "text": "Implemented auth middleware",
            "title": "Auth work",
        }
    )
    assert "Session turn stored" in push_text

    ctx = _handle_arka_sessions(
        {"action": "context", "channel": "cursor", "chat_id": "proj-1"}
    )
    assert "Implemented auth middleware" in ctx
    assert "ASSISTANT:" in ctx

    status = json.loads(
        _handle_arka_sessions({"action": "status", "channel": "cursor", "chat_id": "proj-1"})
    )
    assert status["session"]["turns"] == 1

    reset_text = _handle_arka_sessions(
        {"action": "reset", "channel": "cursor", "chat_id": "proj-1"}
    )
    assert "Session reset: cursor:proj-1" in reset_text

    ctx_after = _handle_arka_sessions(
        {"action": "context", "channel": "cursor", "chat_id": "proj-1"}
    )
    assert ctx_after == "(no session context)"


def test_handle_arka_routines_list(tmp_path, monkeypatch):
    from arka.integrations.mcp_server import _handle_arka_routines

    routine_file = tmp_path / "routines.json"
    routine_file.write_text(
        json.dumps(
            [
                {
                    "id": "morning",
                    "schedule": "daily 9am",
                    "action": "check unread emails",
                    "enabled": True,
                    "created": 1.0,
                },
                {
                    "id": "paused",
                    "schedule": "hourly",
                    "action": "ping status",
                    "enabled": False,
                    "created": 2.0,
                },
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("arka.integrations.routines.ROUTINE_FILE", routine_file)

    rows = json.loads(_handle_arka_routines({"action": "list"}))
    assert len(rows) == 2
    assert rows[0]["id"] == "morning"

    enabled = json.loads(_handle_arka_routines({"action": "list", "enabled_only": True}))
    assert len(enabled) == 1
    assert enabled[0]["id"] == "morning"


def test_handle_arka_routines_add_and_remove(tmp_path, monkeypatch):
    from arka.integrations.mcp_server import _handle_arka_routines

    routine_file = tmp_path / "routines.json"
    routine_file.write_text("[]", encoding="utf-8")
    monkeypatch.setattr("arka.integrations.routines.ROUTINE_FILE", routine_file)
    monkeypatch.setattr(
        "arka.integrations.routines._security_gate_action",
        lambda _action: True,
    )
    monkeypatch.setattr("arka.integrations.routines._uninstall_one", lambda _rid: None)

    created = json.loads(
        _handle_arka_routines(
            {
                "action": "add",
                "schedule": "09:00",
                "task": "check unread emails",
                "name": "inbox-check",
            }
        )
    )
    assert created["id"] == "inbox-check"
    assert created["schedule"] == "09:00"
    assert "email" in created["action"].lower() or "agent" in created["action"].lower()

    rows = json.loads(_handle_arka_routines({"action": "list"}))
    assert any(r["id"] == "inbox-check" for r in rows)

    removed = _handle_arka_routines({"action": "remove", "id": "inbox-check"})
    assert "Removed routine inbox-check" in removed
    assert json.loads(_handle_arka_routines({"action": "list"})) == []


def test_handle_arka_session_memory(tmp_path, monkeypatch):
    from arka.core import session_memory
    from arka.integrations.mcp_server import _handle_arka_session_memory

    monkeypatch.setattr(session_memory, "memory_root", lambda: tmp_path)
    monkeypatch.setenv("SESSION_MEMORY", "1")

    append_text = _handle_arka_session_memory(
        {"action": "append", "text": "Prefers morning standups", "long_term": True}
    )
    assert "Session memory stored" in append_text

    hits = json.loads(_handle_arka_session_memory({"action": "search", "query": "standup"}))
    assert len(hits) >= 1
    assert "standup" in hits[0]["text"].lower()

    ctx = _handle_arka_session_memory({"action": "context", "goal": "standup"})
    assert "standup" in ctx.lower()

    status = json.loads(_handle_arka_session_memory({"action": "status"}))
    assert status["enabled"] is True


def test_handle_arka_subagent_spawn_and_list(tmp_path, monkeypatch):
    from arka.integrations import subagent
    from arka.integrations.mcp_server import _handle_arka_subagent

    monkeypatch.setattr(subagent, "subagents_root", lambda: tmp_path)

    with patch("arka.integrations.subagent._run_agent", return_value=("mcp subagent done", 0)):
        payload = json.loads(
            _handle_arka_subagent({"action": "spawn", "task": "summarize logs", "sync": True})
        )
    assert payload["status"] == "done"
    assert "mcp subagent done" in payload.get("result", "")

    listed = json.loads(_handle_arka_subagent({"action": "list", "limit": 5}))
    assert len(listed) == 1
    assert listed[0]["status"] == "done"

    detail = json.loads(
        _handle_arka_subagent({"action": "status", "agent_id": payload["id"]})
    )
    assert detail["task"] == "summarize logs"

    resumed = json.loads(
        _handle_arka_subagent({"action": "resume", "agent_id": payload["id"]})
    )
    assert resumed["id"] == payload["id"]
    assert resumed["status"] == "done"
    assert "mcp subagent done" in resumed.get("result", "")


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
                "arka_heartbeat",
                "arka_sessions",
                "arka_routines",
                "arka_session_memory",
                "arka_subagent",
                "arka_project_rules",
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
