#!/usr/bin/env python3
"""Coach users to write clearer, more effective LLM prompts."""

from __future__ import annotations

import argparse
import json
import sys

from arka.routing.prompt_coach import extract_focus


def prompt_coach_system_prompt() -> str:
    return (
        "You are an expert prompt-writing coach for LLM users and agent builders. "
        "Teach practical prompt craft — not hype. Be concise and actionable.\n\n"
        "When coaching, cover what applies:\n"
        "1. **Goal** — one clear outcome; remove mixed intents.\n"
        "2. **Role & audience** — who the model should be and who the output is for.\n"
        "3. **Context** — only the facts, files, constraints, or examples that change the answer.\n"
        "4. **Constraints** — format, length, tone, must-include / must-not, tools available.\n"
        "5. **Examples** — one short input→output example when ambiguity is costly.\n"
        "6. **Verification** — how to check the answer (tests, checklist, cite sources).\n\n"
        "If the user shared a draft prompt, show:\n"
        "- **What's working**\n"
        "- **Gaps** (missing context, vague verbs, conflicting goals)\n"
        "- **Rewritten prompt** in a fenced block they can copy\n"
        "- **Why** each change helps (1 line each, no fluff)\n\n"
        "If no draft was given, give a short playbook plus 2–3 before/after mini examples "
        "for common tasks (coding, research, writing, agents). "
        "Do not invent product features or claim access you lack."
    )


def prompt_coach_user_prompt(text: str, *, focus: str | None = None) -> str:
    resolved = focus or extract_focus(text)
    if resolved:
        return (
            f"User request: {text}\n\n"
            f"Focus / draft / task: {resolved}\n\n"
            "Coach them on writing a better prompt for this."
        )
    return (
        f"User request: {text}\n\n"
        "They want general help writing better prompts. "
        "Give a practical playbook and examples they can reuse."
    )


def coach_prompts(text: str, *, focus: str | None = None) -> str:
    text = " ".join((text or "").split()).strip()
    if not text:
        return ""

    system = prompt_coach_system_prompt()
    user = prompt_coach_user_prompt(text, focus=focus)

    try:
        from arka.llm.cli import llm_complete

        return llm_complete(
            system,
            user,
            temperature=0.35,
            task="chat",
            skill="prompt_coach",
        ).strip()
    except ImportError:
        pass

    from arka.agent.core import _llm

    return _llm(system, user, temperature=0.35, task="chat")


def route_command(text: str) -> str | None:
    from arka.routing.prompt_coach import route_command as _route

    return _route(text)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="arka prompt_coach",
        description="Help write clearer, more effective LLM prompts",
    )
    parser.add_argument(
        "text",
        nargs="*",
        help="Coaching request (e.g. help me write better prompts)",
    )
    parser.add_argument("--draft", "-d", help="Draft prompt or task to improve")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv if argv is not None else sys.argv[1:]))

    request = " ".join(args.text).strip()
    if not request and not args.draft:
        parser.print_help()
        return 1
    if not request:
        request = "help me write better prompts"

    focus = args.draft or extract_focus(request)
    answer = coach_prompts(request, focus=focus)
    if not answer:
        print("Could not coach (check LLM API keys)", file=sys.stderr)
        return 1

    if args.json:
        print(
            json.dumps(
                {
                    "request": request,
                    "focus": focus,
                    "coaching": answer,
                },
                indent=2,
            )
        )
    else:
        print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
