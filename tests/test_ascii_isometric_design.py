"""Tests for ASCII isometric landing page design guide."""

from __future__ import annotations

from arka.core import ascii_isometric_design, design_guides


def test_bundled_guide_path_exists() -> None:
    path = ascii_isometric_design.bundled_guide_path()
    assert path is not None
    assert path.name == "ascii-isometric-landing-page.md"


def test_auto_includes_for_isometric_goal(monkeypatch) -> None:
    monkeypatch.delenv("ASCII_ISOMETRIC_DESIGN_GUIDE", raising=False)
    monkeypatch.setenv("ASCII_ISOMETRIC_DESIGN_GUIDE_MODE", "auto")
    assert ascii_isometric_design.should_include("build ascii isometric developer landing page")
    assert not ascii_isometric_design.should_include("run pytest on backend")


def test_coding_mode_does_not_force_include(monkeypatch) -> None:
    monkeypatch.setenv("ASCII_ISOMETRIC_DESIGN_GUIDE_MODE", "auto")
    assert not ascii_isometric_design.should_include("fix parser", coding=True)


def test_context_contains_design_system(monkeypatch) -> None:
    monkeypatch.delenv("ASCII_ISOMETRIC_DESIGN_GUIDE", raising=False)
    ctx = ascii_isometric_design.context_for("pill nav segmented feature grid")
    assert "ASCII isometric landing page design system" in ctx
    assert "--accent-green" in ctx or "--bg-canvas" in ctx


def test_resolve_alias() -> None:
    resolved = ascii_isometric_design.resolve_alias("ascii-isometric-landing-page")
    assert resolved is not None
    assert resolved.endswith("ascii-isometric-landing-page.md")


def test_mcp_markdown_reads_alias() -> None:
    from arka.integrations.mcp_server import _handle_arka_markdown

    text = _handle_arka_markdown({"action": "read", "path": "ascii-isometric-landing-page"})
    assert "ASCII Isometric" in text or "isometric" in text.lower()
    assert "pill" in text.lower() or "segmented" in text.lower()


def test_md_doc_route_follow_ascii_isometric() -> None:
    from arka.agent.md_doc import route_command

    assert route_command("follow ascii isometric landing page guide") == (
        "md_doc read ascii-isometric-landing-page"
    )


def test_design_guides_merges_ascii_isometric(monkeypatch) -> None:
    monkeypatch.delenv("FRONTEND_CONTENT_GUIDE", raising=False)
    monkeypatch.delenv("GOOGLE_DESIGN_GUIDE", raising=False)
    monkeypatch.delenv("ASCII_ISOMETRIC_DESIGN_GUIDE", raising=False)
    ctx = design_guides.context_for("build ascii isometric saas landing with pill nav")
    assert "ASCII isometric landing page design system" in ctx
