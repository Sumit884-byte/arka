"""Consistent terminal blocks for Arka CLI output."""

from __future__ import annotations

import re

_BLOCK_RE = re.compile(r"^━━━\s+(.+?)\s+━━━$")


def active_model_label() -> str | None:
    try:
        from arka.llm.fallback import llm_last_model

        row = llm_last_model()
        if row:
            return f"{row[0]}/{row[1]}"
    except Exception:
        pass
    return None


def print_block(title: str, body: str, *, model: str | None = None) -> None:
    """Standard answer block: green-style header, indented body, optional model footer."""
    title = (title or "Answer").strip()
    text = (body or "").strip()
    print(f"━━━ {title} ━━━")
    print()
    if text:
        for line in text.splitlines():
            stripped = line.rstrip()
            if stripped:
                print(f"  {stripped}")
            else:
                print()
    label = model if model is not None else active_model_label()
    if label:
        print()
        print(f"  Model: {label}")


def parse_block(text: str) -> tuple[str, str] | None:
    """Return (title, body) if text starts with a ━━━ header block."""
    lines = text.splitlines()
    if not lines:
        return None
    m = _BLOCK_RE.match(lines[0].strip())
    if not m:
        return None
    body = "\n".join(lines[1:]).strip()
    body = re.sub(r"^\s{2}", "", body, flags=re.MULTILINE)
    body = re.sub(r"\n\s*Model:.*$", "", body, flags=re.S).strip()
    return m.group(1).strip(), body
