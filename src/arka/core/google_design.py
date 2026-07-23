#!/usr/bin/env python3
"""Google DESIGN.md format guide — visual identity for coding agents."""
from __future__ import annotations

import os
import re
from pathlib import Path

_GUIDE_NAME = "google-design.md"
_DEFAULT_MAX_CHARS = 4000

_DESIGN_GOAL_RE = re.compile(
    r"(?i)\b("
    r"frontend|front-end|front end|ui|ux|user interface|landing page|landing|"
    r"webapp|web app|website|mockup|wireframe|dashboard|settings page|"
    r"button|modal|toast|navbar|sidebar|hero|onboarding|"
    r"screen|viewport|component|jsx|tsx|vue|svelte|css|tailwind|"
    r"design|layout|typography|accessibility|a11y|theme|design system|"
    r"design\.md|google design|stitch|material|visual identity|color palette|"
    r"spacing|tokens|design tokens"
    r")\b"
)

_ALIASES = frozenset(
    {
        "google-design",
        "google-design.md",
        "google design",
        "google design.md",
        "design",
        "design.md",
        "docs/guides/google-design.md",
    }
)


def _enabled() -> bool:
    return os.environ.get("GOOGLE_DESIGN_GUIDE", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _mode() -> str:
    raw = os.environ.get("GOOGLE_DESIGN_GUIDE_MODE", "auto").strip().lower()
    if raw in {"always", "on", "all"}:
        return "always"
    if raw in {"off", "never", "0"}:
        return "off"
    return "auto"


def project_design_path(*, cwd: Path | None = None) -> Path | None:
    bases: list[Path] = []
    if cwd is not None:
        bases.append(cwd)
    else:
        bases.append(Path.cwd())
    try:
        from arka.paths import checkout_root

        root = checkout_root()
        if root is not None:
            bases.append(root)
    except ImportError:
        pass
    seen: set[Path] = set()
    for base in bases:
        try:
            resolved = base.resolve()
        except OSError:
            continue
        if resolved in seen:
            continue
        seen.add(resolved)
        for name in ("DESIGN.md", "design.md"):
            candidate = resolved / name
            if candidate.is_file():
                return candidate
    return None


def guide_path() -> Path | None:
    project = project_design_path()
    if project is not None:
        return project
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
        return True
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
    if path is None:
        label = _GUIDE_NAME
    elif path.name.upper() == "DESIGN.MD":
        label = f"project DESIGN.md ({path})"
    else:
        label = path.name
    return f"Google DESIGN.md guide ({label}):\n{body}".strip()


def resolve_alias(path: str, *, cwd: Path | None = None) -> str | None:
    raw = path.strip().strip("'\"")
    normalized = raw.lower().replace("\\", "/").lstrip("./")
    if normalized in _ALIASES or normalized.endswith("google-design.md"):
        resolved = project_design_path(cwd=cwd)
        if resolved is not None:
            return str(resolved)
        bundled = bundled_guide_path()
        return str(bundled) if bundled is not None else None
    if normalized in {"design.md", "design"}:
        resolved = project_design_path(cwd=cwd)
        if resolved is not None:
            return str(resolved)
        bundled = bundled_guide_path()
        return str(bundled) if bundled is not None else None
    return None


def status() -> dict[str, object]:
    path = guide_path()
    bundled = bundled_guide_path()
    project = project_design_path()
    return {
        "enabled": _enabled(),
        "mode": _mode(),
        "path": str(path) if path else None,
        "project_design_path": str(project) if project else None,
        "bundled_path": str(bundled) if bundled else None,
        "bytes": path.stat().st_size if path and path.is_file() else 0,
    }
