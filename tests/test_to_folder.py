"""Tests for to-folder navigation routing and resolution."""

from __future__ import annotations

import os
import shlex
import shutil
import subprocess
from pathlib import Path

import pytest

from arka.core import folder_cache
from arka.core.to_folder import nl_to_argv, parse_folder_name, resolve_folder, route_command
from arka.router import route

REPO = Path(__file__).resolve().parents[1]
FISH_CFG = REPO / "src" / "arka" / "fish" / "config.fish"


def test_parse_folder_name_direct() -> None:
    assert parse_folder_name("to Downloads") == "Downloads"
    assert parse_folder_name("TO Documents") == "Documents"


def test_parse_folder_name_go_to() -> None:
    assert parse_folder_name("go to Downloads") == "Downloads"
    assert parse_folder_name("go to Downloads folder") == "Downloads"
    assert parse_folder_name("cd to folder Projects") == "Projects"
    assert parse_folder_name("navigate to the Desktop folder") == "Desktop"


def test_parse_folder_name_rejects_convert() -> None:
    assert parse_folder_name("convert video.mp4 to gif") is None
    assert parse_folder_name("remind me to go to gym") is None


def test_route_command() -> None:
    assert route_command("to Downloads") == "to Downloads"
    assert route_command("go to Pictures folder") == "to Pictures"
    assert route_command("arka to Downloads") == "to Downloads"
    assert route_command("arka go to Downloads folder") == "to Downloads"


def test_parse_folder_name_arka_prefix() -> None:
    assert parse_folder_name("arka to Downloads") == "Downloads"
    assert parse_folder_name("arka go to Downloads folder") == "Downloads"


def test_tech_stack_does_not_steal_folder_navigation() -> None:
    from arka.agent.tech_stack import extract_project_name, nl_to_argv

    for cmd in (
        "to Downloads",
        "'to Downloads'",
        "go to Downloads folder",
        "arka to Downloads",
    ):
        assert nl_to_argv(cmd) == [], cmd
        assert extract_project_name(cmd) is None, cmd


@pytest.mark.skipif(shutil.which("fish") is None, reason="fish shell not installed")
def test_fish_tech_stack_does_not_match_to_downloads() -> None:
    proc = _run_fish("_agent_build_tech_stack_cmd 'to Downloads'")
    assert proc.stdout.strip() == "", proc.stderr


@pytest.mark.skipif(shutil.which("fish") is None, reason="fish shell not installed")
def test_fish_agent_interpret_to_downloads() -> None:
    proc = _run_fish(
        "set -l interpreted ''; set -l cmd 'to Downloads'; "
        "if test -z \"$interpreted\"; and set -l to_cmd (_agent_route_to_folder \"$cmd\"); "
        "and test -n \"$to_cmd\"; set interpreted $to_cmd; end; "
        "if test -z \"$interpreted\"; and _agent_is_tech_stack_request \"$cmd\"; "
        "set interpreted (_agent_build_tech_stack_cmd \"$cmd\"); end; echo $interpreted"
    )
    assert proc.stdout.strip() == "to Downloads", proc.stderr


def test_nl_to_argv() -> None:
    assert nl_to_argv("to Downloads") == ["to", "Downloads"]
    assert nl_to_argv("go to Documents") == ["to", "Documents"]
    assert nl_to_argv("convert to pdf") == []


def test_resolve_folder(tmp_path: Path) -> None:
    target = tmp_path / "MyFolder"
    target.mkdir()
    assert resolve_folder("MyFolder", cwd=tmp_path, home=tmp_path) == target.resolve()


@pytest.fixture
def folder_cache_dir(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> Path:
    cfg = tmp_path / "config"
    cfg.mkdir()
    monkeypatch.setattr(folder_cache, "config_dir", lambda: cfg)
    monkeypatch.setenv("ARKA_FOLDER_CACHE", "1")
    if folder_cache.folder_cache_path().is_file():
        folder_cache.folder_cache_path().unlink()
    return cfg


def test_resolve_folder_dev_alias(tmp_path: Path, folder_cache_dir: Path) -> None:
    dev = tmp_path / "dev"
    dev.mkdir()
    assert resolve_folder("dev", cwd=tmp_path, home=tmp_path) == dev.resolve()


def test_resolve_folder_developer_alias(tmp_path: Path, folder_cache_dir: Path) -> None:
    developer = tmp_path / "Developer"
    developer.mkdir()
    assert resolve_folder("dev", cwd=tmp_path, home=tmp_path) == developer.resolve()


def test_resolve_folder_remembers_success(tmp_path: Path, folder_cache_dir: Path) -> None:
    dev = tmp_path / "dev"
    dev.mkdir()
    assert resolve_folder("dev", cwd=tmp_path, home=tmp_path) == dev.resolve()
    cached = folder_cache.get_cached_folder("dev")
    assert cached == dev.resolve()


def test_route_to_dev_not_tech_stack() -> None:
    hit = route("to dev")
    assert hit is not None
    assert hit.skill == "to dev"
    from arka.agent.tech_stack import extract_project_name, nl_to_argv as tech_nl_to_argv

    assert tech_nl_to_argv("to dev") == []
    assert extract_project_name("to dev") is None


def test_route_command_dev() -> None:
    assert route_command("to dev") == "to dev"
    assert route_command("arka to dev") == "to dev"


def test_fish_config_loads_to_function() -> None:
    text = FISH_CFG.read_text(encoding="utf-8")
    assert "function _arka_load_package_functions" in text
    assert "_arka_load_package_functions" in text
    assert "function _agent_route_to_folder" in text
    assert " create_folder list_folders show_folder to \\" in text


def _fish_env() -> dict[str, str]:
    env = os.environ.copy()
    env["ARKA_AUTO_REFETCH"] = "0"
    env["INSTALL_HOME"] = str(REPO)
    env["CONFIG_DIR"] = "/tmp/arka-to-folder-test"
    env["PYTHONPATH"] = str(REPO / "src")
    return env


def _run_fish(cmd: str) -> subprocess.CompletedProcess[str]:
    cfg = shlex.quote(str(FISH_CFG))
    inner = f"source {cfg}; {cmd}"
    return subprocess.run(
        ["fish", "-c", inner],
        capture_output=True,
        text=True,
        env=_fish_env(),
        timeout=30,
        check=False,
    )


@pytest.mark.skipif(shutil.which("fish") is None, reason="fish shell not installed")
def test_fish_to_function_loaded() -> None:
    proc = _run_fish("functions -q to; echo status=$status")
    assert "status=0" in proc.stdout.strip(), proc.stderr


@pytest.mark.skipif(shutil.which("fish") is None, reason="fish shell not installed")
def test_fish_guess_route_to_downloads() -> None:
    proc = _run_fish("_agent_guess_route 'to Downloads'")
    out = proc.stdout.strip()
    assert proc.returncode == 0, proc.stderr
    assert "to Downloads" in out
    assert "web_answer" not in out


@pytest.mark.skipif(shutil.which("fish") is None, reason="fish shell not installed")
def test_fish_guess_route_go_to_folder() -> None:
    proc = _run_fish("_agent_guess_route 'go to Downloads folder'")
    out = proc.stdout.strip()
    assert proc.returncode == 0, proc.stderr
    assert "to Downloads" in out
