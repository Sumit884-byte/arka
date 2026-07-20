"""Routing for arka capabilities / skills help requests."""

from __future__ import annotations

import io
import os
import shlex
import time
from contextlib import redirect_stderr, redirect_stdout
from unittest import mock

from arka.router import route, route_preview
from arka.routing.symbolic import route_help


def test_route_capabilities_exact():
    with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
        result = route("capabilities")
    assert result is not None
    assert result.skill == "capabilities"


def test_route_skills_maps_to_capabilities():
    with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
        result = route("skills")
    assert result is not None
    assert result.skill == "capabilities"


def test_route_help_stays_help():
    with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
        result = route("help")
    assert result is not None
    assert result.skill == "help"


def test_route_what_can_arka_do():
    with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
        result = route("what can arka do")
    assert result is not None
    assert result.skill == "capabilities"


def test_symbolic_route_help_nl():
    assert route_help("list your skills") == "capabilities"
    assert route_help("what can arka do") == "capabilities"
    assert route_help("help") == "help"


def test_route_preview_what_is_rust():
    with redirect_stderr(io.StringIO()):
        start = time.perf_counter()
        result = route_preview("what is rust?")
        elapsed = time.perf_counter() - start
    assert result is not None
    assert result.skill == "web_answer what is rust?"
    assert result.source == "offline"
    assert result.kind == "skill"
    assert elapsed < 1.0


def test_route_preview_what_is_rust_case_insensitive():
    with redirect_stderr(io.StringIO()):
        result = route_preview("what is Rust?")
    assert result is not None
    assert result.skill == "web_answer what is Rust?"
    assert result.source == "offline"


def test_route_preview_time_in_tokyo():
    with redirect_stderr(io.StringIO()):
        result = route_preview("time in tokyo")
    assert result is not None
    assert result.skill.startswith("timezone_convert")
    assert result.source == "offline"


def test_route_preview_capabilities():
    with redirect_stderr(io.StringIO()):
        result = route_preview("capabilities")
    assert result is not None
    assert result.skill == "capabilities"
    assert result.source == "offline"


def test_cli_route_preview_skips_fish(monkeypatch):
    from arka import cli

    fish_calls = []

    def _fish_preview(_text: str):
        fish_calls.append(_text)
        return None

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setattr("arka.fish_bridge.fish_route_preview", _fish_preview)
    buf = io.StringIO()
    with redirect_stdout(buf):
        assert cli.main(["route", "what is rust?"]) == 0
    assert not fish_calls
    output = buf.getvalue()
    assert "skill:" in output
    assert "web_answer what is rust?" in output
    assert "source: offline" in output
    assert "Answer" not in output
    assert "Model:" not in output


def test_fish_arka_route_preview_only():
    import shutil
    import subprocess
    from pathlib import Path

    fish = shutil.which("fish")
    if not fish:
        import pytest

        pytest.skip("fish not installed")

    repo = Path(__file__).resolve().parents[1]
    cfg = repo / "src" / "arka" / "fish" / "config.fish"
    env = os.environ.copy()
    env["ARKA_AUTO_REFETCH"] = "0"
    result = subprocess.run(
        [fish, "-c", f"source {shlex.quote(str(cfg))}; arka route 'what is rust?'"],
        capture_output=True,
        text=True,
        timeout=5,
        cwd=repo,
        env=env,
        check=False,
    )
    combined = result.stdout + result.stderr
    assert result.returncode == 0, combined
    assert "skill:" in result.stdout
    assert "source: offline" in result.stdout
    assert "Answer" not in combined
    assert "Model:" not in combined
    assert "💡 [AI routing]" not in combined


def test_cli_bare_nl_offline_bypasses_fish(monkeypatch):
    from arka import cli

    fish_calls = []

    def _fish_delegate(_args):
        fish_calls.append(_args)
        return 0

    monkeypatch.setenv("ARKA_AUTO_REFETCH", "0")
    monkeypatch.setattr("arka.cli.has_full_fish_agent", lambda: True)
    monkeypatch.setattr("arka.fish_bridge.delegate_to_fish", _fish_delegate)
    with mock.patch("arka.cli._run_portable", return_value=0) as portable:
        assert cli.main(["time in tokyo"]) == 0
    portable.assert_called_once()
    assert portable.call_args.args[0] == "time in tokyo"
    assert portable.call_args.args[1] is not None
    assert not fish_calls


def test_route_symbolic_prefers_offline_before_fish():
    from arka.router import Route

    fake_fish = Route("spotify_play song", source="fish", kind="skill")
    with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic"}, clear=False):
        with mock.patch("arka.router._route_via_fish", return_value=fake_fish):
            result = route("time in tokyo")
    assert result is not None
    assert result.skill.startswith("timezone_convert")
    assert result.source == "offline"


def test_route_ai_only_prefers_offline_before_fish():
    from arka.router import Route

    fake_fish = Route("timezone_convert 'time in tokyo'", source="fish", kind="skill")
    with mock.patch.dict(os.environ, {"ROUTE_MODE": "ai_only"}, clear=False):
        with mock.patch("arka.router._route_via_fish", return_value=fake_fish):
            result = route("time in tokyo")
    assert result is not None
    assert "--to Asia/Tokyo" in result.skill
    assert result.source == "offline"


def test_help_and_capabilities_outputs_differ():
    from arka.output import show_capabilities, show_help

    help_buf = io.StringIO()
    cap_buf = io.StringIO()
    with redirect_stdout(help_buf):
        show_help()
    with redirect_stdout(cap_buf):
        show_capabilities()

    help_text = help_buf.getvalue()
    cap_text = cap_buf.getvalue()
    assert help_text != cap_text
    assert "Arka Help" in help_text
    assert "Install & setup" in help_text
    assert "Arka Skills" in cap_text
    assert "Full list: arka help" in cap_text


def test_cli_help_and_capabilities_differ():
    from arka.cli import main

    help_buf = io.StringIO()
    cap_buf = io.StringIO()
    with redirect_stdout(help_buf):
        assert main(["help"]) == 0
    with redirect_stdout(cap_buf):
        assert main(["capabilities"]) == 0

    assert help_buf.getvalue() != cap_buf.getvalue()
