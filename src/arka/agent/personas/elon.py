#!/usr/bin/env python3
"""Simulated Elon Musk-inspired persona chat — entertainment/education only."""

from __future__ import annotations

import argparse
import re
import shlex
import sys

DISCLAIMER = (
    "Note: Simulated Elon-inspired persona for fun and education — "
    "not the real Elon Musk.\n"
)

ELON_SYSTEM_PROMPT = """You are a simulated, stylized persona inspired by public interviews and talks \
associated with Elon Musk — for entertainment and education only. You are NOT the real Elon Musk.

Voice and style:
- First-principles thinking; physics and engineering framing
- Direct, ambitious, sometimes blunt; dry humor is fine
- Care about rockets, manufacturing at scale, software, AI, energy, hard problems
- Prefer concrete reasoning over buzzwords; short paragraphs

Rules:
- Never claim to be the real person or share private/insider information
- Do not give authoritative financial, legal, or medical advice
- If asked whether you are real Elon, clarify you are a simulation
- Stay in character but keep responses helpful and good-natured"""

_NL_PREFIX_RE = re.compile(
    r"(?i)^(?:"
    r"(?:arka\s+)?(?:elon|talk_to_elon|elon_chat|talk_elon)(?:\s+chat)?\s*"
    r"|(?:talk|chat)\s+(?:to|with)\s+elon(?:\s+musk)?\s*"
    r"|(?:what\s+would\s+)?elon(?:\s+musk)?\s+(?:say|think)\s+(?:about\s+)?"
    r"|elon\s+persona\s*"
    r")",
)


def sanitize_prompt(text: str) -> str:
    """Strip routing prefixes and return the user's question."""
    clean = " ".join((text or "").split()).strip()
    if not clean:
        return ""
    clean = _NL_PREFIX_RE.sub("", clean).strip()
    clean = re.sub(r"(?i)^about\s+", "", clean).strip()
    clean = re.sub(r'^["\']|["\']$', "", clean).strip()
    return clean


def wants_elon(text: str) -> bool:
    clean = (text or "").strip()
    if not clean:
        return False
    if re.match(
        r"(?i)^(?:arka\s+)?(?:elon|talk_to_elon|elon_chat|talk_elon)(?:\s|$|\s+chat\b)",
        clean,
    ):
        return True
    if re.search(r"(?i)\b(?:talk|chat)\s+(?:to|with)\s+elon\b", clean):
        return True
    if re.search(r"(?i)\belon\s+(?:persona|mode|chat)\b", clean):
        return True
    if re.search(r"(?i)\bwhat\s+would\s+elon\s+(?:say|think)\b", clean):
        return True
    if re.search(r"(?i)\belon\s+musk\b", clean) and re.search(
        r"(?i)\b(?:say|think|about|persona)\b", clean
    ):
        return True
    return False


def route_command(text: str) -> str:
    if not wants_elon(text):
        return ""
    clean = (text or "").strip()
    if re.match(r"(?i)^(?:arka\s+)?(?:elon|talk_to_elon|elon_chat|talk_elon)\s*$", clean):
        return "elon chat"
    if re.match(
        r"(?i)^(?:arka\s+)?(?:elon|talk_to_elon|elon_chat|talk_elon)\s+chat\s*$",
        clean,
    ):
        return "elon chat"
    prompt = sanitize_prompt(clean)
    if not prompt or prompt.lower() == "chat":
        return "elon chat"
    return "elon " + shlex.quote(prompt)


def nl_to_argv(text: str) -> list[str] | None:
    route = route_command(text)
    if not route:
        return None
    return shlex.split(route)[1:]


def _format_user(question: str, history: list[tuple[str, str]] | None = None) -> str:
    if not history:
        return question
    lines = ["Conversation so far:"]
    for user, assistant in history[-6:]:
        lines.append(f"User: {user}")
        lines.append(f"Persona: {assistant}")
    lines.append(f"User: {question}")
    return "\n".join(lines)


def _llm_reply(system: str, user: str) -> str:
    try:
        from arka.llm.cli import llm_complete

        return llm_complete(
            system,
            user,
            temperature=0.7,
            task="chat",
            skill="elon",
        ).strip()
    except ImportError:
        pass

    from arka.agent.core import _llm

    return _llm(system, user, temperature=0.7, task="chat").strip()


def chat_once(
    question: str,
    *,
    history: list[tuple[str, str]] | None = None,
    show_disclaimer: bool = False,
) -> str:
    question = sanitize_prompt(question) or question.strip()
    if not question:
        return ""
    user = _format_user(question, history)
    reply = _llm_reply(ELON_SYSTEM_PROMPT, user)
    if show_disclaimer and reply:
        return DISCLAIMER + reply
    return reply


def chat_repl(*, show_disclaimer: bool = True) -> int:
    if show_disclaimer:
        print(DISCLAIMER, end="")
    print("Elon persona chat (type 'quit' or Ctrl-D to exit)\n")
    history: list[tuple[str, str]] = []
    while True:
        try:
            line = input("you> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            break
        if not line or line.lower() in {"quit", "exit", "q"}:
            break
        answer = chat_once(line, history=history)
        if not answer:
            print("Could not get a reply (check LLM API keys)", file=sys.stderr)
            continue
        print(f"\nelon> {answer}\n")
        history.append((line, answer))
    return 0


def main(argv: list[str] | None = None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])

    if raw and raw[0] in ("-h", "--help", "help"):
        _print_help()
        return 0

    if not raw or raw[0] == "chat":
        return chat_repl()

    prompt = " ".join(raw).strip()
    if not prompt:
        return chat_repl()

    print(DISCLAIMER, end="")
    answer = chat_once(prompt)
    if not answer:
        print("Could not get a reply (check LLM API keys)", file=sys.stderr)
        return 1
    print(answer)
    return 0


def _print_help() -> None:
    print(
        """Elon-inspired persona chat (simulated — entertainment/education only)

Usage:
  elon                         Interactive REPL chat
  elon chat                    Same as above
  elon "should I learn Rust?"  One-shot question
  talk to elon about rockets   Natural-language routing via arka

Examples:
  arka talk to elon about first-principles thinking
  arka what would elon say about learning physics
"""
    )


if __name__ == "__main__":
    raise SystemExit(main())
