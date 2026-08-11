#!/usr/bin/env python3
"""ASCII isometric landing page design system — layout, tokens, and components."""
from __future__ import annotations

import os
import re
from pathlib import Path

_GUIDE_NAME = "ascii-isometric-landing-page.md"
_DEFAULT_MAX_CHARS = 4500

_DESIGN_GOAL_RE = re.compile(
    r"(?i)\b("
    r"ascii isometric|isometric ascii|isometric landing|halftone|"
    r"pill nav(?:igation)?|floating pill|floating header|segmented feature|"
    r"segmented card|developer landing|dev landing|saas landing|"
    r"terminal aesthetic|retro terminal|wireframe ascii|ascii art landing|"
    r"ascii-isometric-landing-page"
    r")\b"
)

_ALIASES = frozenset(
    {
        "ascii-isometric-landing-page",
        "ascii-isometric-landing-page.md",
        "ascii isometric landing page",
        "isometric landing page",
        "docs/guides/ascii-isometric-landing-page.md",
    }
)


def _enabled() -> bool:
    return os.environ.get("ASCII_ISOMETRIC_DESIGN_GUIDE", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _mode() -> str:
    raw = os.environ.get("ASCII_ISOMETRIC_DESIGN_GUIDE_MODE", "auto").strip().lower()
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


def bundled_guide_path() -> Path | None:
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


def is_design_goal(goal: str) -> bool:
    return bool(_DESIGN_GOAL_RE.search(goal or ""))


def should_include(goal: str = "", *, coding: bool = False) -> bool:
    if not _enabled():
        return False
    mode = _mode()
    if mode == "off":
        return False
    if mode == "always":
        return True
    if coding:
        return False
    return is_design_goal(goal)


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
    return f"ASCII isometric landing page design system ({label}):\n{body}".strip()


def resolve_alias(path: str, *, cwd: Path | None = None) -> str | None:
    del cwd
    raw = path.strip().strip("'\"")
    normalized = raw.lower().replace("\\", "/").lstrip("./")
    if normalized in _ALIASES or normalized.endswith("ascii-isometric-landing-page.md"):
        bundled = bundled_guide_path()
        return str(bundled) if bundled is not None else None
    return None


def status() -> dict[str, object]:
    path = guide_path()
    bundled = bundled_guide_path()
    return {
        "enabled": _enabled(),
        "mode": _mode(),
        "path": str(path) if path else None,
        "bundled_path": str(bundled) if bundled else None,
        "bytes": path.stat().st_size if path and path.is_file() else 0,
    }
