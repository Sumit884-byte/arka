"""Deterministic, opt-in chunking for oversized model prompts."""
from __future__ import annotations

from collections.abc import Callable


def split_prompt(text: str, max_chars: int) -> list[str]:
    """Split on paragraph/line boundaries while preserving all input text."""
    if max_chars <= 0 or len(text) <= max_chars:
        return [text]
    parts: list[str] = []
    current = ""
    for block in text.split("\n\n"):
        candidate = block if not current else current + "\n\n" + block
        if current and len(candidate) > max_chars:
            parts.append(current)
            current = block
        elif len(block) > max_chars:
            if current:
                parts.append(current)
                current = ""
            parts.extend(block[i : i + max_chars] for i in range(0, len(block), max_chars))
        else:
            current = candidate
    if current:
        parts.append(current)
    return parts or [text]


def complete_chunked(
    complete: Callable[[str, str], str],
    system: str,
    user: str,
    *,
    max_chars: int = 12000,
) -> str:
    """Process chunks and ask the model to synthesize their marked outputs."""
    chunks = split_prompt(user, max_chars)
    if len(chunks) == 1:
        return complete(system, user)
    outputs = []
    for index, chunk in enumerate(chunks, 1):
        outputs.append(complete(
            system,
            f"You are processing chunk {index}/{len(chunks)} of one user request. "
            "Analyze only this chunk; preserve concrete facts and do not invent missing context.\n\n"
            f"<chunk>\n{chunk}\n</chunk>",
        ))
    joined = "\n\n".join(f"<chunk-result index=\"{i}\">\n{o}\n</chunk-result>" for i, o in enumerate(outputs, 1))
    return complete(
        system,
        "Synthesize the following chunk results into one coherent answer. Preserve all relevant details, "
        "remove duplication, and do not add facts absent from the results.\n\n" + joined,
    )
