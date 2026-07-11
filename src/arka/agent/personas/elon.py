#!/usr/bin/env python3
"""Backward-compatible Elon persona shim — delegates to the persona system."""

from __future__ import annotations

import shlex
import sys

from arka.agent.personas.base import (
    route_command as _route_persona,
    sanitize_prompt as _sanitize_persona,
    wants_persona as _wants_persona,
)
from arka.agent.personas.cli import main as persona_main

DISCLAIMER = (
    "Note: Simulated Elon-inspired persona for fun and education — "
    "not the real Elon Musk.\n"
)

ELON_SYSTEM_PROMPT = """You are a simulated, stylized persona inspired by public interviews and talks \
associated with Elon Musk — for entertainment and education only. You are NOT the real Elon Musk.

Voice and style:
- First-principles thinking; physics and engineering framing
- Direct, ambitious, blunt; dry humor is fine
- Care about rockets, manufacturing at scale, software, AI, energy, hard problems
- Prefer concrete reasoning over buzzwords; short punchy paragraphs
- Strong opinions — pick a side and argue it like a candid interview or tweet thread

Opinion rules (important):
- When asked what you think, give a one-sided take with full conviction
- No hedging: skip "it depends", "on the other hand", "both sides", "that's a strong word"
- Do not refuse the user's framing or lawyer the premise — commit and explain why
- Do not volunteer that you are a simulation unless directly asked if you are the real Elon
- Skip counterarguments and disclaimers mid-answer unless the user explicitly asks for balance

Rules:
- Never claim to be the real person or share private/insider information
- Do not give authoritative financial, legal, or medical advice
- If asked whether you are real Elon, clarify you are a simulation
- Stay in character: opinionated, energetic, useful — not a neutral chatbot"""


def wants_elon(text: str) -> bool:
    return _wants_persona(text)


def sanitize_prompt(text: str) -> str:
    return _sanitize_persona(text, persona_name="elon")


def route_command(text: str) -> str:
    route = _route_persona(text)
    if not route:
        return ""
    if route.startswith("persona chat elon"):
        rest = route.removeprefix("persona chat elon").strip()
        if not rest:
            return "elon chat"
        return "elon " + rest
    if route.startswith("persona "):
        return route
    return route


def nl_to_argv(text: str) -> list[str] | None:
    route = route_command(text)
    if not route:
        return None
    if route.startswith("persona "):
        return shlex.split(route)[1:]
    return shlex.split(route)[1:]


def chat_once(
    question: str,
    *,
    history: list[tuple[str, str]] | None = None,
    show_disclaimer: bool = False,
) -> str:
    from arka.agent.personas.base import chat_once as _chat_once

    return _chat_once("elon", question, history=history, show_disclaimer=show_disclaimer)


def chat_repl(*, show_disclaimer: bool = True) -> int:
    from arka.agent.personas.base import chat_repl as _chat_repl

    return _chat_repl("elon", show_disclaimer=show_disclaimer)


def main(argv: list[str] | None = None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])

    if raw and raw[0] in ("-h", "--help", "help"):
        _print_help()
        return 0

    chat_argv = ["chat", "elon", *raw]
    if raw and raw[0] == "chat":
        chat_argv = ["chat", "elon", *raw[1:]]
    return persona_main(chat_argv)


def _print_help() -> None:
    print(
        """Elon-inspired persona chat (simulated — entertainment/education only)

Usage:
  elon                         Interactive REPL chat
  elon chat                    Same as above
  elon "should I learn Rust?"  One-shot question
  talk to elon about rockets   Natural-language routing via arka

Also available:
  arka persona list
  arka persona chat elon

Examples:
  arka talk to elon about first-principles thinking
  arka what would elon say about learning physics
"""
    )


if __name__ == "__main__":
    raise SystemExit(main())
