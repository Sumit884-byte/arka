"""MCP context resolution for team workflow steps."""

from __future__ import annotations

import os
from typing import Any

from arka.teams.schema import Team, Workflow, WorkflowStep


def _coerce_bool(val: Any) -> bool | None:
    if val is None:
        return None
    if isinstance(val, bool):
        return val
    if isinstance(val, (int, float)):
        return bool(val)
    if isinstance(val, str):
        text = val.strip().lower()
        if text in {"true", "1", "yes", "on"}:
            return True
        if text in {"false", "0", "no", "off"}:
            return False
    return None


def _mcp_flag_chain(step: WorkflowStep, team: Team, workflow: Workflow) -> bool | None:
    wf_defaults = workflow.defaults or {}
    team_defaults = team.defaults or {}
    for flag in (step.mcp, wf_defaults.get("mcp"), team_defaults.get("mcp")):
        coerced = _coerce_bool(flag)
        if coerced is not None:
            return coerced
    return None


def resolve_step_mcp(step: WorkflowStep, team: Team, workflow: Workflow) -> tuple[bool, list[str]]:
    """Return whether MCP is enabled for a step and which server names to expose."""
    if step.mcp_servers:
        names = [str(s).strip() for s in step.mcp_servers if str(s).strip()]
        return bool(names), names

    enabled = _mcp_flag_chain(step, team, workflow)
    if enabled is False:
        return False, []
    if enabled is True:
        from arka.integrations.mcp_manager import list_server_names

        return True, list_server_names()
    return False, []


def build_mcp_context(servers: list[str]) -> str:
    """Build MCP server/tool summary for injection into step prompts."""
    if not servers:
        return ""

    from arka.integrations.mcp_manager import list_tools

    lines = [
        "MCP tools available for this step (configured in ~/.config/arka/mcp.json):",
    ]
    for name in servers:
        try:
            tools = list_tools(name)
            if tools:
                preview = ", ".join(tool.name for tool in tools[:25])
                suffix = " …" if len(tools) > 25 else ""
                lines.append(f"- {name}: {preview}{suffix}")
            else:
                lines.append(f"- {name}: (no tools listed)")
        except Exception as exc:
            lines.append(f"- {name}: unavailable ({str(exc)[:120]})")

    max_rounds = max(0, int(os.environ.get("TEAM_MCP_TOOL_ROUNDS", "0")))
    if max_rounds > 0:
        lines.append(
            f"Model steps may request MCP tools via JSON: "
            f'{{"mcp_tool": "<server>", "tool": "<name>", "arguments": {{}}}} '
            f"(up to {max_rounds} round(s); set TEAM_MCP_TOOL_ROUNDS=0 to disable)."
        )
    else:
        lines.append(
            "Direct MCP tool loops are disabled for model steps (TEAM_MCP_TOOL_ROUNDS=0). "
            "Use shared memory or agent roles for live tool use."
        )
    return "\n".join(lines)


def inject_mcp(system: str, mcp_context: str) -> str:
    if not mcp_context:
        return system
    if system:
        return system + "\n\n" + mcp_context
    return mcp_context
