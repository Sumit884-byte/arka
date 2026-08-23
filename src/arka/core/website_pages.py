#!/usr/bin/env python3
"""Bias agents toward sensible website information architecture and page boundaries."""

from __future__ import annotations

import os
import re
from pathlib import Path

_GUIDE_NAME = "website-pages-guide.md"
_DEFAULT_MAX_CHARS = 4800

_COMPACT_RULE = (
    "Website structure: plan pages before writing UI or copy. One primary job per page. "
    "Split tutorials from reference; use hub + detail for lists. Primary nav ≤7 items. "
    "Output a sitemap (URL, job, sections) before implementing routes."
)

_WEBSITE_GOAL_RE = re.compile(
    r"(?i)\b("
    r"website|web site|webpage|web page|landing page|marketing site|"
    r"sitemap|site map|site structure|site architecture|information architecture|\bia\b|"
    r"nav(?:igation)?|navbar|menu structure|routes? for|pages? for|"
    r"divide.*(?:content|pages)|organiz(?:e|ing).*(?:pages|content|site)|"
    r"split.*(?:pages|content)|multi.?page|page layout|"
    r"next\.js.*(?:pages|routes)|react router|app router"
    r")\b"
)

_PLAN_GOAL_RE = re.compile(
    r"(?i)\b("
    r"plan (?:the )?(?:site|pages|sitemap|structure|ia)|"
    r"organiz(?:e|ing)|divide|split|structure|map out|"
    r"what pages|which pages|how many pages|page breakdown"
    r")\b"
)


def _enabled() -> bool:
    return os.environ.get("WEBSITE_PAGES_BIAS", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _mode() -> str:
    raw = os.environ.get("WEBSITE_PAGES_BIAS_MODE", "auto").strip().lower()
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


def is_website_goal(goal: str) -> bool:
    return bool(_WEBSITE_GOAL_RE.search(goal or ""))


def wants_page_plan(goal: str) -> bool:
    if not is_website_goal(goal):
        return False
    return bool(_PLAN_GOAL_RE.search(goal or "")) or bool(
        re.search(r"(?i)\b(?:build|create|make|design|scaffold)\b.*\b(?:website|site|app)\b", goal or "")
    )


def should_include(goal: str = "", *, coding: bool = False) -> bool:
    if not _enabled():
        return False
    mode = _mode()
    if mode == "off":
        return False
    if mode == "always":
        return True
    if coding and is_website_goal(goal):
        return True
    return is_website_goal(goal) or wants_page_plan(goal)


def compact_rule() -> str:
    if not _enabled():
        return ""
    return _COMPACT_RULE


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
    if not _enabled():
        return ""
    if not should_include(goal, coding=coding):
        return ""
    parts = [compact_rule()]
    guide = read_guide(max_chars=max(1200, limit_chars - len(parts[0]) - 80))
    if guide:
        parts.append("Website pages guide:\n" + guide)
    if wants_page_plan(goal):
        parts.append(
            "User wants a page plan: run website_pages plan (or output sitemap table) "
            "before writing components or routes."
        )
    try:
        from arka.core.website_archetypes import context_for as archetype_context

        hint = archetype_context(goal, limit_chars=max(400, limit_chars // 3))
        if hint:
            parts.append(hint)
    except ImportError:
        pass
    text = "\n\n".join(p for p in parts if p).strip()
    if len(text) > limit_chars:
        text = text[:limit_chars].rstrip() + "\n…"
    return text


def status() -> dict[str, object]:
    path = guide_path()
    return {
        "enabled": _enabled(),
        "mode": _mode(),
        "guide_path": str(path) if path else None,
        "guide_bytes": path.stat().st_size if path and path.is_file() else 0,
    }
