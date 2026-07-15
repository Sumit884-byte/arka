"""Deterministic, intent-preserving optimization for user-authored prompts."""
from __future__ import annotations

import argparse
import os
import re
from dataclasses import dataclass


@dataclass(frozen=True)
class OptimizationResult:
    original: str
    optimized: str
    transformations: tuple[str, ...]

    @property
    def changed(self) -> bool:
        return self.original != self.optimized


def enabled() -> bool:
    return os.environ.get("ARKA_PROMPT_OPTIMIZE", "1").strip().lower() not in {"0", "false", "off", "no"}


def _protected(text: str) -> bool:
    stripped = text.strip()
    return bool(
        stripped.startswith("```")
        or (stripped.startswith(("{", "[")) and stripped.endswith(("}", "]")))
        or re.match(r"^(?:https?://|(?:curl|wget|git|python3?|npm|pnpm|yarn|docker|kubectl|ssh)\s)", stripped, re.I) is not None
    )


def optimize_user_prompt(prompt: str, *, force: bool = False) -> OptimizationResult:
    original = prompt
    text = prompt.strip()
    if not text or not (force or enabled()) or _protected(text):
        return OptimizationResult(original, original, ())
    transformations: list[str] = []
    normalized = re.sub(r"\s+", " ", text)
    if normalized != text:
        transformations.append("normalized whitespace")
    text = normalized
    additions: list[str] = []
    lower = text.lower()
    if not re.search(r"\b(?:must|should|need to|do not|don't|without|only)\b", lower):
        additions.append("Preserve the user's stated intent and do not invent requirements, links, or facts.")
        transformations.append("added intent guard")
    if not re.search(r"\b(?:return|output|format|show|explain|list|give me)\b", lower):
        additions.append("Return the result first, followed by concise assumptions or next steps when useful.")
        transformations.append("clarified output")
    if additions:
        text = text.rstrip(" .") + ". " + " ".join(additions)
    return OptimizationResult(original, text, tuple(transformations))


def optimize(prompt: str, *, rounds: int = 1, role: str = "") -> str:
    """Backward-compatible explicit optimizer; rounds are bounded and local."""
    result = optimize_user_prompt(prompt, force=True)
    text = result.optimized
    if role:
        text = f"You are {role}. {text}"
    return text


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Optimize a prompt locally without changing its intent")
    parser.add_argument("prompt")
    parser.add_argument("--rounds", type=int, default=1, help="accepted for compatibility; optimization is bounded")
    parser.add_argument("--role", default="")
    args = parser.parse_args(argv)
    try:
        print(optimize(args.prompt, rounds=args.rounds, role=args.role))
    except ValueError as exc:
        parser.error(str(exc))
    return 0
