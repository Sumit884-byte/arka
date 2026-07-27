"""Tests for unified `arka dev` developer loop."""

from __future__ import annotations

import json
from pathlib import Path
from unittest import mock

import pytest

from arka.agent import dev_cli


def test_route_command():
    assert dev_cli.route_command("dev ship") == "dev ship"
    assert dev_cli.route_command("prepare to commit") == "dev ship"
    assert dev_cli.route_command("run dev checks") == "dev ship"
    assert dev_cli.route_command("dev test") == "dev test"
    assert dev_cli.route_command("dev review") == "dev review"
    assert dev_cli.route_command("dev init .") == "dev init ."
    assert dev_cli.route_command("dev tui") == "dev tui"
    assert dev_cli.route_command("what is python") == ""


def test_main_help():
    assert dev_cli.main([]) == 0


def test_dev_test_json(monkeypatch, tmp_path, capsys):
    payload = {"ok": True, "results": [{"name": "ruff", "ok": True, "exit_code": 0}]}
    monkeypatch.setattr("arka.agent.dev_tools.run_ci", lambda root, **kwargs: payload)
    monkeypatch.setattr(
        "arka.agent.dev_tools.ci_text",
        lambda root, **kwargs: "CI ok",
    )
    assert dev_cli.main(["test", str(tmp_path), "--json"]) == 0
    out = json.loads(capsys.readouterr().out)
    assert out["ok"] is True
    assert out["results"][0]["name"] == "ruff"


def test_dev_ship_passes(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("arka.agent.dev_cli.review_text", lambda root, **kwargs: "Review scope: staged\n")
    monkeypatch.setattr(
        "arka.agent.dev_cli.run_ci",
        lambda root, **kwargs: {"ok": True, "results": [{"name": "ruff", "ok": True, "exit_code": 0}]},
    )
    monkeypatch.setattr("arka.agent.dev_cli.ci_text", lambda root, **kwargs: "CI: ok")
    assert dev_cli.main(["ship", str(tmp_path)]) == 0
    output = capsys.readouterr().out
    assert "Review scope: staged" in output
    assert "ship checks passed" in output


def test_dev_ship_fails_on_ci(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("arka.agent.dev_cli.review_text", lambda root, **kwargs: "Review scope: staged\n")
    monkeypatch.setattr(
        "arka.agent.dev_cli.run_ci",
        lambda root, **kwargs: {"ok": False, "results": [{"name": "pytest", "ok": False, "exit_code": 1}]},
    )
    monkeypatch.setattr("arka.agent.dev_cli.ci_text", lambda root, **kwargs: "CI: failed")
    assert dev_cli.main(["ship", str(tmp_path)]) == 1
    assert "CI gates failed" in capsys.readouterr().out


def test_run_ship_json(monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("arka.agent.dev_cli.review_text", lambda root, **kwargs: "Review scope: staged\n")
    monkeypatch.setattr(
        "arka.agent.dev_cli.run_ci",
        lambda root, **kwargs: {"ok": True, "results": []},
    )
    assert dev_cli.run_ship(tmp_path, json_output=True) == 0
    payload = json.loads(capsys.readouterr().out)
    assert payload["ok"] is True
    assert payload["review_ok"] is True
    assert payload["ci_ok"] is True


def test_router_symbolic_dev_ship():
    from arka.router import route

    with mock.patch.dict("os.environ", {"ROUTE_MODE": "symbolic_only"}, clear=False):
        result = route("prepare to commit")
    assert result.skill.startswith("dev ship")
