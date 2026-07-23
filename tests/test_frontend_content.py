from __future__ import annotations

from arka.core import frontend_content


def test_guide_path_exists() -> None:
    assert frontend_content.guide_path() is not None


def test_auto_includes_for_frontend_goal(monkeypatch) -> None:
    monkeypatch.delenv("FRONTEND_CONTENT_GUIDE", raising=False)
    monkeypatch.setenv("FRONTEND_CONTENT_GUIDE_MODE", "auto")
    assert frontend_content.should_include("polish the landing page hero")
    assert not frontend_content.should_include("run pytest on backend")


def test_coding_mode(monkeypatch) -> None:
    monkeypatch.setenv("FRONTEND_CONTENT_GUIDE_MODE", "auto")
    assert frontend_content.should_include("fix parser", coding=True)


def test_context_contains_golden_rule(monkeypatch) -> None:
    monkeypatch.delenv("FRONTEND_CONTENT_GUIDE", raising=False)
    ctx = frontend_content.context_for("review dashboard UI copy")
    assert "Frontend content guide" in ctx
    assert "Golden rule" in ctx or "Show outcomes" in ctx


def test_guide_bans_dev_status_banners() -> None:
    body = frontend_content.read_guide(max_chars=20_000)
    assert "Database connected · API healthy · 8 posts loaded" in body
    assert "Dev / ops health banners" in body
    assert "8 posts ready" in body


def test_is_frontend_goal_status_banner() -> None:
    assert frontend_content.is_frontend_goal("remove the dev status banner from the UI")
    assert frontend_content.is_frontend_goal("fix status banner copy on health page")
    assert frontend_content.should_include("polish ui copy on status page")


def test_mcp_markdown_reads_frontend_guide_alias() -> None:
    from arka.integrations.mcp_server import _handle_arka_markdown

    text = _handle_arka_markdown({"action": "read", "path": "frontend-content-guide"})
    assert "Database connected · API healthy · 8 posts loaded" in text
    assert "Golden rule" in text


def test_memory_context_includes_frontend_guide(tmp_path, monkeypatch) -> None:
    from arka.agent import core as agent_core

    monkeypatch.setenv("PROJECT_RULES", "0")
    monkeypatch.setenv("FRONTEND_CONTENT_GUIDE", "1")
    monkeypatch.setenv("GOOGLE_DESIGN_GUIDE", "0")
    monkeypatch.setenv("FRONTEND_CONTENT_GUIDE_MODE", "auto")
    monkeypatch.setattr(agent_core, "_memory_context_body", lambda goal, limit=3: "")

    ctx = agent_core.memory_context_for("improve landing page copy")
    assert "Frontend content guide" in ctx
