"""Tests for Google Gemini CLI wrapper."""

from __future__ import annotations

from unittest import mock

from arka.integrations import gemini_cli as gc


def test_gemini_exec_prefix_which():
    with mock.patch.object(gc.shutil, "which", side_effect=lambda name: "/usr/local/bin/gemini" if name == "gemini" else None):
        assert gc.gemini_exec_prefix() == ["/usr/local/bin/gemini"]


def test_gemini_exec_prefix_npx_fallback():
    with mock.patch.object(gc.shutil, "which", side_effect=lambda name: "/usr/bin/npx" if name == "npx" else None):
        assert gc.gemini_exec_prefix() == ["npx", "@google/gemini-cli"]


def test_gemini_exec_prefix_env_override():
    with mock.patch.dict("os.environ", {"GEMINI_CLI": "/custom/gemini"}, clear=False):
        assert gc.gemini_exec_prefix() == ["/custom/gemini"]


def test_gemini_exec_prefix_missing():
    with mock.patch.object(gc.shutil, "which", return_value=None):
        assert gc.gemini_exec_prefix() is None
        assert gc.gemini_cli_available() is False


def test_build_gemini_argv_shorthand_prompt():
    assert gc.build_gemini_argv(["explain", "this", "codebase"]) == [
        "--skip-trust",
        "-p",
        "explain this codebase",
    ]


def test_build_gemini_argv_passthrough_flags():
    assert gc.build_gemini_argv(["-p", "hello", "-m", "gemini-2.5-flash"]) == [
        "-p",
        "hello",
        "-m",
        "gemini-2.5-flash",
    ]


def test_build_gemini_argv_passthrough_subcommand():
    assert gc.build_gemini_argv(["mcp", "list"]) == ["mcp", "list"]


def test_build_gemini_argv_explicit_passthrough():
    assert gc.build_gemini_argv(["--", "-i", "continue planning"]) == ["-i", "continue planning"]


def test_run_gemini_cli_missing_binary(capsys):
    with mock.patch.object(gc, "gemini_exec_prefix", return_value=None):
        rc = gc.run_gemini_cli(["-p", "hi"])
    assert rc == 127
    err = capsys.readouterr().err
    assert "Gemini CLI not found" in err
    assert "npm install -g" in err
