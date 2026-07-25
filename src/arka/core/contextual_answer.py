#!/usr/bin/env python3
"""Proactive context and comparison framing for answers."""

from __future__ import annotations

import os
import re

_COMPACT_RULE = (
    "When the question is explanatory or decision-oriented, add brief context the user "
    "may not know to ask for: what category the topic belongs to, who it is for, and "
    "2–3 related alternatives or adjacent options for comparison—after the direct answer."
)

_CONTEXTUAL_RE = re.compile(
    r"(?i)\b("
    r"what\s+is|what\s+are|explain|tell\s+me\s+about|how\s+does|how\s+do|"
    r"should\s+i|worth\s+it|recommend|suggest|which\s+(?:is|one|should)|"
    r"best\s+(?:way|option|tool|approach)|"
    r"pros\s+and\s+cons|advantages|disadvantages|"
    r"compare|comparison|versus|\bvs\.?\b|difference\s+between|"
    r"alternatives?|options?\s+for|"
    r"new\s+to|beginner|don't\s+know|do\s+not\s+know|"
    r"context|background|landscape|"
    r"what\s+else|related"
    r")\b"
)

_EXCLUDE_RE = re.compile(
    r"(?i)\b("
    r"weather|forecast|temperature|"
    r"what\s+time|what(?:'s|\s+is)\s+the\s+date|"
    r"my\s+ip|disk\s+space|password|wifi|"
    r"headlines?|daily\s+brief|"
    r"commit|push|git\s+status|"
    r"traceback|stack\s+trace|syntaxerror"
    r")\b"
)

_EXPLICIT_RE = re.compile(
    r"(?i)\b(?:with\s+context|give\s+context|include\s+context|"
    r"contextual\s+answer|compare\s+to\s+other|related\s+options|"
    r"what\s+else\s+should\s+i\s+know|alternatives?\s+i\s+should\s+know)\b"
)


def _enabled() -> bool:
    return os.environ.get("CONTEXTUAL_ANSWER", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _mode() -> str:
    raw = os.environ.get("CONTEXTUAL_ANSWER_MODE", "auto").strip().lower()
    if raw in {"always", "on", "all"}:
        return "always"
    if raw in {"off", "never", "0"}:
        return "off"
    return "auto"


def wants_contextual_framing(text: str) -> bool:
    """True when an answer should include proactive context and comparisons."""
    if not _enabled():
        return False
    clean = " ".join((text or "").split()).strip()
    if not clean or len(clean.split()) < 3:
        return False
    if _EXCLUDE_RE.search(clean):
        return False
    if _mode() == "always":
        return True
    if _EXPLICIT_RE.search(clean):
        return True
    return bool(_CONTEXTUAL_RE.search(clean))


def answer_instructions(text: str, *, force: bool = False) -> str:
    """Prompt fragment to append for contextual/comparison-rich answers."""
    if not force and not wants_contextual_framing(text):
        return ""
    return (
        "\n\nContext framing (include even if the user did not ask):\n"
        "1. Direct answer first — 1–3 sentences.\n"
        "2. **Context** — what this is, what category it sits in, and who typically uses it "
        "(help someone who does not know the landscape).\n"
        "3. **Related options** — 2–3 alternatives, adjacent tools, or common comparisons "
        "the user might not know to ask about; one line each on when each fits.\n"
        "Keep it practical and concise; do not pad with generic filler."
    )


def nudge_context_instructions() -> str:
    """Extra framing for nudge mode — context without killing the yes-nudge."""
    return (
        "\n\nAlso include:\n"
        "- **Context** (2–3 sentences): what the thing is and who it is for.\n"
        "- **You might also consider**: 2–3 related alternatives the user may not know "
        "(one short line each; do not argue against the main purchase).\n"
        "Then list benefits and end with a punchy nudge."
    )


def compare_context_instructions() -> str:
    """Extra framing for compare mode — background for newcomers."""
    return (
        "\n\nStart with **Background** (2–3 sentences) so someone new to the topic understands "
        "what each option category is. Then compare options fairly and recommend clearly."
    )


def context_for(goal: str = "", *, limit_chars: int = 800) -> str:
    if not _enabled():
        return ""
    if _mode() == "always" or wants_contextual_framing(goal):
        text = _COMPACT_RULE
        if len(text) > limit_chars:
            text = text[:limit_chars].rstrip() + "…"
        return text
    return ""


def compact_rule() -> str:
    return _COMPACT_RULE if _enabled() else ""


def route_command(text: str) -> str | None:
    clean = " ".join((text or "").split()).strip()
    if not clean:
        return None
    if _EXPLICIT_RE.search(clean) or (
        _CONTEXTUAL_RE.search(clean) and re.search(r"(?i)\b(?:explain|what\s+is|tell\s+me)\b", clean)
    ):
        import shlex

        return "contextual_answer " + shlex.quote(clean)
    return None
