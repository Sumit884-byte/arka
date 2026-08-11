#!/usr/bin/env python3
"""Arka Nudge — benefits-only nudges, or fair comparisons when alternatives are named."""

from __future__ import annotations

import json
import sys

from arka.routing.nudge import (
    nudge_mode,
    nudge_system_prompt,
    nudge_user_prompt,
    strip_nudge_prefix,
)


def answer_nudge(text: str, *, mode: str | None = None) -> str:
    text = " ".join((text or "").split()).strip()
    if not text:
        return ""
    resolved_mode = mode or nudge_mode(text)
    system = nudge_system_prompt(mode=resolved_mode)
    user = nudge_user_prompt(text, mode=resolved_mode)
    try:
        from arka.llm.cli import llm_complete

        return llm_complete(
            system,
            user,
            temperature=0.65 if resolved_mode == "compare" else 0.75,
            task="chat",
            skill="nudge",
        ).strip()
    except ImportError:
        pass
    from arka.agent.core import _llm

    temp = 0.65 if resolved_mode == "compare" else 0.75
    return _llm(system, user, temperature=temp, task="chat")


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(prog="arka nudge", description="Benefits-only nudges or fair comparisons")
    parser.add_argument("question", nargs="*", help="Purchase or decision question")
    parser.add_argument("--json", action="store_true", help="Emit JSON with mode and answer")
    parser.add_argument("--mode", choices=("nudge", "compare"), help="Force nudge or compare mode")
    args = parser.parse_args(list(argv if argv is not None else sys.argv[1:]))

    question = " ".join(args.question).strip()
    if not question:
        parser.print_help()
        return 1

    mode = args.mode or nudge_mode(question)
    answer = answer_nudge(question, mode=mode)
    if not answer:
        print("Could not generate nudge (check LLM API keys)", file=sys.stderr)
        return 1

    if args.json:
        print(
            json.dumps(
                {
                    "mode": mode,
                    "compare": mode == "compare",
                    "question": strip_nudge_prefix(question),
                    "answer": answer,
                },
                indent=2,
            )
        )
    else:
        label = "Compare" if mode == "compare" else "Nudge"
        print(f"[{label}]\n{answer}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
