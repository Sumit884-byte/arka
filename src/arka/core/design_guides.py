#!/usr/bin/env python3
"""Merged frontend + Google DESIGN.md guides for agent context injection."""
from __future__ import annotations

from pathlib import Path

from arka.core import frontend_content, google_design


def should_include(goal: str = "", *, coding: bool = False) -> bool:
    return frontend_content.should_include(goal, coding=coding) or google_design.should_include(
        goal, coding=coding
    )


def context_for(
    goal: str = "",
    *,
    coding: bool = False,
    limit_chars: int = 3500,
) -> str:
    parts: list[str] = []
    if frontend_content.should_include(goal, coding=coding):
        block = frontend_content.context_for(goal, coding=coding, limit_chars=limit_chars)
        if block:
            parts.append(block)
    if google_design.should_include(goal, coding=coding):
        block = google_design.context_for(goal, coding=coding, limit_chars=limit_chars)
        if block:
            parts.append(block)
    return "\n\n".join(parts)


def read_guides(*, max_chars: int = 4000, coding: bool = True) -> str:
    parts: list[str] = []
    if frontend_content.should_include("", coding=coding):
        body = frontend_content.read_guide(max_chars=max_chars)
        if body:
            parts.append(body)
    if google_design.should_include("", coding=coding):
        body = google_design.read_guide(max_chars=max_chars)
        if body:
            parts.append(body)
    return "\n\n---\n\n".join(parts)


def resolve_markdown_alias(path: str, *, cwd: Path | None = None) -> str | None:
    raw = path.strip().strip("'\"")
    normalized = raw.lower().replace("\\", "/").lstrip("./")
    frontend_aliases = {
        "frontend-content-guide",
        "frontend-content-guide.md",
        "frontend-content",
        "docs/guides/frontend-content-guide.md",
    }
    if normalized in frontend_aliases or normalized.endswith("frontend-content-guide.md"):
        bundled = frontend_content.guide_path()
        return str(bundled) if bundled is not None else None
    return google_design.resolve_alias(path, cwd=cwd)


def status() -> dict[str, object]:
    return {
        "frontend_content": frontend_content.status(),
        "google_design": google_design.status(),
    }
