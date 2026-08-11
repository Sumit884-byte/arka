"""Tests for verify-after-fix agent guidance."""

from __future__ import annotations

from arka.core import fix_verify
from arka.integrations.mcp_local_files import agent_execution_rules_payload


def test_compact_rule_enabled():
    rule = fix_verify.compact_rule()
    assert "verification" in rule.lower()
    assert "fixed" in rule.lower()


def test_context_for_includes_compact_rule():
    ctx = fix_verify.context_for("fix the bug")
    assert ctx == fix_verify.compact_rule()


def test_disabled(monkeypatch):
    monkeypatch.setenv("FIX_VERIFY_BIAS", "0")
    assert fix_verify.compact_rule() == ""
    assert fix_verify.context_for("fix") == ""


def test_memory_context_includes_fix_verify(monkeypatch):
    from arka.agent import core as agent_core

    monkeypatch.setenv("FIX_VERIFY_BIAS", "1")
    monkeypatch.setenv("PROJECT_RULES", "0")
    monkeypatch.setattr(
        agent_core, "_memory_context_body", lambda goal, limit=3: "local memory"
    )

    ctx = agent_core.memory_context_for("fix failing test")
    assert "verification" in ctx.lower()
    assert "local memory" in ctx


def test_agent_execution_rules_payload():
    payload = agent_execution_rules_payload()
    assert payload["verify_after_fix"]["steps"]
    assert "fixed" in payload["verify_after_fix"]["notice"].lower()
    assert any(row["id"] == "verify_after_fix" for row in payload["rules"])
