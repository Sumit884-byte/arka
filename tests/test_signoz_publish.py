"""Tests for signoz_publish — NL parsing, routing, preflight, and mocked git/vercel/blog."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from arka.agent import signoz_publish as sp
from arka.integrations.mcp_server import _handle_arka_signoz_publish
from arka.routing.symbolic import route_signoz_publish


def _fake_preflight(tmp_path: Path, **overrides) -> sp.Preflight:
    base = sp.Preflight(
        root=str(tmp_path),
        branch="main",
        remote="origin",
        has_changes=False,
        git=True,
        gh=True,
        vercel=True,
        blog_exists=False,
        blog_path=str(tmp_path / "signoz/BLOG.md"),
        vercel_dir=str(tmp_path / "landing"),
        errors=[],
        warnings=[],
    )
    for key, val in overrides.items():
        setattr(base, key, val)
    return base


def test_nl_to_argv_publish_signoz():
    argv = sp.nl_to_argv("signoz publish push to github and deploy vercel update blog")
    assert "--generate-blog" in argv


def test_nl_to_argv_with_topic_and_yes():
    argv = sp.nl_to_argv("publish signoz topic: new demo screenshots and go ahead")
    assert "--topic" in argv
    assert "--yes" in argv


def test_nl_to_argv_unrelated():
    assert sp.nl_to_argv("summarize README") == []


def test_route_signoz_publish():
    hit = route_signoz_publish("signoz publish push github vercel blog")
    assert hit is not None
    assert hit.startswith("signoz_publish")


def test_suggest_commit_message():
    root = Path("/tmp")
    msg = sp.suggest_commit_message(root, topic="demo video refresh")
    assert "demo video refresh" in msg


def test_generate_blog_fallback():
    with mock.patch("arka.llm.cli.llm_complete", return_value=""):
        body = sp.generate_blog_markdown(
            topic="New traces screenshot",
            existing="# Title\n\nExisting content.",
            diff_summary=" signoz/BLOG.md | 2 +++",
        )
    assert "New traces screenshot" in body
    assert "Title" in body


def test_preflight_git_repo(tmp_path: Path, monkeypatch):
    (tmp_path / ".git").mkdir()
    (tmp_path / "landing").mkdir()
    monkeypatch.setattr(sp, "which_bin", lambda name: "/usr/bin/" + name)
    monkeypatch.setattr(sp, "git_remote", lambda root: "origin")
    monkeypatch.setattr(sp, "git_branch", lambda root: "main")
    monkeypatch.setattr(sp, "git_porcelain", lambda root: "")
    pf = sp.preflight(tmp_path)
    assert pf.git is True
    assert pf.remote == "origin"


def test_preflight_no_git(tmp_path: Path):
    pf = sp.preflight(tmp_path)
    assert pf.git is False
    assert pf.errors


def test_write_blog_dry_run(tmp_path: Path):
    path = sp.write_blog(tmp_path, "# Test\n", dry_run=True)
    assert path == tmp_path / "signoz/BLOG.md"
    assert not path.is_file()


def test_write_blog_writes(tmp_path: Path):
    path = sp.write_blog(tmp_path, "# Test\n", dry_run=False)
    assert path.is_file()
    assert path.read_text(encoding="utf-8").startswith("# Test")


def test_build_plan_preview_requires_no_yes(tmp_path: Path, monkeypatch):
    (tmp_path / "landing").mkdir()
    (tmp_path / "signoz").mkdir()
    monkeypatch.setattr(sp, "repo_root", lambda start=None: tmp_path)
    monkeypatch.setattr(sp, "preflight", lambda root=None, **kw: _fake_preflight(tmp_path))

    import argparse

    args = argparse.Namespace(
        message="Update blog",
        m="Update blog",
        topic="",
        content="",
        content_text="",
        generate_blog=False,
        skip_blog=True,
        skip_git=False,
        skip_deploy=True,
        vercel_dir="landing",
        production=False,
        all_files=False,
        dry_run=False,
        yes=False,
        json=True,
    )
    plan = sp.build_plan(args, tmp_path)
    assert plan.commit_message == "Update blog"
    assert plan.git.get("dry_run") is True


def test_resolve_commit_message_requires_explicit_or_yes(tmp_path: Path):
    import argparse

    args = argparse.Namespace(message="", m="", yes=False, topic="")
    with pytest.raises(SystemExit, match="Commit message required"):
        sp.resolve_commit_message(args, tmp_path)


def test_git_stage_commit_push_dry_run(tmp_path: Path):
    result = sp.git_stage_commit_push(tmp_path, "test msg", dry_run=True)
    assert result["dry_run"] is True
    assert result["commit"] == "test msg"


def test_vercel_deploy_dry_run(tmp_path: Path):
    (tmp_path / "landing").mkdir()
    result = sp.vercel_deploy(tmp_path, dry_run=True, production=True)
    assert result["dry_run"] is True
    assert "--prod" in result["command"]


def test_vercel_deploy_missing_cli(tmp_path: Path, monkeypatch):
    (tmp_path / "landing").mkdir()
    monkeypatch.setattr(sp, "which_bin", lambda name: None if name == "vercel" else "/usr/bin/git")
    with pytest.raises(SystemExit, match="vercel CLI not found"):
        sp.vercel_deploy(tmp_path, dry_run=False)


def test_run_publish_preview(tmp_path: Path, monkeypatch, capsys):
    (tmp_path / "landing").mkdir()
    (tmp_path / "signoz").mkdir()
    monkeypatch.setattr(sp, "repo_root", lambda start=None: tmp_path)
    monkeypatch.setattr(sp, "preflight", lambda root=None, **kw: _fake_preflight(tmp_path))

    import argparse

    args = argparse.Namespace(
        message="Preview only",
        m="Preview only",
        topic="",
        content="",
        content_text="",
        generate_blog=False,
        skip_blog=True,
        skip_git=True,
        skip_deploy=True,
        vercel_dir="landing",
        production=False,
        all_files=False,
        dry_run=False,
        yes=False,
        json=False,
    )
    sp.run_publish(args, tmp_path)
    out = capsys.readouterr().out
    assert "Signoz publish plan" in out


def test_run_publish_dry_run_full_mock(tmp_path: Path, monkeypatch):
    (tmp_path / "landing").mkdir()
    blog = tmp_path / "signoz/BLOG.md"
    blog.parent.mkdir(parents=True, exist_ok=True)
    blog.write_text("# Existing\n", encoding="utf-8")
    monkeypatch.setattr(sp, "repo_root", lambda start=None: tmp_path)
    monkeypatch.setattr(sp, "preflight", lambda root=None, **kw: _fake_preflight(tmp_path))
    monkeypatch.setattr(sp, "which_bin", lambda name: name)

    import argparse

    args = argparse.Namespace(
        message="",
        m="",
        topic="observability update",
        content="",
        content_text="",
        generate_blog=True,
        skip_blog=False,
        skip_git=False,
        skip_deploy=False,
        vercel_dir="landing",
        production=False,
        all_files=True,
        dry_run=True,
        yes=True,
        json=False,
    )
    with mock.patch("arka.agent.signoz_publish.generate_blog_markdown", return_value="# Updated blog\n"):
        plan = sp.run_publish(args, tmp_path)
    assert plan.dry_run is True
    assert plan.blog.get("would_write") or plan.blog.get("mode") == "generate"


def test_skill_manifest():
    manifest = json.loads(
        (Path(__file__).parents[1] / "src/arka/skills/signoz_publish/skill.json").read_text()
    )
    assert manifest["name"] == "signoz_publish"
    assert "git" in manifest["requires"]["bins"]


def test_mcp_check():
    raw = _handle_arka_signoz_publish({"action": "check"})
    payload = json.loads(raw)
    assert "preflight" in payload


def test_mcp_parse():
    raw = _handle_arka_signoz_publish(
        {"action": "parse", "text": "signoz publish topic demo and go ahead"}
    )
    payload = json.loads(raw)
    assert "signoz_publish" in payload.get("command", "")


def test_mcp_dry_run(tmp_path: Path, monkeypatch):
    (tmp_path / "landing").mkdir()
    monkeypatch.setattr(sp, "repo_root", lambda start=None: tmp_path)
    monkeypatch.setattr(sp, "preflight", lambda root=None, **kw: _fake_preflight(tmp_path))

    raw = _handle_arka_signoz_publish(
        {
            "action": "dry-run",
            "message": "Test commit",
            "skip_blog": True,
            "skip_deploy": True,
        }
    )
    payload = json.loads(raw)
    assert payload.get("dry_run") is True
    assert payload.get("commit_message") == "Test commit"
