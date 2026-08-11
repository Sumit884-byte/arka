"""Just-AI mode — LLM chat/completion only, no routing or skills."""

from __future__ import annotations

import os

_TRUTHY = frozenset({"1", "true", "yes", "on", "enabled"})

# MCP tools exposed when JUST_AI=1 (everything else is disabled).
JUST_AI_MCP_TOOLS = frozenset({"arka_ask"})


def is_just_ai() -> bool:
    """True when Arka should skip routing/skills and use LLM chat only."""
    val = os.environ.get("JUST_AI", "").strip().lower()
    return val in _TRUTHY


def enable_just_ai() -> None:
    """Enable just-ai mode for the current process."""
    os.environ["JUST_AI"] = "1"


def describe_just_ai() -> str:
    return "LLM chat only — routing, skills, and MCP tools disabled"
