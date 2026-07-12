"""Tests for Arka local MCP server."""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch

import pytest


def test_list_tool_definitions_schema():
    from arka.integrations.mcp_server import list_tool_definitions, list_tool_names

    tools = list_tool_definitions()
    names = list_tool_names()
    assert len(tools) == len(names) == 23
    assert "arka_ask" in names
    assert "arka_recall" in names
    assert "arka_heartbeat" in names
    assert "arka_sessions" in names
    assert "arka_routines" in names
    assert "arka_session_memory" in names
    assert "arka_subagent" in names
    assert "arka_project_rules" in names
    assert "arka_webhook" in names
    assert "arka_view_data" in names
    assert "arka_clipboard" in names
    assert "arka_remind" in names
    assert "arka_bookmarks" in names
    assert "arka_docker" in names
    assert "arka_disk" in names
    assert "arka_currency" in names
    assert "arka_qr" in names
    assert "arka_repo_health" in names
    assert "arka_agent_hub" in names
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
    assert len(response["result"]["tools"]) == 23


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

    _handle_arka_heartbeat({"action": "ping", "activity": "test.second"})
    hist = json.loads(_handle_arka_heartbeat({"action": "history", "limit": 10}))
    assert len(hist) >= 2
    assert hist[-1]["activity"] == "test.second"
    assert hist[-1]["source"] == "mcp"


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


def test_handle_arka_sessions_silence_check():
    from arka.integrations.mcp_server import _handle_arka_sessions

    silent = json.loads(
        _handle_arka_sessions({"action": "silence_check", "text": "[SILENT]"})
    )
    assert silent["silent"] is True
    assert "[silent]" in silent["tokens"]

    spoken = json.loads(
        _handle_arka_sessions(
            {"action": "silence_check", "text": "Deploy finished successfully"}
        )
    )
    assert spoken["silent"] is False


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


def test_handle_arka_routines_enable_disable(tmp_path, monkeypatch):
    from arka.integrations.mcp_server import _handle_arka_routines

    routine_file = tmp_path / "routines.json"
    routine_file.write_text(
        json.dumps(
            [
                {
                    "id": "brief",
                    "schedule": "09:00",
                    "action": "daily_brief",
                    "enabled": True,
                    "created": 1.0,
                }
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr("arka.integrations.routines.ROUTINE_FILE", routine_file)
    monkeypatch.setattr("arka.integrations.routines._install_one", lambda _entry: None)
    monkeypatch.setattr("arka.integrations.routines._uninstall_one", lambda _rid: None)

    disabled = json.loads(
        _handle_arka_routines({"action": "disable", "id": "brief"})
    )
    assert disabled["id"] == "brief"
    assert disabled["enabled"] is False
    assert json.loads(_handle_arka_routines({"action": "list", "enabled_only": True})) == []

    enabled = json.loads(_handle_arka_routines({"action": "enable", "id": "brief"}))
    assert enabled["enabled"] is True
    rows = json.loads(_handle_arka_routines({"action": "list", "enabled_only": True}))
    assert rows[0]["id"] == "brief"


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

    cleared = json.loads(
        _handle_arka_session_memory({"action": "clear", "scope": "all"})
    )
    assert cleared["scope"] == "all"
    assert cleared["removed_daily"] >= 1
    assert cleared["cleared_long_term"] is True
    assert json.loads(_handle_arka_session_memory({"action": "search", "query": "standup"})) == []


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


def test_handle_arka_remind_add_list_cancel(tmp_path, monkeypatch):
    from arka.integrations import remind
    from arka.integrations.mcp_server import _handle_arka_remind

    monkeypatch.setattr(remind, "REMINDERS_FILE", tmp_path / "reminders.json")
    monkeypatch.setattr(remind, "start_daemon", lambda: 0)

    created = json.loads(
        _handle_arka_remind(
            {"action": "add", "text": "stretch", "in": "30m", "start": False}
        )
    )
    assert created["text"]
    assert created["id"]
    assert created["due_at"]

    listed = json.loads(_handle_arka_remind({"action": "list"}))
    assert len(listed) == 1
    assert listed[0]["id"] == created["id"]

    cancelled = json.loads(
        _handle_arka_remind({"action": "cancel", "id": created["id"]})
    )
    assert cancelled["cancelled"][0]["id"] == created["id"]
    assert json.loads(_handle_arka_remind({"action": "list"})) == []


def test_handle_arka_clipboard_save_list_get_clear(tmp_path, monkeypatch):
    from arka.integrations import clipboard_history as ch
    from arka.integrations.mcp_server import _handle_arka_clipboard

    store = tmp_path / "clipboard_history.json"
    monkeypatch.setattr(ch, "_store_path", lambda: store)

    saved = json.loads(
        _handle_arka_clipboard({"action": "save", "text": "paste me later"})
    )
    assert saved["index"] == 1
    assert saved["duplicate"] is False

    listed = json.loads(_handle_arka_clipboard({"action": "list"}))
    assert len(listed) == 1
    assert "paste me later" in listed[0]["preview"]

    got = json.loads(_handle_arka_clipboard({"action": "get", "index": 1}))
    assert got["text"] == "paste me later"

    cleared = _handle_arka_clipboard({"action": "clear"})
    assert "cleared" in cleared.lower()
    assert json.loads(_handle_arka_clipboard({"action": "list"})) == []


def test_handle_arka_webhook_status_and_health(tmp_path, monkeypatch):
    from arka.integrations import webhook
    from arka.integrations.mcp_server import _handle_arka_webhook

    monkeypatch.setattr(webhook, "PID_PATH", tmp_path / "arka_webhook.pid")
    monkeypatch.setenv("WEBHOOK_ENABLED", "1")
    monkeypatch.setenv("WEBHOOK_TOKEN", "test-token")
    monkeypatch.setenv("WEBHOOK_HOST", "127.0.0.1")
    monkeypatch.setenv("WEBHOOK_PORT", "8767")
    (tmp_path / "arka_webhook.pid").write_text("12345", encoding="utf-8")

    status = json.loads(_handle_arka_webhook({"action": "status"}))
    assert status["enabled"] is True
    assert status["token_set"] is True
    assert status["running"] is True
    assert status["pid"] == "12345"
    assert status["inbox_url"].endswith("/v1/inbox")

    health = json.loads(_handle_arka_webhook({"action": "health"}))
    assert health["ok"] is True
    assert health["webhook_enabled"] is True
    assert health["running"] is True


def test_handle_arka_view_data_preview():
    from arka.integrations.mcp_server import _handle_arka_view_data

    fixture = Path(__file__).parent / "fixtures" / "pubmed_sample.csv"
    payload = json.loads(
        _handle_arka_view_data(
            {"action": "preview", "path": str(fixture), "max_rows": 5, "plain": True}
        )
    )
    assert "pmid" in payload["columns"]
    assert payload["shown_rows"] >= 1
    assert "42436396" in payload["table"]
    assert "\033[" not in payload["table"]


def test_handle_arka_agent_hub_status(tmp_path, monkeypatch):
    from arka.integrations import agent_hub
    from arka.integrations.mcp_server import _handle_arka_agent_hub

    monkeypatch.setattr(agent_hub, "hub_dir", lambda: tmp_path / "hub")
    (tmp_path / "hub").mkdir()
    payload = json.loads(_handle_arka_agent_hub({"action": "status"}))
    assert payload["hub"] == str(tmp_path / "hub")
    assert payload["agent_count"] >= 1
    assert any(a["key"] for a in payload["agents"])

    listed = json.loads(_handle_arka_agent_hub({"action": "list"}))
    assert isinstance(listed, list) and listed


def test_handle_arka_bookmarks(tmp_path, monkeypatch):
    from arka.agent import bookmarks as bm
    from arka.integrations.mcp_server import _handle_arka_bookmarks

    store = tmp_path / "bookmarks.json"
    monkeypatch.setattr(bm, "_store_path", lambda: store)

    saved = json.loads(
        _handle_arka_bookmarks(
            {
                "action": "save",
                "url": "https://example.com/docs",
                "title": "Docs",
                "tags": "docs,arka",
                "note": "ref",
            }
        )
    )
    assert saved["url"] == "https://example.com/docs"
    assert "docs" in saved["tags"]

    rows = json.loads(_handle_arka_bookmarks({"action": "list"}))
    assert len(rows) == 1
    hits = json.loads(_handle_arka_bookmarks({"action": "search", "query": "docs"}))
    assert hits[0]["title"] == "Docs"
    got = json.loads(_handle_arka_bookmarks({"action": "get", "index": 1}))
    assert got["url"] == "https://example.com/docs"
    deleted = json.loads(_handle_arka_bookmarks({"action": "delete", "index": 1}))
    assert deleted["title"] == "Docs"
    assert json.loads(_handle_arka_bookmarks({"action": "list"})) == []


def test_handle_arka_docker_health(monkeypatch):
    from arka.integrations import docker_status as ds
    from arka.integrations.mcp_server import _handle_arka_docker

    monkeypatch.setattr(
        ds,
        "health_payload",
        lambda: {
            "docker_cli": True,
            "daemon_running": True,
            "running_containers": 2,
            "detail": "",
        },
    )
    monkeypatch.setattr(
        ds,
        "list_containers",
        lambda: {
            "count": 1,
            "containers": [
                {
                    "name": "api",
                    "status": "Up",
                    "image": "api:latest",
                    "ports": "8080->80",
                }
            ],
        },
    )
    health = json.loads(_handle_arka_docker({"action": "health"}))
    assert health["daemon_running"] is True
    assert health["running_containers"] == 2
    ps = json.loads(_handle_arka_docker({"action": "ps"}))
    assert ps["containers"][0]["name"] == "api"


def test_handle_arka_qr_ascii(monkeypatch):
    from arka.integrations import qr_code as qr_mod
    from arka.integrations.mcp_server import _handle_arka_qr

    monkeypatch.setattr(
        qr_mod,
        "ascii_payload",
        lambda text: {
            "text": text,
            "ascii": "##",
            "version": 1,
            "modules": 21,
            "engine": "qrcode",
        },
    )
    payload = json.loads(_handle_arka_qr({"text": "https://example.com"}))
    assert payload["text"] == "https://example.com"
    assert payload["modules"] == 21


def test_handle_arka_currency_convert(monkeypatch):
    from decimal import Decimal

    from arka.integrations import currency as currency_mod
    from arka.integrations.mcp_server import _handle_arka_currency

    monkeypatch.setattr(
        currency_mod,
        "convert_payload",
        lambda amount, from_ccy, to_ccy: {
            "amount": str(amount),
            "from": "USD",
            "to": "INR",
            "rate": "83",
            "result": "8300",
            "formatted": {"amount": "100", "result": "8,300"},
            "date": "2026-07-12",
            "source": "test",
        },
    )
    payload = json.loads(
        _handle_arka_currency({"action": "convert", "amount": 100, "from": "USD", "to": "INR"})
    )
    assert payload["from"] == "USD"
    assert payload["to"] == "INR"
    assert payload["result"] == "8300"


def test_handle_arka_disk_usage(monkeypatch):
    from arka.core import disk as disk_mod
    from arka.integrations.mcp_server import _handle_arka_disk

    monkeypatch.setattr(
        disk_mod,
        "usage_payload",
        lambda path=None: {
            "path": "/tmp/home",
            "mount": "/",
            "total": "500G",
            "used": "200G",
            "avail": "300G",
            "pct": "40%",
        },
    )
    payload = json.loads(_handle_arka_disk({"action": "usage"}))
    assert payload["pct"] == "40%"
    assert payload["path"] == "/tmp/home"


def test_handle_arka_repo_health_scan(tmp_path):
    from arka.integrations.mcp_server import _handle_arka_repo_health

    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
    (tmp_path / "tests").mkdir()
    payload = json.loads(
        _handle_arka_repo_health({"action": "scan", "path": str(tmp_path)})
    )
    assert payload["path"] == str(tmp_path.resolve())
    assert payload["count"] >= 1
    assert any(c["category"] in ("test", "lint") for c in payload["checks"])


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
                "arka_webhook",
                "arka_view_data",
                "arka_clipboard",
                "arka_remind",
                "arka_bookmarks",
                "arka_docker",
                "arka_disk",
                "arka_currency",
                "arka_qr",
                "arka_repo_health",
                "arka_agent_hub",
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
