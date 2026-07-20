#!/usr/bin/env python3
"""Deterministic greetings so short salutations do not waste LLM calls."""

from __future__ import annotations

import argparse
import re

GREETING_RE = re.compile(
    r"(?i)^(?:hi|hello|hey|yo|namaste|thanks|thank\s+you|good\s+(?:morning|afternoon|evening|night))[!.\\s]*$"
)


def is_greeting(text: str) -> bool:
    return bool(GREETING_RE.match((text or "").strip()))


def greeting_text(text: str = "") -> str:
    lower = (text or "").strip().lower()
    if lower.startswith(("thanks", "thank")):
        return "You’re welcome — what should Arka help with next?"
    return "Hi — I’m Arka. Ask me to inspect a repo, run tests, summarize a site, or use any Arka skill."


def route_greeting(text: str) -> str | None:
    if not is_greeting(text):
        return None
    return "greeting " + (text.strip() or "hi")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reply to short greetings without an LLM call.")
    parser.add_argument("text", nargs="*", default=["hi"])
    args = parser.parse_args(argv)
    print(greeting_text(" ".join(args.text)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
