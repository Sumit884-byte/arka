from __future__ import annotations

import json
from pathlib import Path

from arka.agent.video_capture import (
    DEFAULT_WALKTHROUGH_URL,
    dashboard_walkthrough_actions,
    load_actions,
    temporary_output,
)
from arka.routing.symbolic import route_capture_video


def test_dashboard_walkthrough_actions():
    steps = dashboard_walkthrough_actions("http://127.0.0.1:5173")
    assert steps[0]["url"] == "http://127.0.0.1:5173/"
    assert any(step.get("name") == "02-skills.png" for step in steps)


def test_load_actions(tmp_path: Path):
    path = tmp_path / "steps.json"
    path.write_text(json.dumps([{"type": "wait", "ms": 500}]))
    assert load_actions(path) == [{"type": "wait", "ms": 500}]


def test_temporary_output_is_unique_and_under_tempdir():
    first, second = temporary_output(), temporary_output()
    assert first != second
    assert Path(first).is_dir() and Path(second).is_dir()


def test_capture_rejects_unbounded_settle_time():
    from arka.agent.video_capture import capture

    try:
        capture("http://localhost:5173", settle_seconds=61)
    except ValueError as exc:
        assert "between 0 and 60" in str(exc)
    else:
        raise AssertionError("expected settle validation before browser startup")


def test_route_capture_video_with_url():
    routed = route_capture_video("record a walkthrough video of https://example.com")
    assert routed == "capture video https://example.com"


def test_route_capture_video_dashboard():
    routed = route_capture_video("capture walkthrough of the arka web dashboard")
    assert routed == f"capture video --walkthrough"


def test_default_walkthrough_url():
    assert DEFAULT_WALKTHROUGH_URL.startswith("http")


def test_capture_cli_subcommand_help(capsys):
    from arka.cli import main

    code = main(["capture", "video", "--help"])
    out = capsys.readouterr().out
    assert code == 0
    assert "--walkthrough" in out


def test_capture_cli_subcommand_walkthrough_flag(capsys, monkeypatch):
    from arka.cli import main

    monkeypatch.setattr(
        "arka.agent.video_capture.main",
        lambda argv: print(f"argv={argv}") or 0,
    )
    code = main(["capture", "video", "--walkthrough"])
    out = capsys.readouterr().out
    assert code == 0
    assert "--walkthrough" in out
