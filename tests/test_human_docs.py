"""Tests for human_docs bias and routing."""

from arka.core.human_docs import (
    compact_rule,
    context_for,
    is_human_doc_goal,
    should_include,
    suggest_output_path,
    wants_file_write,
)
from arka.routing.symbolic import route_human_docs


def test_compact_rule_enabled():
    assert "README" in compact_rule()
    assert "not chat" in compact_rule()


def test_should_include_always_by_default():
    assert should_include("") is True
    assert should_include("fix a bug") is True


def test_is_human_doc_goal():
    assert is_human_doc_goal("write a README for this project")
    assert is_human_doc_goal("make the changelog sound human")
    assert not is_human_doc_goal("what is 2+2")


def test_wants_file_write():
    assert wants_file_write("draft a README for arka")
    assert wants_file_write("update the contributing guide")


def test_suggest_output_path():
    assert suggest_output_path("write changelog").endswith("CHANGELOG.md")
    assert suggest_output_path("update contributing").endswith("CONTRIBUTING.md")
    assert suggest_output_path("project overview").endswith("README.md")


def test_context_for_includes_compact_rule():
    ctx = context_for("random question")
    assert "Human-facing docs" in ctx


def test_context_for_expands_on_readme_goal():
    ctx = context_for("write a human sounding README")
    assert "Human docs guide" in ctx or "Golden rule" in ctx


def test_route_human_docs():
    hit = route_human_docs("write a human sounding README for this repo")
    assert hit is not None
    assert hit.startswith("human_docs write")
    assert hit.endswith("--apply")


def test_route_human_docs_write_readme_applies():
    hit = route_human_docs("write readme for this project")
    assert hit is not None
    assert "human_docs write" in hit
    assert "--apply" in hit


def test_route_human_docs_preview_skips_apply():
    hit = route_human_docs("preview readme for this project")
    assert hit is not None
    assert "--apply" not in hit


def test_match_command_prefers_human_docs_route():
    from arka.agent.skills import match_command

    hit = match_command("write readme for this project")
    assert hit.startswith("human_docs write")
    assert "--apply" in hit
    assert hit != "human_docs for this project"


def test_route_human_docs_skips_unrelated():
    assert route_human_docs("what is the weather") is None
