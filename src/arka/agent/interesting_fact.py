#!/usr/bin/env python3
"""Lightweight LLM trivia — one surprising fact, no web search."""

from __future__ import annotations

import sys

from arka.routing.interesting_fact import (
    extract_topic,
    interesting_fact_system_prompt,
    interesting_fact_user_prompt,
)


def answer_interesting_fact(text: str, *, topic: str | None = None) -> str:
    text = " ".join((text or "").split()).strip()
    if not text:
        return ""

    resolved_topic = topic or extract_topic(text)
    system = interesting_fact_system_prompt()
    user = interesting_fact_user_prompt(text, topic=resolved_topic)

    try:
        from arka.llm.cli import llm_complete

        return llm_complete(
            system,
            user,
            temperature=0.9,
            task="chat",
            skill="interesting_fact",
        ).strip()
    except ImportError:
        pass

    from arka.agent.core import _llm

    return _llm(system, user, temperature=0.9, task="chat")


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("Usage: interesting_fact.py <request>", file=sys.stderr)
        return 1
    answer = answer_interesting_fact(" ".join(args))
    if not answer:
        print("Could not get a fact (check LLM API keys)", file=sys.stderr)
        return 1
    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
