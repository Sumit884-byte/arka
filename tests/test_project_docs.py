"""Tests for project_docs — first-person README/blog sync."""

from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from arka.integrations.project_docs import (
    _split_blog_frontmatter,
    collect_context,
    route_command,
    status_payload,
    update_docs,
)
from arka.routing.symbolic import route_project_docs


def test_route_command_update_readme_from_changes() -> None:
    hit = route_command("update readme from code changes in first person")
    assert hit is not None
    assert hit.startswith("project_docs readme")
    assert "--apply" in hit


def test_route_command_blog_post_devto() -> None:
    hit = route_command("write blog in first person and publish to dev.to")
    assert hit is not None
    assert "project_docs blog" in hit
    assert "--post" in hit


def test_route_command_skips_unrelated() -> None:
    assert route_command("what is the weather") == ""


def test_route_project_docs_symbolic() -> None:
    hit = route_project_docs("sync project docs from git changes")
    assert hit is not None
    assert hit.startswith("project_docs")


def test_split_blog_frontmatter() -> None:
    raw = "---\ntitle: Hi\n---\n\nBody here\n"
    fm, body = _split_blog_frontmatter(raw)
    assert "title: Hi" in fm
    assert body == "Body here"


def test_status_payload_in_git_repo(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "README.md").write_text("# Hello\n", encoding="utf-8")
    payload = status_payload(tmp_path)
    assert payload["readme"]["exists"] is True
    assert payload["blog"]["exists"] is False


def test_collect_context_reads_existing_docs(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "README.md").write_text("# I built this\n", encoding="utf-8")
    (tmp_path / "blog-post.md").write_text("---\ntitle: T\n---\n\nPost\n", encoding="utf-8")
    ctx = collect_context(tmp_path)
    assert "I built this" in ctx["existing_readme"]
    assert "Post" in ctx["existing_blog"]


def test_update_docs_preview_without_llm(tmp_path: Path) -> None:
    (tmp_path / ".git").mkdir()
    (tmp_path / "README.md").write_text("# Old\n", encoding="utf-8")

    def fake_readme(*_a, **_k):
        return "# I rebuilt it\n", collect_context(tmp_path)

    def fake_blog(*_a, **_k):
        return "I learned a lot.\n", collect_context(tmp_path)

    with patch("arka.integrations.project_docs.generate_readme", side_effect=fake_readme):
        with patch("arka.integrations.project_docs.generate_blog", side_effect=fake_blog):
            result = update_docs(tmp_path, apply=False, blog=False)
    assert "readme" in result["docs"]
    assert "I rebuilt it" in result["docs"]["readme"]["body"]
