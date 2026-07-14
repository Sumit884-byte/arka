"""Consistent terminal blocks for Arka CLI output."""

from __future__ import annotations

import re

_BLOCK_RE = re.compile(r"^━━━\s+(.+?)\s+━━━$")


def active_model_label() -> str | None:
    try:
        from arka.llm.fallback import llm_last_model

        if not show_model_enabled():
            return None
        row = llm_last_model()
        if row:
            return f"{row[0]}/{row[1]}"
    except Exception:
        pass
    return None


def show_model_enabled() -> bool:
    """True unless SHOW_MODEL is explicitly disabled (default on)."""
    import os

    raw = os.environ.get("SHOW_MODEL", "").strip().lower()
    if raw in {"0", "false", "no", "off"}:
        return False
    return True


def active_context7_label() -> str | None:
    try:
        from arka.integrations.context7_mcp import context7_usage_label, show_context7_enabled

        if not show_context7_enabled():
            return None
        return context7_usage_label()
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
    docs = active_context7_label()
    if label or docs:
        print()
    if label:
        print(f"  Model: {label}")
    if docs:
        print(f"  Docs: {docs}")


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
    body = re.sub(r"\n\s*Docs:.*$", "", body, flags=re.S).strip()
    return m.group(1).strip(), body
