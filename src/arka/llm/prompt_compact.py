"""Deterministic compact intermediate form for verbose user prompts."""

from __future__ import annotations

import os
import re
from dataclasses import dataclass


PROTECTED_BLOCK_RE = re.compile(
    r"(```.*?```|https?://[^\s)>\"]+|(?:^|\n)\s*(?:curl|wget|git|python3?|npm|pnpm|yarn|docker|kubectl|ssh)\s+[^\n]+)",
    re.DOTALL | re.IGNORECASE,
)


@dataclass(frozen=True)
class CompactPromptResult:
    original: str
    compact: str
    transformations: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return self.original != self.compact


def enabled() -> bool:
    return os.environ.get("ARKA_PROMPT_COMPACT", "1").strip().lower() not in {"0", "false", "off", "no"}


def _threshold() -> int:
    try:
        return max(400, int(os.environ.get("ARKA_PROMPT_COMPACT_MIN_CHARS", "900")))
    except ValueError:
        return 900


def _protect(text: str) -> tuple[str, list[str]]:
    protected: list[str] = []

    def repl(match: re.Match[str]) -> str:
        protected.append(match.group(0))
        return f"__ARKA_PROTECTED_{len(protected) - 1}__"

    return PROTECTED_BLOCK_RE.sub(repl, text), protected


def _restore(text: str, protected: list[str]) -> str:
    for index, value in enumerate(protected):
        text = text.replace(f"__ARKA_PROTECTED_{index}__", value)
    return text


def _sentence_split(text: str) -> list[str]:
    parts = re.split(r"(?<=[.!?])\s+|\n+", text)
    return [part.strip(" \t-•") for part in parts if part.strip(" \t-•")]


def _is_high_signal(sentence: str) -> bool:
    return bool(
        re.search(
            r"\b(?:must|should|need|needs|fix|add|remove|keep|preserve|do not|don't|only|never|"
            r"file|path|url|api|test|verify|run|output|format|constraint|requirement|error|bug|failed|"
            r"implement|create|build|update|route|skill|docs?|security|fallback)\b",
            sentence,
            re.IGNORECASE,
        )
    )


def compact_user_prompt(prompt: str, *, force: bool = False, task: str | None = None) -> CompactPromptResult:
    """Convert verbose user input into a compact, intent-preserving IR.

    The original text should still be used for routing, security, logs, and exact
    command detection. This representation is only for model-facing prompts.
    """
    original = prompt
    if not prompt or not (force or enabled()):
        return CompactPromptResult(original, original, ())
    if (task or "").strip().lower() in {"route", "routing"}:
        return CompactPromptResult(original, original, ())
    stripped = prompt.strip()
    if stripped.startswith("Task IR:"):
        return CompactPromptResult(original, original, ())
    if len(stripped) < _threshold() and stripped.count("\n") < 8:
        return CompactPromptResult(original, original, ())

    masked, protected = _protect(stripped)
    transformations: list[str] = []
    normalized = re.sub(r"[ \t]+", " ", masked)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized).strip()
    if normalized != masked:
        transformations.append("normalized whitespace")

    sentences = _sentence_split(normalized)
    seen: set[str] = set()
    requirements: list[str] = []
    context: list[str] = []
    for sentence in sentences:
        key = re.sub(r"\W+", " ", sentence).strip().lower()
        if not key or key in seen:
            if key:
                transformations.append("removed duplicate sentence")
            continue
        seen.add(key)
        if _is_high_signal(sentence):
            requirements.append(sentence)
        elif len(context) < 4:
            context.append(sentence)

    if not requirements:
        return CompactPromptResult(original, original, ())

    try:
        max_items = max(8, int(os.environ.get("ARKA_PROMPT_COMPACT_MAX_ITEMS", "24") or "24"))
    except ValueError:
        max_items = 24
    trimmed = requirements[:max_items]
    if len(requirements) > len(trimmed):
        transformations.append("capped low-priority requirements")

    lines = ["Task IR:"]
    if context:
        lines.append("Context:")
        lines.extend(f"- {item}" for item in context)
    lines.append("Requirements:")
    lines.extend(f"- {item}" for item in trimmed)
    lines.append("Rules:")
    lines.append("- Preserve literals/order; do not invent facts, links, files, APIs, or requirements.")
    compact = _restore("\n".join(lines), protected)
    if len(compact) >= len(original):
        return CompactPromptResult(original, original, ())
    transformations.append("converted to compact task IR")
    return CompactPromptResult(original, compact, tuple(dict.fromkeys(transformations)))
