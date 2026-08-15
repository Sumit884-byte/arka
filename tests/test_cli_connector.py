"""Tests for Arka CLI connector."""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest


@pytest.fixture
def connector_paths(tmp_path, monkeypatch):
    hub = tmp_path / "hub"
    cfg = tmp_path / "config"
    cfg.mkdir()
    hub.mkdir()
    monkeypatch.setenv("ARKA_HUB_DIR", str(hub))
    monkeypatch.setattr("arka.paths.config_dir", lambda: cfg)
    monkeypatch.setattr("arka.integrations.cli_connector.config_dir", lambda: cfg)
    monkeypatch.setattr("arka.integrations.agent_hub.hub_dir", lambda: hub)
    monkeypatch.setattr(
        "arka.integrations.agent_hub.hub_memory_dir",
        lambda: hub / "memory",
    )
    monkeypatch.setattr(
        "arka.integrations.agent_hub.hub_context_md_path",
        lambda: hub / "memory" / "context.md",
    )
    monkeypatch.setattr(
        "arka.integrations.agent_hub.hub_launch_env_path",
        lambda: hub / "launch.env",
    )
    monkeypatch.setattr(
        "arka.integrations.agent_hub.hub_mcp_path",
        lambda: hub / "mcp.json",
    )
    return {"hub": hub, "cfg": cfg}


def test_connect_writes_marker_and_env(connector_paths, monkeypatch):
    from arka.integrations import cli_connector as cc

    hub = connector_paths["hub"]
    (hub / "memory").mkdir(parents=True, exist_ok=True)
    (hub / "memory" / "context.md").write_text(
        "# Shared\n\n- Uses pytest\n",
        encoding="utf-8",
    )
    (hub / "launch.env").write_text('export ARKA_CONTEXT_MD="/tmp/context.md"\n', encoding="utf-8")

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    with patch("arka.integrations.agent_hub.sync_all") as mock_sync:
        mock_sync.return_value = {"ok": True}
        with patch("arka.integrations.agent_hub.write_launch_env_file") as mock_write:
            mock_write.return_value = hub / "launch.env"
            with patch("arka.integrations.agent_hub.launch_env") as mock_env:
                mock_env.return_value = {
                    "ARKA_HUB_DIR": str(hub),
                    "ARKA_CONTEXT_MD": str(hub / "memory" / "context.md"),
                    "ARKA_MCP_CONFIG": str(hub / "mcp.json"),
                    "ARKA_MEMORY_DIR": str(hub / "memory"),
                }
                payload = cc.connect(sync=True)

    assert payload["ok"] is True
    assert cc.is_connected()
    assert cc.marker_path().is_file()
    assert cc.context_md_path().is_file()


def test_shared_context_block_filters_goal(connector_paths, monkeypatch):
    from arka.integrations import cli_connector as cc

    hub = connector_paths["hub"]
    (hub / "memory").mkdir(parents=True, exist_ok=True)
    (hub / "memory" / "context.md").write_text(
        "\n".join(
            [
                "# Shared context",
                "",
                "## Facts",
                "",
                "- Project uses pytest",
                "- Deploy target is Railway",
            ]
        ),
        encoding="utf-8",
    )
    monkeypatch.setenv("ARKA_CLI_CONNECTOR", "1")
    block = cc.shared_context_block("pytest tests", limit_chars=500)
    assert "pytest" in block.lower()
    assert "Shared context" in block


def test_cli_connect_command(monkeypatch, capsys, connector_paths):
    from arka.integrations import cli_connector as cc

    monkeypatch.setattr(
        cc,
        "connect",
        lambda **kwargs: {
            "ok": True,
            "context_md": str(connector_paths["hub"] / "memory" / "context.md"),
            "launch_env": str(connector_paths["hub"] / "launch.env"),
            "context_exists": True,
        },
    )
    assert cc.main(["connect"]) == 0
    out = capsys.readouterr().out
    assert "connected" in out.lower()


def test_mcp_connector_status_handler():
    from arka.integrations.mcp_server import _handle_arka_connector

    with patch("arka.integrations.cli_connector.status_payload", return_value={"connected": False}):
        raw = _handle_arka_connector({"action": "status"})
    assert json.loads(raw)["connected"] is False


def test_route_cli_connector():
    from arka.integrations.cli_connector import nl_to_argv
    from arka.routing.symbolic import route_cli_connector

    assert nl_to_argv("connect shared context for cli") == ["connect"]
    assert nl_to_argv("suggest cli to connect") == ["suggest"]
    assert route_cli_connector("wire terminal to shared context") == "connector connect"
    assert route_cli_connector("suggest cli to connect") == "connector suggest"


def test_agent_catalog_includes_cli():
    from arka.integrations.agent_hub import AGENTS, list_agents

    keys = {k for k, _ in list_agents()}
    assert "cli" in keys
    assert AGENTS["cli"]["name"] == "Arka CLI"
