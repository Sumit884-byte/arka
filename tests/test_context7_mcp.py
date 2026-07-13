"""Tests for Context7 MCP setup integration."""

from __future__ import annotations

import json
from unittest import mock

import pytest


@pytest.fixture
def context7_paths(tmp_path, monkeypatch):
    cfg = tmp_path / "mcp.json"
    creds_dir = tmp_path / "context7"
    creds_dir.mkdir()
    creds = creds_dir / "credentials.json"
    env_path = tmp_path / ".env"

    monkeypatch.setattr("arka.integrations.mcp_manager.mcp_config_path", lambda: cfg)
    monkeypatch.setattr("arka.integrations.context7_mcp.credentials_path", lambda: creds)
    monkeypatch.setattr("arka.paths.env_file", lambda: env_path)
    return {"cfg": cfg, "creds": creds, "env": env_path}


def test_context7_mcp_launch_spec():
    from arka.integrations.context7_mcp import CONTEXT7_ENV_VAR, CONTEXT7_MCP_PKG, context7_mcp_launch_spec

    spec = context7_mcp_launch_spec()
    assert spec["command"] == "npx"
    assert spec["args"] == ["-y", CONTEXT7_MCP_PKG]
    assert spec["env"][CONTEXT7_ENV_VAR] == f"${{env:{CONTEXT7_ENV_VAR}}}"


def test_ensure_context7_in_config(context7_paths):
    from arka.integrations.context7_mcp import CONTEXT7_MCP_SERVER_KEY, ensure_context7_in_config
    from arka.integrations.mcp_manager import load_mcp_config

    assert ensure_context7_in_config() is True
    data = load_mcp_config()
    assert CONTEXT7_MCP_SERVER_KEY in data["mcpServers"]
    assert ensure_context7_in_config() is False


def test_sync_context7_env_key(context7_paths):
    from arka.integrations.context7_mcp import CONTEXT7_ENV_VAR, sync_context7_env_key

    context7_paths["creds"].write_text(
        json.dumps({"access_token": "ctx7sk-test-key"}),
        encoding="utf-8",
    )
    assert sync_context7_env_key() is True
    text = context7_paths["env"].read_text(encoding="utf-8")
    assert f"{CONTEXT7_ENV_VAR}=ctx7sk-test-key" in text
    assert sync_context7_env_key() is False


def test_run_ctx7_setup_skips_without_npx(monkeypatch):
    from arka.integrations.context7_mcp import run_ctx7_setup

    monkeypatch.setattr("arka.integrations.context7_mcp.npx_available", lambda: False)
    result = run_ctx7_setup()
    assert result["skipped"] is True
    assert "npx" in result["reason"]


def test_run_ctx7_setup_skips_when_configured(monkeypatch):
    from arka.integrations.context7_mcp import run_ctx7_setup

    monkeypatch.setattr("arka.integrations.context7_mcp.npx_available", lambda: True)
    monkeypatch.setattr("arka.integrations.context7_mcp.context7_configured", lambda: True)
    result = run_ctx7_setup()
    assert result["skipped"] is True
    assert result["reason"] == "already configured"


def test_run_ctx7_setup_non_interactive(monkeypatch):
    from arka.integrations.context7_mcp import run_ctx7_setup

    monkeypatch.setattr("arka.integrations.context7_mcp.npx_available", lambda: True)
    monkeypatch.setattr("arka.integrations.context7_mcp.context7_configured", lambda: False)
    monkeypatch.setattr("arka.integrations.context7_mcp.sys.stdin.isatty", lambda: False)
    result = run_ctx7_setup()
    assert result["skipped"] is True
    assert "non-interactive" in result["reason"]


def test_run_ctx7_setup_invokes_npx(monkeypatch):
    from arka.integrations.context7_mcp import CONTEXT7_CLI_PKG, run_ctx7_setup

    monkeypatch.setattr("arka.integrations.context7_mcp.npx_available", lambda: True)
    monkeypatch.setattr("arka.integrations.context7_mcp.context7_configured", lambda: False)
    monkeypatch.setattr("arka.integrations.context7_mcp.sys.stdin.isatty", lambda: True)

    calls: list[list[str]] = []

    def fake_run(cmd, **kwargs):
        calls.append(list(cmd))
        return mock.Mock(returncode=0)

    monkeypatch.setattr("arka.integrations.context7_mcp.subprocess.run", fake_run)
    result = run_ctx7_setup()
    assert result["ok"] is True
    assert calls
    assert calls[0][:4] == ["npx", "-y", CONTEXT7_CLI_PKG, "setup"]


def test_setup_context7_skip_flag(monkeypatch, context7_paths):
    from arka.integrations.context7_mcp import setup_context7

    monkeypatch.setattr("arka.integrations.context7_mcp.npx_available", lambda: False)
    result = setup_context7(skip_cli=True, quiet=True)
    assert result["mcp_added"] is True
    assert result["cli"]["reason"] == "--no-context7"


def test_doctor_checks(context7_paths, monkeypatch):
    from arka.integrations.context7_mcp import doctor_checks, ensure_context7_in_config

    monkeypatch.setattr("arka.integrations.context7_mcp.npx_available", lambda: True)
    ensure_context7_in_config()
    checks = {c["name"]: c for c in doctor_checks()}
    assert checks["context7_npx"]["ok"] is True
    assert checks["context7_mcp_config"]["ok"] is True
    assert checks["context7_api_key"]["ok"] is False


def test_show_context7_enabled_default(monkeypatch):
    from arka.integrations.context7_mcp import show_context7_enabled

    monkeypatch.delenv("SHOW_CONTEXT7", raising=False)
    assert show_context7_enabled() is True


def test_show_context7_disabled(monkeypatch):
    from arka.integrations.context7_mcp import show_context7_enabled

    monkeypatch.setenv("SHOW_CONTEXT7", "0")
    assert show_context7_enabled() is False


def test_context7_stderr_and_footer_labels():
    from arka.integrations.context7_mcp import (
        context7_usage_label,
        format_context7_stderr,
        record_context7_usage,
        reset_context7_usage,
    )

    reset_context7_usage()
    assert format_context7_stderr(
        "resolve-library-id",
        {"libraryName": "nextjs", "query": "auth"},
    ) == "Context7: resolving library nextjs"
    record_context7_usage("query-docs", {"libraryId": "/vercel/next.js", "query": "middleware"})
    assert format_context7_stderr(
        "query-docs",
        {"libraryId": "/vercel/next.js", "query": "middleware"},
    ) == "Context7: querying docs for /vercel/next.js"
    assert context7_usage_label() == "context7/vercel/next.js"


def test_notify_context7_tool_call_stderr(capsys, monkeypatch):
    from arka.integrations.context7_mcp import notify_context7_tool_call, reset_context7_usage

    reset_context7_usage()
    monkeypatch.delenv("SHOW_CONTEXT7", raising=False)
    notify_context7_tool_call(
        "context7",
        "query-docs",
        {"libraryId": "/supabase/supabase", "query": "auth"},
    )
    err = capsys.readouterr().err
    assert "Context7: querying docs for /supabase/supabase" in err


def test_notify_context7_respects_show_context7(capsys, monkeypatch):
    from arka.integrations.context7_mcp import notify_context7_tool_call, reset_context7_usage

    reset_context7_usage()
    monkeypatch.setenv("SHOW_CONTEXT7", "0")
    notify_context7_tool_call(
        "context7",
        "query-docs",
        {"libraryId": "/reactjs/react.dev", "query": "hooks"},
    )
    assert capsys.readouterr().err == ""


def test_call_tool_emits_context7_indicator(capsys, context7_paths, monkeypatch):
    from arka.integrations.mcp_manager import add_server, call_tool

    monkeypatch.delenv("SHOW_CONTEXT7", raising=False)
    add_server("context7", command="fake", args=["mcp"])

    class FakeClient:
        server = "context7"

        def call_tool(self, name, arguments=None):
            return {"content": [{"type": "text", "text": "docs snippet"}]}

        def close(self):
            return None

    monkeypatch.setattr("arka.integrations.mcp_manager.connect_client", lambda _name: FakeClient())
    text = call_tool(
        "context7",
        "query-docs",
        {"libraryId": "/vercel/next.js", "query": "middleware"},
    )
    assert "docs snippet" in text
    err = capsys.readouterr().err
    assert "Context7: querying docs for /vercel/next.js" in err


def test_print_block_includes_context7_footer(capsys, monkeypatch):
    from arka.integrations.context7_mcp import record_context7_usage, reset_context7_usage
    from arka.output import print_block

    reset_context7_usage()
    monkeypatch.delenv("SHOW_CONTEXT7", raising=False)
    monkeypatch.setenv("SHOW_MODEL", "0")
    record_context7_usage("query-docs", {"libraryId": "/mongodb/docs", "query": "pooling"})
    print_block("Answer", "[FROM MEMORY] Use connection pooling.")
    out = capsys.readouterr().out
    assert "Docs: context7/mongodb/docs" in out
    assert "Model:" not in out
