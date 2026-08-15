"""Natural-language routing for prompt_coach — teach and improve prompt writing."""

from __future__ import annotations

import re
import shlex

# Deterministic rewriter — leave those to prompt_optimize.
_OPTIMIZE = re.compile(
    r"(?i)\b(?:optimize|rewrite)\s+(?:this\s+)?prompt\s*[:\-]?\s*\S"
)

_IMPROVE_THIS = re.compile(
    r"(?i)\bimprove\s+(?:this\s+)?prompt\s*[:\-]\s*\S"
)

_EXPLICIT = re.compile(
    r"(?i)\b(?:"
    r"prompt\s+coach(?:ing)?|"
    r"help\s+(?:me\s+)?(?:write|craft|create)\s+(?:a\s+)?better\s+prompts?|"
    r"help\s+(?:me\s+)?(?:with\s+)?prompt\s+writ(?:ing|e)|"
    r"how\s+(?:do\s+i|to)\s+write\s+(?:a\s+)?(?:good|better|great|effective)\s+prompts?|"
    r"teach\s+me\s+(?:to\s+)?(?:write\s+)?(?:better\s+)?prompts?|"
    r"prompt\s+writ(?:ing|e)\s+(?:help|tips|guide|advice)|"
    r"prompting\s+(?:help|tips|guide|advice|coach(?:ing)?)|"
    r"better\s+prompting|"
    r"prompt\s+engineering\s+(?:help|tips|guide|for\s+beginners)"
    r")\b"
)

_DRAFT = re.compile(
    r"(?i)(?:"
    r"(?:coach|review|critique|help\s+(?:me\s+)?(?:with|improve))\s+(?:this\s+)?prompt\s*(?:for|:)\s*|"
    r"write\s+(?:a\s+)?better\s+prompt\s+(?:for|about)\s+"
    r")(.+)$"
)


def is_prompt_coach_request(text: str) -> bool:
    clean = " ".join((text or "").split()).strip()
    if not clean:
        return False
    if _OPTIMIZE.search(clean) or _IMPROVE_THIS.search(clean):
        return False
    if _EXPLICIT.search(clean):
        return True
    if _DRAFT.search(clean):
        return True
    return bool(
        re.search(
            r"(?i)\b(?:"
            r"make\s+my\s+prompts?\s+better|"
            r"how\s+can\s+i\s+prompt\s+(?:better|more\s+effectively)|"
            r"what\s+makes\s+a\s+good\s+prompt"
            r")\b",
            clean,
        )
    )


def extract_focus(text: str) -> str | None:
    """Optional topic or draft prompt from the user's request."""
    clean = " ".join((text or "").split()).strip()
    match = _DRAFT.search(clean)
    if match:
        focus = match.group(1).strip().rstrip("?.!")
        return focus or None
    match = re.search(
        r"(?i)\b(?:for|about)\s+(.+)$",
        clean,
    )
    if match and _EXPLICIT.search(clean):
        focus = match.group(1).strip().rstrip("?.!")
        if focus and len(focus.split()) >= 2:
            return focus
    return None


def route_command(cmd: str) -> str | None:
    clean = " ".join((cmd or "").split()).strip()
    if not is_prompt_coach_request(clean):
        return None
    return "prompt_coach " + shlex.quote(clean)


def nl_to_argv(cmd: str) -> list[str] | None:
    clean = " ".join((cmd or "").split()).strip()
    if not is_prompt_coach_request(clean):
        return None
    focus = extract_focus(clean)
    if focus:
        return ["coach", focus]
    return ["coach"]
