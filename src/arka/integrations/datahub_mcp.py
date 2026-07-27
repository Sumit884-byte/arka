"""DataHub MCP — data discovery, lineage, and metadata management for Arka agents."""

from __future__ import annotations

import os
from typing import Any

DATAHUB_MCP_SERVER_KEY = "datahub"
DATAHUB_MCP_PKG = "mcp-server-datahub"
DATAHUB_GMS_URL_VAR = "DATAHUB_GMS_URL"
DATAHUB_GMS_TOKEN_VAR = "DATAHUB_GMS_TOKEN"


def datahub_configured() -> bool:
    """True if GMS URL and token environment variables are set."""
    from arka.paths import load_env_file

    load_env_file()
    url = os.environ.get(DATAHUB_GMS_URL_VAR, "").strip()
    token = os.environ.get(DATAHUB_GMS_TOKEN_VAR, "").strip()
    return bool(url and token)


def datahub_mcp_launch_spec() -> dict[str, Any]:
    """Return the recommended uvx launch configuration for the DataHub MCP server."""
    return {
        "command": "uvx",
        "args": [DATAHUB_MCP_PKG],
        "env": {
            DATAHUB_GMS_URL_VAR: f"${{env:{DATAHUB_GMS_URL_VAR}}}",
            DATAHUB_GMS_TOKEN_VAR: f"${{env:{DATAHUB_GMS_TOKEN_VAR}}}",
            "TOOLS_IS_MUTATION_ENABLED": os.environ.get(
                "TOOLS_IS_MUTATION_ENABLED", "true"
            ),
            "TOOLS_IS_USER_ENABLED": os.environ.get("TOOLS_IS_USER_ENABLED", "true"),
        },
    }


def ensure_datahub_in_config() -> bool:
    """Add DataHub MCP entry to ~/.config/arka/mcp.json if missing."""
    from arka.integrations.mcp_manager import load_mcp_config, save_mcp_config

    data = load_mcp_config()
    servers = data.setdefault("mcpServers", {})
    if DATAHUB_MCP_SERVER_KEY in servers:
        return False
    servers[DATAHUB_MCP_SERVER_KEY] = datahub_mcp_launch_spec()
    save_mcp_config(data)
    return True


def setup_datahub(*, quiet: bool = False) -> dict[str, Any]:
    """Default DataHub setup for `arka setup`."""
    result: dict[str, Any] = {"mcp_added": False, "configured": False}
    result["mcp_added"] = ensure_datahub_in_config()
    result["configured"] = datahub_configured()

    if not quiet:
        if result["mcp_added"]:
            print("  ✓ DataHub MCP added to ~/.config/arka/mcp.json")
        if result["configured"]:
            print("  ✓ DataHub credentials ready")
        else:
            print(
                f"  → DataHub: set {DATAHUB_GMS_URL_VAR} and {DATAHUB_GMS_TOKEN_VAR} in .env"
            )
    return result


def doctor_checks() -> list[dict[str, Any]]:
    """Lightweight DataHub checks for `arka doctor`."""
    from arka.integrations.mcp_manager import load_mcp_config, mcp_config_path

    checks: list[dict[str, Any]] = []

    data = load_mcp_config()
    servers = data.get("mcpServers") or {}
    in_config = DATAHUB_MCP_SERVER_KEY in servers
    checks.append(
        {
            "name": "datahub_mcp_config",
            "ok": in_config,
            "detail": str(mcp_config_path()) if in_config else "run: arka setup",
        }
    )

    configured = datahub_configured()
    checks.append(
        {
            "name": "datahub_credentials",
            "ok": configured,
            "detail": (
                "DATAHUB_GMS_URL and DATAHUB_GMS_TOKEN set"
                if configured
                else "set DATAHUB_GMS_URL and DATAHUB_GMS_TOKEN in .env"
            ),
        }
    )
    return checks


def format_doctor_lines() -> list[str]:
    """Lightweight DataHub diagnostics formatting for `arka doctor`."""
    lines: list[str] = []
    for check in doctor_checks():
        status = "ok" if check["ok"] else "missing"
        lines.append(
            f"  datahub {check['name'].removeprefix('datahub_')}: {status} ({check['detail']})"
        )
    return lines


__all__ = [
    "DATAHUB_GMS_TOKEN_VAR",
    "DATAHUB_GMS_URL_VAR",
    "DATAHUB_MCP_PKG",
    "DATAHUB_MCP_SERVER_KEY",
    "datahub_configured",
    "datahub_mcp_launch_spec",
    "doctor_checks",
    "ensure_datahub_in_config",
    "format_doctor_lines",
    "setup_datahub",
]
