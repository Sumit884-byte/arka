"""Tests for Arka Agent Hub."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

import pytest


@pytest.fixture
def hub_paths(tmp_path, monkeypatch):
    hub = tmp_path / "hub"
    cfg = tmp_path / "mcp.json"
    monkeypatch.setenv("ARKA_HUB_DIR", str(hub))
    monkeypatch.setattr("arka.integrations.mcp_manager.mcp_config_path", lambda: cfg)
    monkeypatch.setattr(
        "arka.paths.config_dir",
        lambda: tmp_path,
    )
    return {"hub": hub, "mcp": cfg}


def test_agent_catalog():
    from arka.integrations.agent_hub import AGENTS, list_agents

    agents = list_agents()
    assert len(agents) == 9
    keys = {k for k, _ in agents}
    assert keys == {
        "claude",
        "codex-app",
        "hermes",
        "openclaw",
        "opencode",
        "codex",
        "copilot",
        "droid",
        "pi",
    }
    assert AGENTS["claude"]["ollama_launch"] == "claude"


def test_resolve_agent_aliases():
    from arka.integrations.agent_hub import AGENTS, _resolve_agent

    assert _resolve_agent("claude code") == ("claude", AGENTS["claude"])
    assert _resolve_agent("Claude Code")[0] == "claude"
    assert _resolve_agent("hermes")[0] == "hermes"
    assert _resolve_agent("unknown") is None


def test_sync_mcp_copy(hub_paths):
    from arka.integrations.agent_hub import hub_mcp_path, sync_mcp

    hub_paths["mcp"].write_text(
        json.dumps({"mcpServers": {"demo": {"command": "echo", "args": ["hi"]}}}),
        encoding="utf-8",
    )
    result = sync_mcp()
    assert result["ok"] is True
    assert result["mode"] == "copy"
    dst = hub_mcp_path()
    assert dst.is_file()
    data = json.loads(dst.read_text(encoding="utf-8"))
    assert "demo" in data["mcpServers"]


def test_sync_all_creates_exports(hub_paths, monkeypatch):
    from arka.integrations.agent_hub import (
        hub_agents_json_path,
        hub_memory_dir,
        hub_skills_dir,
        sync_all,
    )

    hub_paths["mcp"].write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    monkeypatch.setattr(
        "arka.agent.skills.discover_skills",
        lambda **_: [{"name": "demo_skill", "description": "test", "triggers": ["demo"]}],
    )
    monkeypatch.setattr(
        "arka.core.unified_memory.status",
        lambda **_: {"unified_memory": True, "facts": {"local_count": 2}, "notes": {}},
    )
    monkeypatch.setattr("arka.integrations.message_sessions.list_sessions", lambda **_: [])

    sync_all()
    assert (hub_memory_dir() / "summary.json").is_file()
    assert (hub_skills_dir() / "manifest.json").is_file()
    assert hub_agents_json_path().is_file()
    registry = json.loads(hub_agents_json_path().read_text(encoding="utf-8"))
    assert len(registry["agents"]) == 9
    assert registry["last_sync"]["mcp"]


def test_launch_env(hub_paths):
    from arka.integrations.agent_hub import launch_env

    env = launch_env("claude")
    assert env["ARKA_HUB_DIR"] == str(hub_paths["hub"].resolve())
    assert env["ARKA_MCP_CONFIG"].endswith("mcp.json")
    assert env["MCP_CONFIG"] == env["ARKA_MCP_CONFIG"]
    assert env["ARKA_AGENT_NAME"] == "Claude Code"


def test_launch_agent_runs_ollama(hub_paths, monkeypatch):
    from arka.integrations.agent_hub import launch_agent

    hub_paths["mcp"].write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    monkeypatch.setattr("arka.integrations.agent_hub.sync_all", lambda **_: {"synced_at": "now"})
    completed = MagicMock()
    completed.returncode = 0
    with patch("arka.integrations.agent_hub.subprocess.run", return_value=completed) as run:
        code = launch_agent("hermes", sync_on_launch=True)
    assert code == 0
    args, kwargs = run.call_args
    assert args[0][:3] == ["ollama", "launch", "hermes"]
    assert "ARKA_HUB_DIR" in kwargs["env"]
    assert "ARKA_MCP_CONFIG" in kwargs["env"]


def test_launch_unknown_agent():
    from arka.integrations.agent_hub import launch_agent

    with pytest.raises(ValueError, match="Unknown agent"):
        launch_agent("not-an-agent")


def test_nl_to_argv_routes():
    from arka.integrations.agent_hub import nl_to_argv

    assert nl_to_argv("sync agent hub") == ["sync"]
    assert nl_to_argv("agent hub status") == ["status"]
    assert nl_to_argv("launch claude code") == ["launch", "claude"]
    assert nl_to_argv("ollama launch hermes") == ["launch", "hermes"]
    assert nl_to_argv("shared mcp for agents") == ["status"]
    assert nl_to_argv("hello world") is None


def test_doctor_checks(hub_paths, monkeypatch):
    from arka.integrations.agent_hub import doctor

    monkeypatch.setattr("arka.integrations.agent_hub.ollama_available", lambda: True)
    checks = doctor()
    names = {c["name"] for c in checks}
    assert "ollama" in names
    assert "hub_dir_writable" in names
    assert any(c["name"] == "hub_dir_writable" and c["ok"] for c in checks)


def test_format_list_and_status(hub_paths):
    from arka.integrations.agent_hub import format_agent_list, format_status

    listing = format_agent_list()
    assert "ollama launch claude" in listing
    assert "count\t9" in listing
    status = format_status()
    assert "hub\t" in status
    assert "claude" in status


def test_cli_list(capsys):
    from arka.integrations.agent_hub_cli import main

    assert main(["list"]) == 0
    out = capsys.readouterr().out
    assert "ollama launch" in out


def test_cli_sync(capsys, hub_paths, monkeypatch):
    from arka.integrations.agent_hub_cli import main

    hub_paths["mcp"].write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    monkeypatch.setattr(
        "arka.agent.skills.discover_skills",
        lambda **_: [],
    )
    monkeypatch.setattr(
        "arka.core.unified_memory.status",
        lambda **_: {"unified_memory": True, "facts": {}, "notes": {}},
    )
    monkeypatch.setattr("arka.integrations.message_sessions.list_sessions", lambda **_: [])

    assert main(["sync"]) == 0
    out = capsys.readouterr().out
    assert "synced_at\t" in out
    assert "mcp\t" in out
