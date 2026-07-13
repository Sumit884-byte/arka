"""Detect casual trivia / interesting-fact requests (no web search)."""

from __future__ import annotations

import re

_EXCLUDE = re.compile(
    r"(?i)\b(?:weather|time|date|my\s+ip|disk\s+space|password|wifi)\b"
)

_PATTERNS: tuple[re.Pattern[str], ...] = (
    re.compile(
        r"(?i)^(please\s+)?(do\s+)?tell\s+(me\s+)?(something\s+)?"
        r"(interesting|cool|fun|surprising|weird|random|amazing)\b"
    ),
    re.compile(r"(?i)^(please\s+)?give\s+me\s+(a\s+)?(fun\s+)?fact\b"),
    re.compile(r"(?i)^(please\s+)?(share\s+)?(a\s+)?random\s+fact\b"),
    re.compile(r"(?i)^(please\s+)?something\s+(interesting|cool|fun|surprising|weird|random)\b"),
    re.compile(r"(?i)^(please\s+)?fun\s+fact\b"),
    re.compile(r"(?i)^(please\s+)?trivia\b"),
    re.compile(r"(?i)^(please\s+)?(do\s+)?tell\s+(me\s+)?(a\s+)?(fun|random)\s+fact\b"),
)

_TOPIC = re.compile(
    r"(?i)(?:"
    r"something\s+(?:interesting|cool|fun|surprising|weird|random)\s+about|"
    r"(?:fun|random)\s+fact\s+about|"
    r"tell\s+(?:me\s+)?something\s+(?:interesting|cool|fun|surprising)\s+about"
    r")\s+(.+)$"
)


def is_interesting_fact_request(text: str) -> bool:
    """True for casual trivia prompts, not factual lookup questions."""
    clean = " ".join((text or "").split()).strip()
    if not clean:
        return False
    if _EXCLUDE.search(clean):
        return False
    if _TOPIC.search(clean):
        return True
    return any(p.search(clean) for p in _PATTERNS)


def extract_topic(text: str) -> str | None:
    """Optional topic from phrases like 'something cool about space'."""
    clean = " ".join((text or "").split()).strip()
    match = _TOPIC.search(clean)
    if not match:
        return None
    topic = match.group(1).strip().rstrip("?.!")
    return topic or None


def interesting_fact_system_prompt() -> str:
    return (
        "You share one surprising, true, interesting fact. "
        "Write 2-4 short sentences suitable for text-to-speech. "
        "Pick a varied topic unless the user asks for a specific one. "
        "Be accurate and engaging; no disclaimers or preamble."
    )


def interesting_fact_user_prompt(text: str, *, topic: str | None = None) -> str:
    resolved = topic or extract_topic(text)
    if resolved:
        return f"Share something interesting about {resolved}."
    return "Share something interesting from any topic."
