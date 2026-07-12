"""Tests for Cursor-style project rules context."""

from __future__ import annotations

import json

from arka.core import project_rules
from arka.integrations.mcp_server import _handle_arka_project_rules


def test_collect_and_context(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_RULES", "1")
    monkeypatch.delenv("PROJECT_RULES_ROOT", raising=False)

    (tmp_path / "AGENTS.md").write_text("# Agents\nPrefer pytest for verification.\n", encoding="utf-8")
    rules = tmp_path / ".cursor" / "rules"
    rules.mkdir(parents=True)
    (rules / "python.mdc").write_text("Use type hints on public APIs.\n", encoding="utf-8")

    listed = project_rules.list_rules(root=tmp_path)
    assert {row["label"] for row in listed} == {"AGENTS.md", ".cursor/rules/python.mdc"}

    ctx = project_rules.context_for("pytest verification", root=tmp_path, limit_chars=2000)
    assert "Project rules" in ctx
    assert "Prefer pytest" in ctx
    assert "type hints" in ctx

    status = project_rules.status(root=tmp_path)
    assert status["enabled"] is True
    assert status["files"] == 2


def test_disabled(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_RULES", "0")
    (tmp_path / "AGENTS.md").write_text("secret rules", encoding="utf-8")
    assert project_rules.context_for("x", root=tmp_path) == ""


def test_mcp_project_rules(tmp_path, monkeypatch):
    monkeypatch.setenv("PROJECT_RULES", "1")
    (tmp_path / "CLAUDE.md").write_text("Keep diffs small.\n", encoding="utf-8")

    listed = json.loads(
        _handle_arka_project_rules({"action": "list", "root": str(tmp_path)})
    )
    assert listed[0]["label"] == "CLAUDE.md"

    ctx = _handle_arka_project_rules(
        {"action": "context", "root": str(tmp_path), "goal": "diff"}
    )
    assert "Keep diffs small" in ctx

    status = json.loads(
        _handle_arka_project_rules({"action": "status", "root": str(tmp_path)})
    )
    assert status["files"] == 1


def test_memory_context_includes_project_rules(tmp_path, monkeypatch):
    from arka.agent import core as agent_core

    monkeypatch.setenv("PROJECT_RULES", "1")
    monkeypatch.setenv("PROJECT_RULES_ROOT", str(tmp_path))
    (tmp_path / "AGENTS.md").write_text("Always run focused tests.\n", encoding="utf-8")
    monkeypatch.setattr(
        agent_core, "_memory_context_body", lambda goal, limit=3: "local memory"
    )

    ctx = agent_core.memory_context_for("run tests")
    assert "Always run focused tests" in ctx
    assert "local memory" in ctx
