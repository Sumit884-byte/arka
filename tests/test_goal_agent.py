from pathlib import Path
import io
from contextlib import redirect_stderr
from unittest import mock


def test_parse_step_rejects_truncated_json():
    from arka.agent.goal import _parse_step

    parsed = _parse_step('{"status":"continue","cmd":"cd ar')
    assert parsed["status"] == "invalid"
    assert parsed["cmd"] == ""


def test_goal_command_prefix_is_normalized(tmp_path: Path):
    from arka.agent.goal import _parse_step

    parsed = _parse_step('{"status":"continue","cmd":"cd arka/ && git pull origin main"}')
    assert parsed["cmd"].startswith("cd arka/")


def test_git_commands_require_explicit_goal_authorization(tmp_path):
    from arka.agent.goal import _run_cmd

    code, output = _run_cmd("git status", tmp_path, auto_yes=True)
    assert code == 2
    assert "explicit user authorization" in output


def test_recursive_coding_tui_launch_is_blocked(tmp_path):
    from arka.agent.goal import _run_cmd

    code, output = _run_cmd("arka coding-tui .", tmp_path, auto_yes=True)
    assert code == 2
    assert "recursive Arka agent launch" in output


def test_git_commands_run_when_goal_authorizes_them(tmp_path):
    import subprocess

    from arka.agent.goal import _run_cmd

    subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)
    code, output = _run_cmd("git status --short", tmp_path, auto_yes=True, git_allowed=True)
    assert code == 0


def test_strip_leading_cd_chain_removes_repo_prefix(tmp_path: Path):
    from arka.agent.goal import _strip_leading_cd_chain

    repo = tmp_path / "arka"
    repo.mkdir()
    assert _strip_leading_cd_chain("cd arka/ && pytest tests/", repo) == "pytest tests/"
    assert _strip_leading_cd_chain("cd arka && git status", repo) == "git status"
    assert _strip_leading_cd_chain("cd . && ls", repo) == "ls"


def test_strip_leading_cd_chain_keeps_parent_navigation(tmp_path: Path):
    from arka.agent.goal import _strip_leading_cd_chain

    repo = tmp_path / "arka"
    repo.mkdir()
    assert _strip_leading_cd_chain("cd .. && ls", repo) == "cd .. && ls"


def test_is_standalone_cd_detects_bare_cd_commands():
    from arka.agent.goal import _is_standalone_cd

    assert _is_standalone_cd("cd arka")
    assert _is_standalone_cd("cd .")
    assert not _is_standalone_cd("cd arka/ && pytest")
    assert not _is_standalone_cd("pytest tests/")


def test_run_goal_continues_after_two_blocked_cd_commands(tmp_path: Path):
    from arka.agent.goal import run_goal

    responses = [
        '{"status":"continue","cmd":"cd arka","why":"navigate"}',
        '{"status":"continue","cmd":"cd .","why":"confirm cwd"}',
        '{"status":"done","cmd":"","why":"done"}',
    ]
    stderr = io.StringIO()
    with (
        mock.patch("arka.agent.goal._llm", side_effect=responses),
        mock.patch("arka.agent.goal._dir_context", return_value=("", "")),
        mock.patch("arka.agent.goal._fish_history", return_value=""),
        mock.patch("arka.agent.goal._skills_list", return_value="test"),
        redirect_stderr(stderr),
    ):
        rc = run_goal("improve the tui", max_steps=5)
    assert rc == 0
    err = stderr.getvalue()
    assert err.count("skipped cd") == 2
    assert "Repeated cd actions detected" not in err


def test_run_goal_strips_cd_prefix_before_execution(tmp_path: Path):
    import os

    from arka.agent.goal import run_goal

    repo = tmp_path / "arka"
    repo.mkdir()
    responses = [
        '{"status":"continue","cmd":"cd arka/ && echo hello","why":"probe"}',
        '{"status":"done","cmd":"","why":"done"}',
    ]
    stderr = io.StringIO()
    previous = os.getcwd()
    try:
        os.chdir(tmp_path)
        with (
            mock.patch("arka.agent.goal._llm", side_effect=responses),
            mock.patch("arka.agent.goal._dir_context", return_value=("", "")),
            mock.patch("arka.agent.goal._fish_history", return_value=""),
            mock.patch("arka.agent.goal._skills_list", return_value="test"),
            mock.patch("arka.agent.goal._run_cmd", return_value=(0, "hello")) as mock_run,
            redirect_stderr(stderr),
        ):
            rc = run_goal("improve the tui", max_steps=3)
    finally:
        os.chdir(previous)
    assert rc == 0
    mock_run.assert_called_once()
    assert mock_run.call_args[0][0] == "echo hello"
