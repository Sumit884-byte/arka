"""Detect Arka Council deliberation requests."""

from __future__ import annotations

import re

_EXCLUDE = re.compile(
    r"(?i)\b(?:"
    r"security\s+council|"
    r"student\s+council|"
    r"city\s+council|"
    r"town\s+council|"
    r"un\s+security\s+council|"
    r"european\s+council"
    r")\b"
)

_COUNCIL_PREFIXES: tuple[re.Pattern[str], ...] = (
    re.compile(r"(?i)^(?:please\s+)?(?:arka\s+)?council\s+list\b"),
    re.compile(r"(?i)^(?:please\s+)?(?:arka\s+)?council\s+of\s+(?:experts\s+)?"),
    re.compile(r"(?i)^(?:please\s+)?(?:arka\s+)?council\s+"),
    re.compile(r"(?i)^(?:please\s+)?deliberate\s+(?:with\s+)?(?:arka\s+)?(?:on\s+)?"),
    re.compile(r"(?i)^(?:please\s+)?ask\s+the\s+council\s+(?:about\s+|on\s+)?"),
    re.compile(r"(?i)^(?:please\s+)?(?:have\s+)?(?:the\s+)?council\s+deliberate\s+(?:on\s+)?"),
)


def is_council_request(text: str) -> bool:
    clean = " ".join((text or "").split()).strip()
    if not clean:
        return False
    if _EXCLUDE.search(clean):
        return False
    if re.match(r"(?i)^council\s+list\b", clean):
        return True
    return any(p.search(clean) for p in _COUNCIL_PREFIXES)


def extract_question(text: str) -> str:
    clean = " ".join((text or "").split()).strip()
    if not clean:
        return ""
    if re.match(r"(?i)^council\s+list\b", clean):
        return ""

    patterns: tuple[tuple[re.Pattern[str], int], ...] = (
        (re.compile(r"(?i)^(?:please\s+)?(?:arka\s+)?council\s+of\s+(?:experts\s+)?(?:on\s+)?(.+)$"), 1),
        (re.compile(r"(?i)^(?:please\s+)?(?:arka\s+)?council\s+(.+)$"), 1),
        (re.compile(r"(?i)^(?:please\s+)?deliberate\s+(?:with\s+)?(?:arka\s+)?(?:on\s+)?(.+)$"), 1),
        (re.compile(r"(?i)^(?:please\s+)?ask\s+the\s+council\s+(?:about\s+|on\s+)?(.+)$"), 1),
        (re.compile(r"(?i)^(?:please\s+)?(?:have\s+)?(?:the\s+)?council\s+deliberate\s+(?:on\s+)?(.+)$"), 1),
    )
    for pattern, group in patterns:
        match = pattern.match(clean)
        if match:
            question = (match.group(group) or "").strip().strip("'\"")
            if question.lower() == "list":
                return ""
            return question
    return ""
