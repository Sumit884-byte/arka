from __future__ import annotations

from pathlib import Path

from arka.core import design_guides, google_design


def test_bundled_google_design_path_exists() -> None:
    path = google_design.bundled_guide_path()
    assert path is not None
    assert path.name == "google-design.md"


def test_guide_path_defaults_to_bundled() -> None:
    assert google_design.guide_path() is not None
    assert google_design.guide_path().name == "google-design.md"


def test_auto_includes_for_design_goal(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_DESIGN_GUIDE", raising=False)
    monkeypatch.setenv("GOOGLE_DESIGN_GUIDE_MODE", "auto")
    assert google_design.should_include("build dashboard UI with design tokens")
    assert not google_design.should_include("run pytest on backend")


def test_coding_mode(monkeypatch) -> None:
    monkeypatch.setenv("GOOGLE_DESIGN_GUIDE_MODE", "auto")
    assert google_design.should_include("fix parser", coding=True)


def test_context_contains_priority_order(monkeypatch) -> None:
    monkeypatch.delenv("GOOGLE_DESIGN_GUIDE", raising=False)
    ctx = google_design.context_for("polish landing page layout")
    assert "Google DESIGN.md guide" in ctx
    assert "Priority order" in ctx or "Project `DESIGN.md`" in ctx


def test_resolve_alias_google_design() -> None:
    resolved = google_design.resolve_alias("google-design")
    assert resolved is not None
    assert resolved.endswith("google-design.md")


def test_resolve_alias_design_md_prefers_project(tmp_path: Path) -> None:
    project = tmp_path / "DESIGN.md"
    project.write_text("---\nname: Test\n---\n## Overview\nTest project design.\n", encoding="utf-8")
    resolved = google_design.resolve_alias("design.md", cwd=tmp_path)
    assert resolved == str(project)


def test_mcp_markdown_reads_google_design_alias() -> None:
    from arka.integrations.mcp_server import _handle_arka_markdown

    text = _handle_arka_markdown({"action": "read", "path": "google-design"})
    assert "Google DESIGN.md guide" in text or "DESIGN.md" in text
    assert "Token schema" in text or "YAML front matter" in text


def test_md_doc_route_follow_google_design() -> None:
    from arka.agent.md_doc import route_command

    assert route_command("follow google design.md") == "md_doc read google-design"


def test_design_guides_merges_both(monkeypatch) -> None:
    monkeypatch.delenv("FRONTEND_CONTENT_GUIDE", raising=False)
    monkeypatch.delenv("GOOGLE_DESIGN_GUIDE", raising=False)
    ctx = design_guides.context_for("improve landing page UI")
    assert "Frontend content guide" in ctx
    assert "Google DESIGN.md guide" in ctx


def test_memory_context_includes_google_design(tmp_path, monkeypatch) -> None:
    from arka.agent import core as agent_core

    monkeypatch.setenv("PROJECT_RULES", "0")
    monkeypatch.setenv("FRONTEND_CONTENT_GUIDE", "1")
    monkeypatch.setenv("GOOGLE_DESIGN_GUIDE", "1")
    monkeypatch.setenv("FRONTEND_CONTENT_GUIDE_MODE", "auto")
    monkeypatch.setenv("GOOGLE_DESIGN_GUIDE_MODE", "auto")
    monkeypatch.setattr(agent_core, "_memory_context_body", lambda goal, limit=3: "")

    ctx = agent_core.memory_context_for("build settings page UI")
    assert "Google DESIGN.md guide" in ctx
