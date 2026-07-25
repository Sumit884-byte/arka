"""Detect Arka Nudge requests — benefits-only vs compare mode."""

from __future__ import annotations

import re

_NUDGE_EXPLICIT = re.compile(
    r"(?i)\b(?:arka\s+)?nudge(?:\s+me|\s+mode|\s+arka)?\b"
)

_PURCHASE_DECISION = re.compile(
    r"(?i)\b("
    r"should\s+i\s+(?:buy|get|purchase|invest\s+in|subscribe\s+to|try|switch\s+to)|"
    r"is\s+it\s+worth\s+(?:it\s+)?(?:to\s+)?(?:buy|get|having|investing)|"
    r"worth\s+(?:buying|getting|the\s+money|it)|"
    r"do\s+i\s+need\s+(?:a|an|to\s+get)|"
    r"would\s+you\s+(?:buy|get|recommend)"
    r")\b"
)

_COMPARE = re.compile(
    r"(?i)\b("
    r"already\s+(?:do|have|go|work\s+out|exercise|own|use)|"
    r"i\s+already|"
    r"which\s+is\s+better|"
    r"what(?:'s|\s+is)\s+better|"
    r"better\s+than|"
    r"compared\s+to|"
    r"compare|"
    r"comparison|"
    r"versus|"
    r"\bvs\.?\b|"
    r"instead\s+of|"
    r"rather\s+than|"
    r"or\s+(?:a|an|just|maybe|would)|"
    r"alternative|"
    r"trade[- ]?off|"
    r"both\s+options|"
    r"either\s+.+\s+or"
    r")\b"
)

_OR_CHOICE = re.compile(
    r"(?i)\b(.+?)\s+or\s+(.+?)(?:\s+(?:which|what|is\s+better|should))?\??$"
)


def is_nudge_request(text: str) -> bool:
    """True when the user wants a nudge-style purchase/decision answer."""
    clean = " ".join((text or "").split()).strip()
    if not clean:
        return False
    if _NUDGE_EXPLICIT.search(clean):
        return True
    if _PURCHASE_DECISION.search(clean) and not _looks_like_technical_question(clean):
        return True
    return False


def _looks_like_technical_question(text: str) -> bool:
    """Skip coding/product support questions that happen to contain 'should I'."""
    return bool(
        re.search(
            r"(?i)\b(?:api|docker|kubernetes|git|python|typescript|react|deploy|"
            r"database|sql|bug|error|stack trace|pip install|npm)\b",
            text,
        )
    )


def is_compare_mode(text: str) -> bool:
    """True when the user names alternatives, existing habits, or asks to compare."""
    clean = " ".join((text or "").split()).strip()
    if not clean:
        return False
    if _COMPARE.search(clean):
        return True
    if _OR_CHOICE.search(clean):
        return True
    return False


def nudge_mode(text: str) -> str:
    """Return 'compare' or 'nudge'."""
    return "compare" if is_compare_mode(text) else "nudge"


def strip_nudge_prefix(text: str) -> str:
    clean = " ".join((text or "").split()).strip()
    return re.sub(r"(?i)^(?:arka\s+)?nudge(?:\s+me|\s+mode)?\s*[-:]?\s*", "", clean).strip() or clean


def nudge_system_prompt(*, mode: str = "nudge") -> str:
    try:
        from arka.core.contextual_answer import compare_context_instructions, nudge_context_instructions

        nudge_ctx = nudge_context_instructions()
        compare_ctx = compare_context_instructions()
    except ImportError:
        nudge_ctx = compare_ctx = ""

    if mode == "compare":
        return (
            "You are Arka Nudge in compare mode. The user mentioned alternatives, "
            "existing habits, or asked which option is better. Give a fair, practical comparison: "
            "name what each option actually solves, who each fits, and when one beats the other. "
            "Use plain language, 3–6 short paragraphs or a tight bullet list. "
            "End with a clear recommendation for their situation—not generic advice. "
            "No hype, no benefits-only framing. Acknowledge tradeoffs honestly."
            + compare_ctx
        )
    return (
        "You are Arka Nudge. The user is deciding whether to buy or adopt something. "
        "List ONLY the benefits and upside of the thing they asked about in the main pitch. "
        "Do not mention downsides, costs, or 'it depends' in the benefits section. "
        "Sound like an enthusiastic friend nudging them toward yes—concrete benefits, "
        "3–8 bullet points or 2–4 short paragraphs. "
        "End with one punchy line encouraging the purchase/adoption."
        + nudge_ctx
    )


def nudge_user_prompt(text: str, *, mode: str | None = None) -> str:
    resolved = mode or nudge_mode(text)
    question = strip_nudge_prefix(text)
    if resolved == "compare":
        return (
            f"Compare options and recommend what fits best:\n{question}\n\n"
            "Weigh tradeoffs honestly. If they already exercise or own something similar, factor that in."
        )
    return f"Nudge me toward yes — benefits only:\n{question}"


def route_command(text: str) -> str | None:
    if is_nudge_request(text):
        import shlex

        return "nudge " + shlex.quote(strip_nudge_prefix(text) or text.strip())
    return None
