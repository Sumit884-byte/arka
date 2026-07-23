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
    assert len(agents) == 10
    keys = {k for k, _ in agents}
    assert keys == {
        "claude",
        "codex-app",
        "hermes",
        "openclaw",
        "opencode",
        "codex",
        "fugu",
        "copilot",
        "droid",
        "pi",
    }
    assert AGENTS["claude"]["ollama_launch"] == "claude"
    assert "mcp_merge_key" in AGENTS["claude"]


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


def test_merge_mcp_add_only(hub_paths, tmp_path):
    from arka.integrations.agent_hub import _hub_mcp_servers, hub_mcp_path, merge_mcp_into_path

    hub_mcp_path().parent.mkdir(parents=True, exist_ok=True)
    hub_mcp_path().write_text(
        json.dumps(
            {
                "mcpServers": {
                    "arka": {"command": "arka-mcp"},
                    "new": {"command": "new-mcp"},
                }
            }
        ),
        encoding="utf-8",
    )
    agent_cfg = tmp_path / "agent" / "mcp.json"
    agent_cfg.parent.mkdir(parents=True)
    agent_cfg.write_text(
        json.dumps({"mcpServers": {"local": {"command": "local"}, "arka": {"command": "old"}}}),
        encoding="utf-8",
    )

    result = merge_mcp_into_path(agent_cfg, _hub_mcp_servers(), create=True, replace=False)
    assert result["ok"] is True
    merged = json.loads(agent_cfg.read_text(encoding="utf-8"))
    assert "local" in merged["mcpServers"]
    assert merged["mcpServers"]["arka"]["command"] == "old"
    assert "new" in merged["mcpServers"]


def test_merge_mcp_replace(hub_paths, tmp_path):
    from arka.integrations.agent_hub import _hub_mcp_servers, hub_mcp_path, merge_mcp_into_path

    hub_mcp_path().parent.mkdir(parents=True, exist_ok=True)
    hub_mcp_path().write_text(
        json.dumps({"mcpServers": {"hub-only": {"command": "hub"}}}),
        encoding="utf-8",
    )
    agent_cfg = tmp_path / "mcp.json"
    agent_cfg.write_text(
        json.dumps({"mcpServers": {"local": {"command": "local"}}}),
        encoding="utf-8",
    )
    result = merge_mcp_into_path(agent_cfg, _hub_mcp_servers(), replace=True)
    assert result["ok"] is True
    merged = json.loads(agent_cfg.read_text(encoding="utf-8"))
    assert "local" not in merged["mcpServers"]
    assert "hub-only" in merged["mcpServers"]


def test_detect_agents(hub_paths, tmp_path, monkeypatch):
    from arka.integrations import agent_hub
    from arka.integrations.agent_hub import detect_agents, hub_mcp_path

    hub_mcp_path().parent.mkdir(parents=True, exist_ok=True)
    hub_mcp_path().write_text(json.dumps({"mcpServers": {"x": {}}}), encoding="utf-8")
    codex_path = tmp_path / "codex_mcp.json"
    codex_path.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    monkeypatch.setitem(agent_hub.AGENTS["codex"], "mcp_paths", [str(codex_path)])

    rows = detect_agents()
    codex_row = next(r for r in rows if r["agent"] == "codex")
    assert codex_row["mcp_config_exists"] is True
    assert codex_row["mcp_configs"][0]["exists"] is True


def test_unify_mcp(hub_paths, tmp_path, monkeypatch):
    from arka.integrations import agent_hub
    from arka.integrations.agent_hub import hub_mcp_path, unify_mcp

    hub_mcp_path().parent.mkdir(parents=True, exist_ok=True)
    hub_mcp_path().write_text(
        json.dumps({"mcpServers": {"shared": {"command": "shared"}}}),
        encoding="utf-8",
    )
    agent_cfg = tmp_path / "pi_mcp.json"
    monkeypatch.setitem(agent_hub.AGENTS["pi"], "mcp_paths", [str(agent_cfg)])
    for key in agent_hub.AGENTS:
        if key != "pi":
            monkeypatch.setitem(agent_hub.AGENTS[key], "mcp_paths", [])

    rows = unify_mcp()
    pi_rows = [r for r in rows if r["agent"] == "pi"]
    assert len(pi_rows) == 1
    assert pi_rows[0]["ok"] is True
    assert agent_cfg.is_file()
    data = json.loads(agent_cfg.read_text(encoding="utf-8"))
    assert "shared" in data["mcpServers"]


def test_list_adapters(hub_paths, tmp_path, monkeypatch):
    from arka.integrations import agent_hub
    from arka.integrations.agent_hub import hub_mcp_path, list_adapters

    hub_mcp_path().parent.mkdir(parents=True, exist_ok=True)
    hub_mcp_path().write_text(
        json.dumps({"mcpServers": {"hub": {"command": "hub"}}}),
        encoding="utf-8",
    )
    agent_cfg = tmp_path / "droid_mcp.json"
    agent_cfg.write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    monkeypatch.setitem(agent_hub.AGENTS["droid"], "mcp_paths", [str(agent_cfg)])
    for key in agent_hub.AGENTS:
        if key != "droid":
            monkeypatch.setitem(agent_hub.AGENTS[key], "mcp_paths", [])
    monkeypatch.setattr(agent_hub, "ADAPTER_TARGETS", {})

    rows = list_adapters()
    droid = next(r for r in rows if r["agent"] == "droid")
    assert droid["would_add"] == ["hub"]
    assert droid["fully_merged"] is False


def test_sync_all_creates_exports(hub_paths, monkeypatch):
    from arka.integrations.agent_hub import (
        hub_agents_json_path,
        hub_launch_env_path,
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
    assert (hub_memory_dir() / "context.md").is_file()
    assert (hub_memory_dir() / "README.md").is_file()
    assert (hub_skills_dir() / "manifest.json").is_file()
    assert (hub_skills_dir() / "INSTALL.md").is_file()
    assert hub_launch_env_path().is_file()
    assert hub_agents_json_path().is_file()
    registry = json.loads(hub_agents_json_path().read_text(encoding="utf-8"))
    from arka.integrations.agent_hub import AGENTS

    assert len(registry["agents"]) == len(AGENTS)
    assert registry["last_sync"]["mcp"]


def test_sync_unify_writes_mcp(hub_paths, tmp_path, monkeypatch):
    from arka.integrations import agent_hub
    from arka.integrations.agent_hub import sync_all

    hub_paths["mcp"].write_text(
        json.dumps({"mcpServers": {"unified": {"command": "u"}}}),
        encoding="utf-8",
    )
    agent_cfg = tmp_path / "hermes_mcp.json"
    monkeypatch.setitem(agent_hub.AGENTS["hermes"], "mcp_paths", [str(agent_cfg)])
    for key in agent_hub.AGENTS:
        if key != "hermes":
            monkeypatch.setitem(agent_hub.AGENTS[key], "mcp_paths", [])
    monkeypatch.setattr(agent_hub, "ADAPTER_TARGETS", {})
    monkeypatch.setattr("arka.agent.skills.discover_skills", lambda **_: [])
    monkeypatch.setattr(
        "arka.core.unified_memory.status",
        lambda **_: {"unified_memory": True, "facts": {}, "notes": {}},
    )
    monkeypatch.setattr("arka.integrations.message_sessions.list_sessions", lambda **_: [])

    result = sync_all(unify=True)
    assert result["unified"] is True
    assert agent_cfg.is_file()
    data = json.loads(agent_cfg.read_text(encoding="utf-8"))
    assert "unified" in data["mcpServers"]


def test_write_launch_env(hub_paths):
    from arka.integrations.agent_hub import hub_launch_env_path, launch_env, write_launch_env_file

    path = write_launch_env_file("openclaw")
    assert path == hub_launch_env_path()
    text = path.read_text(encoding="utf-8")
    assert "export ARKA_HUB_DIR=" in text
    assert "export ARKA_CONTEXT_MD=" in text
    assert "export ARKA_SKILLS_MANIFEST=" in text
    assert "export OPENCLAW_MCP_CONFIG=" in text
    env = launch_env("claude")
    assert env["ARKA_SKILLS_MANIFEST"]
    assert env["ARKA_CONTEXT_MD"]
    assert env["ARKA_SKILLS_DIR"]


def test_import_memory_json(hub_paths, tmp_path, monkeypatch):
    from arka.integrations.agent_hub import import_memory

    export = tmp_path / "export.json"
    export.write_text(
        json.dumps(
            {
                "facts": [{"text": "user prefers pytest"}],
                "long_term_notes": ["meeting at 3pm"],
            }
        ),
        encoding="utf-8",
    )
    monkeypatch.setattr(
        "arka.integrations.agent_hub._import_fact",
        lambda text: (True, None),
    )
    monkeypatch.setattr(
        "arka.integrations.agent_hub._import_note",
        lambda text, **_: (True, None),
    )
    result = import_memory(export)
    assert result["ok"] is True
    assert result["facts_imported"] == 1
    assert result["notes_imported"] == 1


def test_import_memory_markdown(hub_paths, tmp_path, monkeypatch):
    from arka.integrations.agent_hub import import_memory

    export = tmp_path / "notes.md"
    export.write_text("# Notes\n\n- First note\n- Second note\n", encoding="utf-8")
    monkeypatch.setattr(
        "arka.integrations.agent_hub._import_note",
        lambda text, **_: (True, None),
    )
    result = import_memory(export)
    assert result["ok"] is True
    assert result["notes_imported"] == 2


def test_list_memory_sources(tmp_path, monkeypatch):
    from arka.integrations import agent_hub

    mem_root = tmp_path / "agent-memory"
    mem_root.mkdir(parents=True)
    memory_file = mem_root / "MEMORY.md"
    memory_file.write_text("- prefers pytest\n", encoding="utf-8")
    rules_dir = tmp_path / "cursor-rules"
    rules_dir.mkdir()
    (rules_dir / "style.mdc").write_text("Use sentence case headings\n", encoding="utf-8")

    monkeypatch.setitem(
        agent_hub.IDE_MEMORY_SOURCES,
        "arka_session",
        {
            "name": "Arka session memory",
            "ide": "arka",
            "paths": [str(memory_file)],
        },
    )
    monkeypatch.setitem(
        agent_hub.IDE_MEMORY_SOURCES,
        "cursor",
        {
            "name": "Cursor user rules",
            "ide": "cursor",
            "paths": [str(rules_dir)],
            "directory": True,
        },
    )

    rows = agent_hub.list_memory_sources()
    ids = {row["id"] for row in rows}
    assert "arka_session" in ids
    assert "cursor" in ids
    assert any(row["file_count"] >= 1 for row in rows if row["id"] == "cursor")


def test_import_ide_memory_all(tmp_path, monkeypatch):
    from arka.integrations import agent_hub

    export = tmp_path / "MEMORY.md"
    export.write_text("- imported from ide\n", encoding="utf-8")
    monkeypatch.setitem(
        agent_hub.IDE_MEMORY_SOURCES,
        "arka_session",
        {
            "name": "Arka session memory",
            "ide": "arka",
            "paths": [str(export)],
        },
    )
    monkeypatch.setattr(
        "arka.integrations.agent_hub._import_note",
        lambda text, **_: (True, None),
    )
    monkeypatch.setattr(
        "arka.integrations.agent_hub.list_memory_sources",
        lambda **_: [
            {
                "id": "arka_session",
                "name": "Arka session memory",
                "ide": "arka",
                "files": [str(export)],
                "file_count": 1,
            }
        ],
    )

    result = agent_hub.import_ide_memory(all_sources=True)
    assert result["ok"] is True
    assert result["notes_imported"] >= 1
    assert result["imports"]


def test_launch_env(hub_paths):
    from arka.integrations.agent_hub import launch_env

    env = launch_env("claude")
    assert env["ARKA_HUB_DIR"] == str(hub_paths["hub"].resolve())
    assert env["ARKA_MCP_CONFIG"].endswith("mcp.json")
    assert env["MCP_CONFIG"] == env["ARKA_MCP_CONFIG"]
    assert env["ARKA_AGENT_NAME"] == "Claude Code"
    assert env["ARKA_SKILLS_DIR"]


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
    assert "ARKA_CONTEXT_MD" in kwargs["env"]


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
    assert nl_to_argv("detect agent hub configs") == ["detect"]
    assert nl_to_argv("agent hub adapters") == ["adapters"]
    assert nl_to_argv("hello world") is None


def test_doctor_checks(hub_paths, monkeypatch):
    from arka.integrations.agent_hub import doctor

    monkeypatch.setattr("arka.integrations.agent_hub.ollama_available", lambda: True)
    checks = doctor()
    names = {c["name"] for c in checks}
    assert "ollama" in names
    assert "hub_dir_writable" in names
    assert "hub_launch_env" in names
    assert "unify_claude" in names
    assert any(c["name"] == "hub_dir_writable" and c["ok"] for c in checks)


def test_cli_doctor_fix_runs_safe_export_sync(monkeypatch, capsys):
    from arka.integrations.agent_hub_cli import main

    monkeypatch.setattr(
        "arka.integrations.agent_hub_cli.sync_all",
        lambda **kwargs: {"synced_at": "now"},
    )
    monkeypatch.setattr(
        "arka.integrations.agent_hub_cli.format_doctor",
        lambda: ("summary\t21/21 checks passed", 0),
    )
    assert main(["doctor", "--fix"]) == 0
    assert "repaired\thub artifacts synced at now" in capsys.readouterr().out


def test_format_list_and_status(hub_paths):
    from arka.integrations.agent_hub import AGENTS, format_agent_list, format_status

    listing = format_agent_list()
    assert "ollama launch claude" in listing
    assert f"count\t{len(AGENTS)}" in listing
    status = format_status()
    assert "hub\t" in status
    assert "claude" in status
    assert "launch_env\t" in status


def test_format_detect_and_adapters(hub_paths):
    from arka.integrations.agent_hub import format_adapters, format_detect

    hub_paths["mcp"].write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    detect = format_detect()
    assert "hub\t" in detect
    adapters = format_adapters()
    assert "hub_servers\t" in adapters


def test_format_mcp_tools(hub_paths):
    from arka.integrations.agent_hub import format_mcp_tools, hub_mcp_path

    hub_mcp_path().parent.mkdir(parents=True, exist_ok=True)
    hub_mcp_path().write_text(json.dumps({"mcpServers": {"local": {"command": "arka"}}}))
    assert "local\tstdio" in format_mcp_tools()


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
    assert "launch_env\t" in out


def test_cli_detect_and_adapters(capsys, hub_paths):
    from arka.integrations.agent_hub_cli import main

    hub_paths["mcp"].write_text(json.dumps({"mcpServers": {}}), encoding="utf-8")
    assert main(["detect"]) == 0
    out = capsys.readouterr().out
    assert "configs=" in out

    assert main(["adapters"]) == 0
    out = capsys.readouterr().out
    assert "hub_servers\t" in out


def test_cli_import_memory(capsys, tmp_path, monkeypatch):
    from arka.integrations.agent_hub_cli import main

    export = tmp_path / "mem.json"
    export.write_text(json.dumps({"facts": [{"text": "test fact"}]}), encoding="utf-8")
    monkeypatch.setattr(
        "arka.integrations.agent_hub_cli.import_memory",
        lambda path: {
            "source": str(path),
            "ok": True,
            "facts_imported": 1,
            "notes_imported": 0,
            "errors": [],
        },
    )
    assert main(["import-memory", str(export)]) == 0
    out = capsys.readouterr().out
    assert "facts_imported\t1" in out
