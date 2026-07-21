"""Tests for Arka local MCP server."""

from __future__ import annotations

import io
import json
from pathlib import Path
from unittest.mock import patch



def test_list_tool_definitions_schema(monkeypatch):
    from arka.integrations.mcp_server import list_tool_definitions, list_tool_names

    monkeypatch.delenv("ARKA_MCP_ENABLE_PERSONAL_SKILLS", raising=False)
    monkeypatch.delenv("ARKA_MCP_ENABLED_TOOLS", raising=False)
    tools = list_tool_definitions()
    names = list_tool_names()
    assert len(tools) == len(names)
    assert "arka_ask" in names
    assert "arka_recall" in names
    assert "arka_heartbeat" in names
    assert "arka_sessions" in names
    assert "arka_routines" in names
    assert "arka_session_memory" in names
    assert "arka_subagent" in names
    assert "arka_jules" in names
    assert "arka_self_build" in names
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
    assert "arka_sports" in names
    assert "arka_config" in names
    assert "arka_price" in names
    assert "arka_github" in names
    assert "arka_persona" in names
    assert "arka_personalize" in names
    assert "arka_platform" in names
    assert "arka_calendar" in names
    assert "arka_textkit" in names
    assert "arka_spotify" not in names
    assert "arka_password" in names
    assert "arka_urlkit" in names
    assert "arka_timekit" in names
    assert "arka_jsonkit" in names
    assert "arka_repo_health" in names
    assert "arka_agent_hub" in names
    assert "arka_team_run" in names
    for tool in tools:
        assert tool["name"]
        assert tool["description"]
        schema = tool["inputSchema"]
        assert schema["type"] == "object"
        assert "properties" in schema


def test_mcp_personal_tools_can_be_opted_in(monkeypatch):
    from arka.integrations.mcp_server import list_tool_names

    monkeypatch.setenv("ARKA_MCP_ENABLE_PERSONAL_SKILLS", "1")
    assert "arka_spotify" in list_tool_names()


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
    tools = listed["result"]["tools"]
    tool_names = [t["name"] for t in tools]
    assert "arka_ask" in tool_names
    assert "arka_repo_map" in tool_names
    route_tool = next(t for t in tools if t["name"] == "arka_route")
    assert "Umbrella Arka MCP tool" in route_tool["description"]
    assert "complete natural-language" in route_tool["inputSchema"]["properties"]["prompt"]["description"]


def test_mcp_capabilities_names_arka_route_as_umbrella_tool():
    from arka.integrations.mcp_server import ArkaMcpServer

    server = ArkaMcpServer(stdin=io.StringIO(), stdout=io.StringIO())
    result = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 22,
            "method": "tools/call",
            "params": {"name": "arka_capabilities", "arguments": {}},
        }
    )
    assert result is not None
    payload = json.loads(result["result"]["content"][0]["text"])
    assert payload["umbrella_tool"]["name"] == "arka_route"
    assert "unsure which specific MCP tool" in payload["umbrella_tool"]["use_when"]


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


def test_mcp_server_writes_tool_call_logs(tmp_path, monkeypatch):
    from arka.integrations.mcp_logs import read_mcp_logs
    from arka.integrations.mcp_server import ArkaMcpServer

    monkeypatch.setenv("ARKA_MCP_LOG_PATH", str(tmp_path / "mcp.jsonl"))
    server = ArkaMcpServer(stdin=io.StringIO(), stdout=io.StringIO())
    result = server.handle_message(
        {
            "jsonrpc": "2.0",
            "id": 5,
            "method": "tools/call",
            "params": {"name": "missing_tool", "arguments": {}},
        }
    )
    assert result is not None
    logs = read_mcp_logs(limit=5)
    assert "server.tools_call" in logs
    assert "unknown_tool" in (tmp_path / "mcp.jsonl").read_text(encoding="utf-8")


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
    assert len(response["result"]["tools"]) == 40


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
    monkeypatch.setattr(
        "arka.integrations.routines._routine_file", lambda: routine_file
    )

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
    monkeypatch.setattr(
        "arka.integrations.routines._routine_file", lambda: routine_file
    )
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
    monkeypatch.setattr(
        "arka.integrations.routines._routine_file", lambda: routine_file
    )
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


def test_subagent_routes_coding_task_to_run_skill(monkeypatch):
    from arka.integrations import subagent

    calls: list[str] = []

    def fake_run_coding(task: str, *, skill_line: str) -> tuple[str, int]:
        calls.append(skill_line)
        return "patched App.jsx", 0

    monkeypatch.setattr(subagent, "_run_coding_task", fake_run_coding)
    output, code = subagent._run_agent("edit src/App.jsx fix Moon rotation")
    assert code == 0
    assert "patched App.jsx" in output
    assert calls
    assert calls[0].startswith("code write ")


def test_run_skill_captured_strips_subprocess_output(monkeypatch):
    from arka.integrations.mcp_server import _run_skill_captured

    def fake_run_skill(skill_line: str) -> int:
        print("\x1b[36mDownload complete\x1b[0m")
        return 0

    monkeypatch.setattr("arka.dispatch.run_skill", fake_run_skill)
    code, output = _run_skill_captured("demo skill")
    assert code == 0
    assert "\x1b" not in output
    assert "Download complete" in output


def test_run_skill_captured_converts_system_exit_to_error(monkeypatch):
    from arka.integrations.mcp_server import _run_skill_captured

    def fake_run_skill(_skill_line: str) -> int:
        raise SystemExit("Image not found: missing.png")

    monkeypatch.setattr("arka.dispatch.run_skill", fake_run_skill)
    code, output = _run_skill_captured("vision_evidence missing.png question")
    assert code == 2
    assert "Image not found" in output


def test_mcp_handler_survives_system_exit():
    from arka.integrations.mcp_server import ArkaMcpServer

    server = ArkaMcpServer()
    response = server.handle_message({"jsonrpc": "2.0", "id": 7, "method": "tools/call", "params": {"name": "arka_skill", "arguments": {"skill": "play"}}})
    assert response["id"] == 7
    assert "required: game" in response["result"]["content"][0]["text"]


def test_mcp_does_not_open_websites_without_explicit_approval():
    from arka.integrations.mcp_server import _handle_arka_skill

    blocked = _handle_arka_skill({"skill": "open_url", "args": ["https://example.com"]})
    assert "disabled" in blocked.lower()
    assert "headless" in blocked.lower()


def test_mcp_disables_personal_skill_heads_by_default(monkeypatch):
    from arka.integrations.mcp_server import _handle_arka_skill

    monkeypatch.delenv("ARKA_MCP_ENABLE_PERSONAL_SKILLS", raising=False)
    for skill in ("daily_brief", "play_spotify", "search_web", "spotify_brave_debug"):
        blocked = _handle_arka_skill({"skill": skill})
        assert "is disabled by default" in blocked.lower()
        assert skill in blocked


def test_mcp_spotify_tool_disabled_by_default(monkeypatch):
    from arka.integrations.mcp_server import _handle_arka_spotify

    monkeypatch.delenv("ARKA_MCP_ENABLE_PERSONAL_SKILLS", raising=False)
    blocked = _handle_arka_spotify({"action": "search", "query": "Song"})
    assert "is disabled by default" in blocked.lower()
    assert "arka_spotify" in blocked


def test_handle_arka_remind_add_list_cancel(tmp_path, monkeypatch):
    from arka.integrations import remind
    from arka.integrations.mcp_server import _handle_arka_remind

    monkeypatch.setattr(
        remind, "_reminders_file", lambda: tmp_path / "reminders.json"
    )
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


def test_handle_arka_jsonkit_validate(monkeypatch):
    from arka.core import jsonkit as jk
    from arka.integrations.mcp_server import _handle_arka_jsonkit

    monkeypatch.setattr(
        jk,
        "validate_payload",
        lambda text: {"ok": True, "valid": True, "error": None, "type": "dict", "bytes": len(text)},
    )
    monkeypatch.setattr(
        jk,
        "get_payload",
        lambda text, path: {"ok": True, "path": path, "type": "int", "value": 1, "json": "1"},
    )
    validated = json.loads(_handle_arka_jsonkit({"action": "validate", "json": "{}"}))
    assert validated["valid"] is True
    got = json.loads(_handle_arka_jsonkit({"action": "get", "json": "{\"a\":1}", "path": "a"}))
    assert got["value"] == 1


def test_handle_arka_timekit_now(monkeypatch):
    from arka.core import timekit as tk
    from arka.integrations.mcp_server import _handle_arka_timekit

    monkeypatch.setattr(
        tk,
        "now_payload",
        lambda tz=None: {
            "ok": True,
            "timezone": tz or "UTC",
            "iso": "2026-07-12T10:00:00+00:00",
            "unix": 1,
            "utc_iso": "2026-07-12T10:00:00+00:00",
            "weekday": "Sunday",
        },
    )
    monkeypatch.setattr(
        tk,
        "relative_payload",
        lambda expression, tz=None, base=None: {
            "ok": True,
            "expression": expression,
            "amount": 2,
            "unit": "hours",
            "iso": "2026-07-12T12:00:00+00:00",
            "unix": 2,
            "timezone": "UTC",
            "base_iso": "2026-07-12T10:00:00+00:00",
        },
    )
    now = json.loads(_handle_arka_timekit({"action": "now", "tz": "UTC"}))
    assert now["weekday"] == "Sunday"
    rel = json.loads(_handle_arka_timekit({"action": "relative", "expression": "2h"}))
    assert rel["unit"] == "hours"


def test_handle_arka_urlkit_parse(monkeypatch):
    from arka.core import urlkit as uk
    from arka.integrations.mcp_server import _handle_arka_urlkit

    monkeypatch.setattr(
        uk,
        "parse_payload",
        lambda url: {"ok": True, "input": url, "host": "example.com", "path": "/a"},
    )
    monkeypatch.setattr(
        uk,
        "slugify_payload",
        lambda text, max_length=80: {"ok": True, "input": text, "slug": "hello-world", "length": 11},
    )
    parsed = json.loads(_handle_arka_urlkit({"action": "parse", "url": "https://example.com/a"}))
    assert parsed["host"] == "example.com"
    slug = json.loads(_handle_arka_urlkit({"action": "slugify", "text": "Hello World"}))
    assert slug["slug"] == "hello-world"


def test_handle_arka_password_generate(monkeypatch):
    from arka.integrations import password_vault as vault
    from arka.integrations.mcp_server import _handle_arka_password

    monkeypatch.setattr(
        vault,
        "generate_payload",
        lambda length=16, symbols=True: {
            "ok": True,
            "password": "Aa1!" + ("x" * max(0, length - 4)),
            "length": length,
            "symbols": symbols,
            "stored": False,
            "note": "One-shot password; not written to the vault",
        },
    )
    payload = json.loads(_handle_arka_password({"action": "generate", "length": 12}))
    assert payload["stored"] is False
    assert payload["length"] == 12


def test_handle_arka_spotify_search(monkeypatch):
    from arka.integrations import spotify as spotify_mod
    from arka.integrations.mcp_server import _handle_arka_spotify

    monkeypatch.setenv("ARKA_MCP_ENABLE_PERSONAL_SKILLS", "1")
    monkeypatch.setattr(
        spotify_mod,
        "search_payload",
        lambda query: {
            "ok": True,
            "query": query,
            "found": True,
            "track": {
                "id": "abc",
                "name": "Song",
                "artist": "Artist",
                "uri": "spotify:track:abc",
                "url": "https://open.spotify.com/track/abc",
            },
            "error": None,
        },
    )
    payload = json.loads(_handle_arka_spotify({"action": "search", "query": "Song"}))
    assert payload["found"] is True
    assert payload["track"]["id"] == "abc"


def test_handle_arka_textkit_hash(monkeypatch):
    from arka.core import textkit as tk
    from arka.integrations.mcp_server import _handle_arka_textkit

    monkeypatch.setattr(
        tk,
        "hash_payload",
        lambda text, algorithm="sha256": {
            "ok": True,
            "algorithm": algorithm,
            "hex": "abc",
            "bytes": len(text.encode("utf-8")),
        },
    )
    monkeypatch.setattr(
        tk,
        "uuid_payload",
        lambda version=4, name=None, namespace="url": {
            "ok": True,
            "version": version,
            "uuid": "00000000-0000-4000-8000-000000000000",
        },
    )
    hashed = json.loads(_handle_arka_textkit({"action": "hash", "text": "hi"}))
    assert hashed["hex"] == "abc"
    uid = json.loads(_handle_arka_textkit({"action": "uuid"}))
    assert uid["version"] == 4


def test_handle_arka_calendar_today(monkeypatch):
    from arka.integrations import macos_calendar as cal_mod
    from arka.integrations.mcp_server import _handle_arka_calendar

    monkeypatch.setattr(
        cal_mod,
        "today_payload",
        lambda: {
            "ok": True,
            "available": True,
            "error": None,
            "count": 1,
            "events": [
                {
                    "summary": "Standup",
                    "calendar": "Work",
                    "when": "Sun Jul 12, 2026 · 10:00 AM",
                    "start": "2026-07-12T10:00:00+05:30",
                    "end": "2026-07-12T10:30:00+05:30",
                    "source": "macos",
                }
            ],
        },
    )
    payload = json.loads(_handle_arka_calendar({"action": "today"}))
    assert payload["count"] == 1
    assert payload["events"][0]["summary"] == "Standup"


def test_handle_arka_platform_show(monkeypatch):
    from arka.core import platform as plat_mod
    from arka.integrations.mcp_server import _handle_arka_platform

    monkeypatch.setattr(
        plat_mod,
        "show_payload",
        lambda: {
            "cached": True,
            "cache_path": "/tmp/platform.json",
            "platform": "macos",
            "system": "Darwin",
            "machine": "arm64",
            "detected_at": "2026-07-12T00:00:00+00:00",
            "capabilities": {"clipboard_copy": "pbcopy"},
        },
    )
    monkeypatch.setattr(
        plat_mod,
        "detect_payload",
        lambda force=False, persist=True: {
            "cached": persist,
            "cache_path": "/tmp/platform.json",
            "platform": "macos",
            "system": "Darwin",
            "machine": "arm64",
            "detected_at": "2026-07-12T00:00:00+00:00",
            "capabilities": {"clipboard_copy": "pbcopy"},
            "force": force,
        },
    )
    shown = json.loads(_handle_arka_platform({"action": "show"}))
    assert shown["platform"] == "macos"
    detected = json.loads(_handle_arka_platform({"action": "detect", "persist": False}))
    assert detected["force"] is False


def test_handle_arka_personalize_status(monkeypatch):
    from arka.core import personalize as pers
    from arka.integrations.mcp_server import _handle_arka_personalize

    monkeypatch.setattr(
        pers,
        "status_payload",
        lambda: {
            "profile_path": "/tmp/personalize.json",
            "interests": ["coding"],
            "experience": "beginner",
            "platforms": ["macos"],
            "has_api_keys": True,
            "uses_fish": False,
            "onboarding_done": True,
            "completed_at": None,
            "summary": "coding (beginner)",
        },
    )
    monkeypatch.setattr(
        pers,
        "recommend_payload",
        lambda limit=8: {
            "profile_summary": "coding (beginner)",
            "count": 1,
            "skills": [{"name": "ask", "score": 1.0, "description": "q", "example": "arka ask", "available": True, "gate": ""}],
        },
    )
    status = json.loads(_handle_arka_personalize({"action": "status"}))
    assert status["interests"] == ["coding"]
    recs = json.loads(_handle_arka_personalize({"action": "recommend", "limit": 3}))
    assert recs["skills"][0]["name"] == "ask"


def test_handle_arka_persona_list(monkeypatch):
    from arka.agent.personas import io as persona_io
    from arka.integrations.mcp_server import _handle_arka_persona

    monkeypatch.setattr(
        persona_io,
        "list_payload",
        lambda include_templates=False: {
            "personas_dir": "/tmp/personas",
            "count": 1,
            "personas": [{"name": "elon", "display_name": "Elon", "description": "x"}],
        },
    )
    monkeypatch.setattr(
        persona_io,
        "show_payload",
        lambda name: {
            "name": name,
            "display_name": "Elon",
            "description": "x",
            "disclaimer": "sim",
            "voice": "",
            "source": "",
            "system_prompt": "Be bold.",
            "system_prompt_chars": 8,
        },
    )
    listed = json.loads(_handle_arka_persona({"action": "list"}))
    assert listed["count"] == 1
    shown = json.loads(_handle_arka_persona({"action": "show", "name": "elon"}))
    assert shown["system_prompt"] == "Be bold."


def test_handle_arka_github_resolve(monkeypatch):
    from arka.agent import github_repo as gh_mod
    from arka.integrations.mcp_server import _handle_arka_github

    monkeypatch.setattr(
        gh_mod,
        "resolve_repo_payload",
        lambda text: {
            "ok": True,
            "query": text,
            "owner": "Sumit884-byte",
            "repo": "arka",
            "full_name": "Sumit884-byte/arka",
        },
    )
    monkeypatch.setattr(
        gh_mod,
        "activity_payload",
        lambda owner, repo, days=7: {
            "ok": True,
            "owner": owner,
            "repo": repo,
            "days": days,
            "commit_count": 1,
            "commits": [{"sha": "abc1234", "message": "test"}],
            "files": [],
        },
    )
    resolved = json.loads(
        _handle_arka_github({"action": "resolve", "query": "Sumit884-byte/arka"})
    )
    assert resolved["full_name"] == "Sumit884-byte/arka"
    activity = json.loads(
        _handle_arka_github({"action": "activity", "owner": "Sumit884-byte", "repo": "arka", "days": 3})
    )
    assert activity["ok"] is True
    assert activity["commits"][0]["sha"] == "abc1234"


def test_handle_arka_price_sources(monkeypatch):
    from arka.agent import price_sources as ps
    from arka.integrations.mcp_server import _handle_arka_price

    monkeypatch.setattr(
        ps,
        "sources_payload",
        lambda **kwargs: {
            "region": "india",
            "product": "iphone",
            "category": "apple",
            "count": 1,
            "sources": [{"id": "apple_in", "label": "Apple India", "site_bias": "site:apple.com"}],
        },
    )
    monkeypatch.setattr(
        ps,
        "parse_price_payload",
        lambda query: {
            "query": query,
            "product": "iphone 16",
            "region": "india",
            "is_price_check": True,
            "category": "apple",
            "sources": [{"id": "apple_in", "label": "Apple India"}],
        },
    )
    sources = json.loads(_handle_arka_price({"action": "sources", "product": "iphone"}))
    assert sources["category"] == "apple"
    parsed = json.loads(_handle_arka_price({"action": "parse", "query": "iphone 16 price in india"}))
    assert parsed["product"] == "iphone 16"


def test_handle_arka_config_list(monkeypatch, tmp_path):
    from arka.core import config_backup as cb
    from arka.integrations.mcp_server import _handle_arka_config

    monkeypatch.setattr(
        cb,
        "list_payload",
        lambda: {
            "config_dir": str(tmp_path),
            "cache_dir": str(tmp_path / "cache"),
            "count": 1,
            "entries": [{"label": "env", "path": str(tmp_path / ".env"), "exists": False}],
        },
    )
    monkeypatch.setattr(
        cb,
        "path_payload",
        lambda target=None: {
            "config_dir": str(tmp_path),
            "cache_dir": str(tmp_path / "cache"),
            "exists": True,
            "export_snippet": f'export ARKA_CONFIG_DIR="{tmp_path}"\n',
        },
    )
    listed = json.loads(_handle_arka_config({"action": "list"}))
    assert listed["count"] == 1
    path = json.loads(_handle_arka_config({"action": "path"}))
    assert path["exists"] is True


def test_handle_arka_sports_leagues(monkeypatch):
    from arka.integrations import sports as sports_mod
    from arka.integrations.mcp_server import _handle_arka_sports

    monkeypatch.setattr(
        sports_mod,
        "leagues_payload",
        lambda: {"count": 1, "leagues": [{"label": "IPL", "sport": "cricket", "league_id": "8048", "aliases": ["ipl"]}]},
    )
    monkeypatch.setattr(
        sports_mod,
        "scores_payload",
        lambda query="", limit_per_league=3: {
            "ok": True,
            "query": query,
            "as_of": "2026-07-12 16:00",
            "leagues": [{"label": "IPL", "ok": True, "count": 1}],
            "events": [{"league": "IPL", "brief": "MI 180/4"}],
            "count": 1,
        },
    )
    leagues = json.loads(_handle_arka_sports({"action": "leagues"}))
    assert leagues["count"] == 1
    scores = json.loads(_handle_arka_sports({"action": "scores", "query": "ipl"}))
    assert scores["ok"] is True
    assert scores["events"][0]["league"] == "IPL"


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


def test_handle_arka_disk_breakdown(monkeypatch):
    from arka.core import disk as disk_mod
    from arka.integrations.mcp_server import _handle_arka_disk

    monkeypatch.setattr(
        disk_mod,
        "breakdown_payload",
        lambda path=None: {
            "home": "/tmp/home",
            "categories": [{"name": "Downloads", "bytes": 1024}],
        },
    )
    payload = json.loads(_handle_arka_disk({"action": "breakdown"}))
    assert payload["home"] == "/tmp/home"
    assert payload["categories"][0]["name"] == "Downloads"


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
                        "arka_capabilities",
                    "arka_route",
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
                "arka_sports",
                "arka_config",
                "arka_price",
                "arka_github",
                "arka_persona",
                "arka_personalize",
                "arka_platform",
                "arka_calendar",
                "arka_textkit",
                "arka_spotify",
                "arka_password",
                "arka_urlkit",
                "arka_timekit",
                "arka_jsonkit",
                "arka_repo_health",
                "arka_agent_hub",
                "arka_jules",
                "arka_self_build",
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
