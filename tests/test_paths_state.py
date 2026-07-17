"""Tests for consolidated runtime state under .arka/."""

from __future__ import annotations

import json

import pytest


@pytest.fixture
def checkout(tmp_path, monkeypatch):
    """Simulate an editable Arka checkout."""
    (tmp_path / "pyproject.toml").write_text("[project]\nname = 'arka'\n", encoding="utf-8")
    pkg = tmp_path / "src" / "arka"
    pkg.mkdir(parents=True)
    (pkg / "paths.py").write_text("# stub\n", encoding="utf-8")
    monkeypatch.setenv("CONFIG_DIR", "")
    monkeypatch.delenv("CONFIG_DIR", raising=False)
    monkeypatch.delenv("ARKA_CONFIG_DIR", raising=False)
    monkeypatch.setattr("arka.paths.package_dir", lambda: pkg)
    return tmp_path


def test_config_dir_uses_dot_arka_in_checkout(checkout):
    from arka.paths import checkout_state_dir, config_dir

    assert checkout_state_dir() == checkout / ".arka"
    assert config_dir() == checkout / ".arka"


def test_config_dir_respects_override(checkout, monkeypatch):
    from arka.paths import config_dir

    custom = checkout / "custom-config"
    monkeypatch.setenv("CONFIG_DIR", str(custom))
    assert config_dir() == custom


def test_migrate_scattered_state_from_repo_root(checkout):
    from arka.paths import config_dir, migrate_scattered_state

    (checkout / "personalize.json").write_text('{"interests": []}\n', encoding="utf-8")
    (checkout / "mcp.json").write_text('{"mcpServers": {}}\n', encoding="utf-8")
    (checkout / "message-sessions").mkdir()
    (checkout / "message-sessions" / "cli_default.json").write_text("[]\n", encoding="utf-8")
    (checkout / "hub").mkdir()
    (checkout / "hub" / "adapters").mkdir()
    (checkout / "hub" / "adapters" / "cursor_mcp_snippet.json").write_text("{}\n", encoding="utf-8")
    (checkout / "hub" / "agents.json").write_text('{"version": 1}\n', encoding="utf-8")
    (checkout / "hub" / "memory").mkdir()
    (checkout / "hub" / "memory" / "summary.json").write_text("{}\n", encoding="utf-8")

    moved = migrate_scattered_state()
    target = config_dir()

    assert (target / "personalize.json").is_file()
    assert (target / "mcp.json").is_file()
    assert (target / "message-sessions" / "cli_default.json").is_file()
    assert (target / "hub" / "agents.json").is_file()
    assert (target / "hub" / "memory" / "summary.json").is_file()
    assert not (checkout / "personalize.json").exists()
    assert (checkout / "hub" / "adapters" / "cursor_mcp_snippet.json").is_file()
    assert len(moved) >= 5


def test_migrate_is_idempotent(checkout):
    from arka.paths import migrate_scattered_state

    (checkout / "repo-index.json").write_text('{"repos": {}}\n', encoding="utf-8")
    first = migrate_scattered_state()
    second = migrate_scattered_state()
    assert first
    assert second == []


def test_ensure_layout_runs_migration(checkout, monkeypatch):
    from arka.paths import config_dir, ensure_layout

    (checkout / "code-project.json").write_text(
        json.dumps({"root": str(checkout)}) + "\n",
        encoding="utf-8",
    )
    monkeypatch.setattr("arka.platform_info.ensure_platform_cache", lambda: None)
    ensure_layout()
    assert (config_dir() / "code-project.json").is_file()
