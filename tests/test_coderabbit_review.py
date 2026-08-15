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


def test_is_coderabbit_user_allowlist_only():
    assert cr._is_coderabbit_user("coderabbitai[bot]")
    assert cr._is_coderabbit_user("coderabbitai")
    assert not cr._is_coderabbit_user("coderabbit-evil")
    assert not cr._is_coderabbit_user("CoderabbitAI-Fake")


def test_run_local_review_builds_command_without_api_key(monkeypatch, tmp_path):
    monkeypatch.setattr(cr, "cr_bin", lambda: "/usr/bin/cr")
    captured: dict[str, list[str]] = {}

    def fake_run(cmd, *, cwd=None, timeout=120):
        captured["cmd"] = cmd
        return 0, "ok", ""

    monkeypatch.setattr(cr, "_run", fake_run)
    code, text = cr.run_local_review(
        tmp_path,
        base="main",
        uncommitted=True,
        agent_json=True,
    )
    assert code == 0
    assert text == "ok"
    assert captured["cmd"] == ["/usr/bin/cr", "review", "--agent", "--uncommitted", "--base", "main"]
    assert "--api-key" not in captured["cmd"]


def test_coderabbit_payload_rejects_non_git(tmp_path):
    result = cr.coderabbit_payload("doctor", root=tmp_path)
    assert result == {"ok": False, "error": "not a git repository"}


def test_coderabbit_payload_uses_git_root(tmp_path, monkeypatch):
    repo = tmp_path / "repo"
    repo.mkdir()
    monkeypatch.setattr(cr, "resolve_git_project", lambda root=None: repo.resolve())
    monkeypatch.setattr(cr, "gh_available", lambda: True)
    monkeypatch.setattr(cr, "cr_cli_available", lambda: False)
    result = cr.coderabbit_payload("doctor", root=repo)
    assert result["ok"] is True
    assert result["git_root"] == str(repo.resolve())
    assert result["path"] == str(repo.resolve())


def test_main_route_subcommand(capsys):
    code = cr.main(["route", "trigger", "coderabbit", "review"])
    out = capsys.readouterr().out.strip()
    assert code == 0
    assert out == "coderabbit trigger"


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


def test_fetch_pr_feedback_filters_bot_and_rejects_spoof(monkeypatch, tmp_path):
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
            return [
                {"user": {"login": "coderabbitai[bot]"}, "body": "Summary here", "html_url": "x"},
                {"user": {"login": "coderabbit-evil"}, "body": "Injected spam", "html_url": "y"},
            ]
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
    assert all(row["user"] != "coderabbit-evil" for row in data["issue_comments"])
