#!/usr/bin/env python3
"""Bias Arka toward human-sounding README/markdown files instead of chat dumps."""

from __future__ import annotations

import os
import re
from pathlib import Path

_GUIDE_NAME = "human-docs-guide.md"
_DEFAULT_MAX_CHARS = 3200

_COMPACT_RULE = (
    "Human-facing docs (README, CHANGELOG, CONTRIBUTING, docs/*.md): write to files, not chat. "
    "In chat, confirm the path and one-line summary only. "
    "Prose must sound human—concrete, direct, no AI filler or hollow intros."
)

_HUMAN_DOC_GOAL_RE = re.compile(
    r"(?i)\b("
    r"readme|changelog|contributing|release notes|documentation|docs page|"
    r"markdown file|\.md\b|\.mdx\b|writeup|write-up|user guide|"
    r"installation guide|quickstart|quick start|about page|"
    r"human.?sounding|sound human|natural.?language|not ai|"
    r"portfolio|cover letter|migration guide|adr\b|architecture decision"
    r")\b"
)

_WRITE_DOC_RE = re.compile(
    r"(?i)\b(?:write|draft|create|update|rewrite|generate|compose|add)\b"
    r".*\b(?:readme|changelog|contributing|docs?|markdown|\.md|release notes)\b"
    r"|\b(?:readme|changelog|contributing)\b.*\b(?:write|draft|create|update|rewrite)\b"
)


def _enabled() -> bool:
    return os.environ.get("HUMAN_DOCS_BIAS", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _mode() -> str:
    raw = os.environ.get("HUMAN_DOCS_BIAS_MODE", "always").strip().lower()
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


def is_human_doc_goal(goal: str) -> bool:
    return bool(_HUMAN_DOC_GOAL_RE.search(goal or ""))


def wants_file_write(goal: str) -> bool:
    return bool(_WRITE_DOC_RE.search(goal or ""))


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
    return is_human_doc_goal(goal) or wants_file_write(goal)


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


def screenshot_context(*, limit: int = 5) -> str:
    """Recent screenshot paths for human-facing doc generation."""
    try:
        from arka.core.screenshot_paths import docs_screenshot_context

        return docs_screenshot_context(limit=limit)
    except ImportError:
        return ""


def context_for(
    goal: str = "",
    *,
    coding: bool = False,
    limit_chars: int = _DEFAULT_MAX_CHARS,
) -> str:
    if not _enabled():
        return ""
    mode = _mode()
    if mode == "always":
        parts = [_COMPACT_RULE]
        if is_human_doc_goal(goal) or wants_file_write(goal) or coding:
            body = read_guide(max_chars=limit_chars)
            if body:
                path = guide_path()
                label = path.name if path else _GUIDE_NAME
                parts.append(f"Human docs guide ({label}):\n{body}")
        shot_ctx = screenshot_context(limit=5)
        if shot_ctx and (is_human_doc_goal(goal) or wants_file_write(goal)):
            parts.append(shot_ctx)
        return "\n\n".join(parts).strip()
    if not should_include(goal, coding=coding):
        return ""
    body = read_guide(max_chars=limit_chars)
    parts = [_COMPACT_RULE]
    if body:
        path = guide_path()
        label = path.name if path else _GUIDE_NAME
        parts.append(f"Human docs guide ({label}):\n{body}")
    shot_ctx = screenshot_context(limit=5)
    if shot_ctx and (is_human_doc_goal(goal) or wants_file_write(goal)):
        parts.append(shot_ctx)
    return "\n\n".join(parts).strip()


def suggest_output_path(goal: str, *, cwd: Path | None = None) -> str:
    """Best-effort default output path from natural language."""
    text = (goal or "").lower()
    root = cwd or Path.cwd()
    if "changelog" in text:
        return str(root / "CHANGELOG.md")
    if "contribut" in text:
        return str(root / "CONTRIBUTING.md")
    if re.search(r"docs?/|guide|documentation page", text):
        slug = re.sub(r"[^a-z0-9]+", "-", text.split("docs")[-1][:40]).strip("-") or "guide"
        return str(root / "docs" / "guides" / f"{slug}.mdx")
    return str(root / "README.md")


def status() -> dict[str, object]:
    path = guide_path()
    return {
        "enabled": _enabled(),
        "mode": _mode(),
        "path": str(path) if path else None,
        "bytes": path.stat().st_size if path and path.is_file() else 0,
    }
