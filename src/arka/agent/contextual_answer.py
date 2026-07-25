#!/usr/bin/env python3
"""Force contextual answers with comparisons and background the user may not know to ask for."""

from __future__ import annotations

import json
import sys

from arka.core.contextual_answer import answer_instructions, wants_contextual_framing


def answer_contextual(question: str) -> tuple[str, str]:
    """Return (provenance, answer_text)."""
    from arka.agent.chat import answer_question

    question = " ".join((question or "").split()).strip()
    if not question:
        return "error", ""
    return answer_question(question, contextual=True)


def main(argv: list[str] | None = None) -> int:
    import argparse

    parser = argparse.ArgumentParser(
        prog="arka contextual_answer",
        description="Answer with proactive context and related-option comparisons",
    )
    parser.add_argument("question", nargs="*", help="Question to answer")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv if argv is not None else sys.argv[1:]))

    question = " ".join(args.question).strip()
    if not question:
        parser.print_help()
        return 1

    prov, answer = answer_contextual(question)
    if not answer:
        print("Could not answer (check LLM API keys)", file=sys.stderr)
        return 1

    if args.json:
        print(
            json.dumps(
                {
                    "provenance": prov,
                    "contextual": True,
                    "auto_detect": wants_contextual_framing(question),
                    "instructions": answer_instructions(question, force=True),
                    "answer": answer,
                },
                indent=2,
            )
        )
    else:
        print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
