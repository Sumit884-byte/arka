"""Tests for DataHub MCP setup integration."""

from __future__ import annotations


import pytest


@pytest.fixture
def datahub_paths(tmp_path, monkeypatch):
    cfg = tmp_path / "mcp.json"
    env_path = tmp_path / ".env"

    monkeypatch.setattr("arka.integrations.mcp_manager.mcp_config_path", lambda: cfg)
    monkeypatch.setattr("arka.paths.env_file", lambda: env_path)
    return {"cfg": cfg, "env": env_path}


def test_datahub_mcp_launch_spec(monkeypatch):
    from arka.integrations.datahub_mcp import (
        DATAHUB_GMS_TOKEN_VAR,
        DATAHUB_GMS_URL_VAR,
        DATAHUB_MCP_PKG,
        datahub_mcp_launch_spec,
    )

    monkeypatch.setenv("TOOLS_IS_MUTATION_ENABLED", "true")
    monkeypatch.setenv("TOOLS_IS_USER_ENABLED", "true")

    spec = datahub_mcp_launch_spec()
    assert spec["command"] == "uvx"
    assert spec["args"] == [DATAHUB_MCP_PKG]
    assert spec["env"][DATAHUB_GMS_URL_VAR] == f"${{env:{DATAHUB_GMS_URL_VAR}}}"
    assert spec["env"][DATAHUB_GMS_TOKEN_VAR] == f"${{env:{DATAHUB_GMS_TOKEN_VAR}}}"
    assert spec["env"]["TOOLS_IS_MUTATION_ENABLED"] == "true"
    assert spec["env"]["TOOLS_IS_USER_ENABLED"] == "true"


def test_ensure_datahub_in_config(datahub_paths):
    from arka.integrations.datahub_mcp import (
        DATAHUB_MCP_SERVER_KEY,
        ensure_datahub_in_config,
    )
    from arka.integrations.mcp_manager import load_mcp_config

    assert ensure_datahub_in_config() is True
    data = load_mcp_config()
    assert DATAHUB_MCP_SERVER_KEY in data["mcpServers"]
    assert ensure_datahub_in_config() is False


def test_datahub_configured(monkeypatch):
    from arka.integrations.datahub_mcp import (
        DATAHUB_GMS_TOKEN_VAR,
        DATAHUB_GMS_URL_VAR,
        datahub_configured,
    )

    monkeypatch.setenv(DATAHUB_GMS_URL_VAR, "http://localhost:8080")
    monkeypatch.setenv(DATAHUB_GMS_TOKEN_VAR, "token123")
    assert datahub_configured() is True

    monkeypatch.delenv(DATAHUB_GMS_TOKEN_VAR, raising=False)
    assert datahub_configured() is False


def test_setup_datahub(datahub_paths, monkeypatch):
    from arka.integrations.datahub_mcp import (
        DATAHUB_GMS_TOKEN_VAR,
        DATAHUB_GMS_URL_VAR,
        setup_datahub,
    )

    monkeypatch.setenv(DATAHUB_GMS_URL_VAR, "http://localhost:8080")
    monkeypatch.setenv(DATAHUB_GMS_TOKEN_VAR, "token123")

    result = setup_datahub(quiet=True)
    assert result["mcp_added"] is True
    assert result["configured"] is True


def test_doctor_checks(datahub_paths, monkeypatch):
    from arka.integrations.datahub_mcp import (
        DATAHUB_GMS_TOKEN_VAR,
        DATAHUB_GMS_URL_VAR,
        doctor_checks,
        ensure_datahub_in_config,
    )

    monkeypatch.delenv(DATAHUB_GMS_URL_VAR, raising=False)
    monkeypatch.delenv(DATAHUB_GMS_TOKEN_VAR, raising=False)
    monkeypatch.setattr("arka.paths.load_env_file", lambda: None)

    ensure_datahub_in_config()
    checks = {c["name"]: c for c in doctor_checks()}
    assert checks["datahub_mcp_config"]["ok"] is True
    assert checks["datahub_credentials"]["ok"] is False


def test_format_doctor_lines(datahub_paths, monkeypatch):
    from arka.integrations.datahub_mcp import format_doctor_lines

    monkeypatch.setattr("arka.paths.load_env_file", lambda: None)
    lines = format_doctor_lines()
    assert len(lines) == 2
    assert any("datahub mcp_config:" in line for line in lines)
    assert any("datahub credentials:" in line for line in lines)
