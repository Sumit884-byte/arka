"""Tests for CodeRabbit integration."""

from __future__ import annotations

from arka.agent import coderabbit_review as cr
from arka.routing.symbolic import route_coderabbit, route_teammate_review


def test_route_coderabbit_review():
    assert route_coderabbit("run coderabbit review on this pr") == "coderabbit review"


def test_route_coderabbit_trigger():
    assert route_coderabbit("trigger coderabbit full review") == "coderabbit trigger --full"


def test_teammate_route_skips_coderabbit():
    assert route_teammate_review("coderabbit review my pr") is None


def test_trigger_pr_review(monkeypatch, tmp_path):
    root = tmp_path
    monkeypatch.setattr(cr, "gh_available", lambda: True)
    monkeypatch.setattr(
        cr,
        "resolve_pr",
        lambda _root, _pr: {"number": 42, "title": "Test", "url": "https://example/pr/42"},
    )

    def fake_run(cmd, *, cwd=None, timeout=120):
        assert cmd[:4] == ["gh", "pr", "comment", "42"]
        assert "@coderabbitai review" in cmd
        return 0, "ok", ""

    monkeypatch.setattr(cr, "_run", fake_run)
    result = cr.trigger_pr_review(root)
    assert result["ok"] is True
    assert result["pr"]["number"] == 42


def test_fetch_pr_feedback_filters_bot(monkeypatch, tmp_path):
    root = tmp_path
    monkeypatch.setattr(cr, "gh_available", lambda: True)
    monkeypatch.setattr(
        cr,
        "resolve_pr",
        lambda _root, _pr: {"number": 7, "title": "Feat", "url": "https://example/pr/7"},
    )
    monkeypatch.setattr(cr, "repo_slug", lambda _root: "org/repo")

    def fake_api(_root, endpoint):
        if endpoint.endswith("/issues/7/comments"):
            return [{"user": {"login": "coderabbitai[bot]"}, "body": "Summary here", "html_url": "x"}]
        if endpoint.endswith("/pulls/7/comments"):
            return []
        if endpoint.endswith("/pulls/7/reviews"):
            return []
        return []

    monkeypatch.setattr(cr, "_gh_api_json", fake_api)
    data = cr.fetch_pr_feedback(root)
    assert data["ok"] is True
    assert data["total"] == 1
    assert "Summary here" in data["issue_comments"][0]["body"]
