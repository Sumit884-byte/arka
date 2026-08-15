"""Tests for interactive blog brief interview."""

from __future__ import annotations

from arka.integrations.blog_interview import (
    extract_topic_from_text,
    infer_brief_from_context,
    interview_brief,
    missing_brief_fields,
    prepare_blog_brief,
)
from arka.integrations.project_docs import route_command


def test_extract_topic_from_text() -> None:
    assert extract_topic_from_text("write a blog post about arka-agent") == "arka-agent"
    assert extract_topic_from_text("write blog about my hackathon project") == "my hackathon project"


def test_route_write_blog() -> None:
    hit = route_command("write blog about arka-agent")
    assert hit is not None
    assert "project_docs blog" in hit
    assert "--apply" in hit
    assert "--prompt" in hit


def test_infer_brief_from_context(tmp_path) -> None:
    root = tmp_path / "demo"
    root.mkdir()
    (root / "pyproject.toml").write_text('[project]\nname = "demo-app"\n', encoding="utf-8")
    (root / "README.md").write_text("# Demo\n\nhttps://demo.example.com\n", encoding="utf-8")
    ctx = {
        "root": str(root),
        "existing_readme": (root / "README.md").read_text(encoding="utf-8"),
        "existing_blog": "",
        "recent_commits": ["abc1234 Add routing"],
    }
    brief = infer_brief_from_context(ctx, user_text="write blog about demo-app")
    assert brief.topic == "demo-app"
    assert brief.demo_url == "https://demo.example.com"


def test_missing_brief_fields() -> None:
    from arka.integrations.blog_interview import BlogBrief

    brief = BlogBrief(topic="x")
    assert "audience" in missing_brief_fields(brief)


def test_interview_assumes_defaults() -> None:
    from arka.integrations.blog_interview import BlogBrief

    brief = BlogBrief(topic="Arka")
    updated, asked = interview_brief(brief, interactive=False, assume_defaults=True)
    assert updated.audience == "developers"
    assert asked == []


def test_prepare_blog_brief_non_interactive(tmp_path) -> None:
    root = tmp_path
    (root / "README.md").write_text("# Hi", encoding="utf-8")
    ctx = {"root": str(root), "existing_readme": "# Hi", "existing_blog": "", "recent_commits": []}
    brief, focus = prepare_blog_brief(
        ctx,
        user_text="write blog about arka",
        assume_defaults=True,
        interactive=False,
    )
    assert brief.topic
    assert "Topic:" in focus
