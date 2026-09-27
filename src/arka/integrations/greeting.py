#!/usr/bin/env python3
"""Deterministic greetings so short salutations do not waste LLM calls."""

from __future__ import annotations

import argparse
import re

GREETING_RE = re.compile(
    r"(?i)^(?:hi|hello|hey|yo|namaste|thanks|thank\s+you|good\s+(?:morning|afternoon|evening|night))[!.\\s]*$"
)
ACK_RE = re.compile(
    r"(?i)^(?:(?:ok(?:ay)?|alright|all\s+right|sure|cool|nice|great|awesome|"
    r"perfect|got\s+it|sounds\s+good|good|fine|sweet|cheers|thanks|"
    r"thank(?:s|\s+you)?|thx|ty)[\s,!.]*)+$"
)
_THANKS_TOKEN = re.compile(r"(?i)\b(?:thanks|thank(?:s|\s+you)?|thx|ty)\b")
_BARE_OK = re.compile(r"(?i)^ok(?:ay)?[!.]*$")


def is_greeting(text: str) -> bool:
    return bool(GREETING_RE.match((text or "").strip()))


def is_acknowledgment(text: str) -> bool:
    """True for thanks / 'ok great' — not a request to keep building code."""
    t = " ".join((text or "").strip().split())
    if not t or _BARE_OK.match(t):
        return False
    if is_greeting(t):
        return bool(_THANKS_TOKEN.search(t))
    return bool(ACK_RE.match(t))


def greeting_text(text: str = "") -> str:
    lower = (text or "").strip().lower()
    if is_acknowledgment(text) or lower.startswith(("thanks", "thank")):
        return "You’re welcome — what should Arka help with next?"
    return "Hi — I’m Arka. Ask me to inspect a repo, run tests, summarize a site, or use any Arka skill."


def route_greeting(text: str) -> str | None:
    if is_greeting(text) or is_acknowledgment(text):
        return "greeting " + (text.strip() or "hi")
    return None


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Reply to short greetings without an LLM call.")
    parser.add_argument("text", nargs="*", default=["hi"])
    args = parser.parse_args(argv)
    print(greeting_text(" ".join(args.text)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
