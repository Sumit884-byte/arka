"""Deterministic scope invariants for risky or ambiguous code-edit requests."""
from __future__ import annotations

import re


def animation_scope_guard(goal: str) -> str:
    text = goal.lower()
    if not re.search(r"\b(?:add|improve|enhance|change|more)\b.*\banimations?\b", text):
        return ""
    if re.search(r"\b(?:test|tests|fixture|snapshot|spec)\b", text):
        return "User explicitly named test-related animation code; edit only the named test scope."
    return (
        "Animation scope guard: modify only production UI/components/styles and their animation assets. "
        "Do not modify tests, fixtures, snapshots, test animations, or assertions. Preserve existing test behavior."
    )
