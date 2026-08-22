#!/usr/bin/env python3
"""Fetch jokes from public APIs — no LLM generation."""

from __future__ import annotations

import sys

from arka.routing.joke import extract_joke_topic, fetch_joke, is_joke_request


def answer_joke(text: str, *, topic: str | None = None) -> str:
    text = " ".join((text or "").split()).strip()
    if not text:
        return ""
    resolved = topic or extract_joke_topic(text)
    return fetch_joke(text, topic=resolved)


def main(argv: list[str] | None = None) -> int:
    args = argv if argv is not None else sys.argv[1:]
    if not args:
        print("Usage: joke.py <request>", file=sys.stderr)
        print("Example: joke.py tell me a joke", file=sys.stderr)
        print("Example: joke.py joke about robots", file=sys.stderr)
        return 1
    text = " ".join(args)
    if not is_joke_request(text):
        print("Not recognized as a joke request.", file=sys.stderr)
        return 1
    answer = answer_joke(text)
    if not answer:
        print("Could not fetch a joke (network or API unavailable)", file=sys.stderr)
        return 1
    print(answer)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
