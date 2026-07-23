#!/usr/bin/env python3
"""Default frontend copy guide — what belongs in user-facing UI vs internal docs."""
from __future__ import annotations

import os
import re
from pathlib import Path

_GUIDE_NAME = "frontend-content-guide.md"
_DEFAULT_MAX_CHARS = 3500

_FRONTEND_GOAL_RE = re.compile(
    r"(?i)\b("
    r"frontend|front-end|front end|ui|ux|user interface|landing page|landing|"
    r"webapp|web app|website|mockup|wireframe|dashboard|settings page|"
    r"button|modal|toast|navbar|sidebar|hero|copy|microcopy|onboarding|"
    r"screen|viewport|component|jsx|tsx|vue|svelte|css|tailwind|"
    r"design|layout|typography|accessibility|a11y|non-profit|nonprofit|for-profit|"
    r"profit|marketing page|about page|pricing page|error message|empty state|"
    r"status banner|dev status|service status|ui copy|user-facing copy|microcopy"
    r")\b"
)


def _enabled() -> bool:
    return os.environ.get("FRONTEND_CONTENT_GUIDE", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _mode() -> str:
    raw = os.environ.get("FRONTEND_CONTENT_GUIDE_MODE", "auto").strip().lower()
    if raw in {"always", "on", "all"}:
        return "always"
    if raw in {"off", "never", "0"}:
        return "off"
    return "auto"


def guide_path() -> Path | None:
    try:
        from arka.paths import checkout_root, package_dir

        bundled = package_dir() / "bundled" / _GUIDE_NAME
        if bundled.is_file():
            return bundled
        root = checkout_root()
        if root:
            docs = root / "docs" / "guides" / _GUIDE_NAME
            if docs.is_file():
                return docs
    except ImportError:
        pass
    return None


def is_frontend_goal(goal: str) -> bool:
    return bool(_FRONTEND_GOAL_RE.search(goal or ""))


def should_include(goal: str = "", *, coding: bool = False) -> bool:
    if not _enabled():
        return False
    mode = _mode()
    if mode == "off":
        return False
    if mode == "always":
        return True
    if coding:
        return True
    return is_frontend_goal(goal)


def read_guide(*, max_chars: int = _DEFAULT_MAX_CHARS) -> str:
    path = guide_path()
    if path is None:
        return ""
    try:
        from arka.agent.md_doc import read_markdown

        return read_markdown(path, max_chars=max_chars)
    except ImportError:
        text = path.read_text(encoding="utf-8", errors="replace").strip()
        if len(text) > max_chars:
            text = text[:max_chars].rstrip() + "\n…"
        return text


def context_for(
    goal: str = "",
    *,
    coding: bool = False,
    limit_chars: int = _DEFAULT_MAX_CHARS,
) -> str:
    if not should_include(goal, coding=coding):
        return ""
    body = read_guide(max_chars=limit_chars)
    if not body:
        return ""
    path = guide_path()
    label = path.name if path else _GUIDE_NAME
    return f"Frontend content guide ({label}):\n{body}".strip()


def status() -> dict[str, object]:
    path = guide_path()
    return {
        "enabled": _enabled(),
        "mode": _mode(),
        "path": str(path) if path else None,
        "bytes": path.stat().st_size if path and path.is_file() else 0,
    }
