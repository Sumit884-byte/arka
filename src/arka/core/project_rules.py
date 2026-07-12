#!/usr/bin/env python3
"""Cursor-style project instruction files — AGENTS.md, .cursor/rules, CLAUDE.md."""

from __future__ import annotations

import os
import re
from pathlib import Path

_RULE_NAMES = (
    "AGENTS.md",
    "CLAUDE.md",
    ".cursorrules",
    "AGENT.md",
)


def _enabled() -> bool:
    return os.environ.get("PROJECT_RULES", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def find_project_root(start: Path | None = None) -> Path | None:
    """Walk up from start (or cwd) for .git, AGENTS.md, or .cursor/rules."""
    if raw := os.environ.get("PROJECT_RULES_ROOT", "").strip():
        path = Path(raw).expanduser().resolve()
        return path if path.is_dir() else None
    cur = (start or Path.cwd()).resolve()
    for candidate in [cur, *cur.parents]:
        if (candidate / ".git").exists():
            return candidate
        if (candidate / "AGENTS.md").is_file():
            return candidate
        if (candidate / ".cursor" / "rules").is_dir():
            return candidate
        if (candidate / "CLAUDE.md").is_file():
            return candidate
    return None


def _read_text(path: Path, *, max_chars: int = 8000) -> str:
    try:
        text = path.read_text(encoding="utf-8", errors="replace")
    except OSError:
        return ""
    text = text.strip()
    if not text:
        return ""
    try:
        from arka.core.security import sanitize_llm_context

        cleaned, _ = sanitize_llm_context(text)
        text = (cleaned or text).strip()
    except ImportError:
        pass
    if len(text) > max_chars:
        text = text[:max_chars].rstrip() + "\n…"
    return text


def collect_rule_files(root: Path) -> list[tuple[str, Path]]:
    """Return (label, path) pairs in stable priority order."""
    rows: list[tuple[str, Path]] = []
    seen: set[Path] = set()
    for name in _RULE_NAMES:
        path = root / name
        if path.is_file() and path not in seen:
            rows.append((name, path))
            seen.add(path)
    rules_dir = root / ".cursor" / "rules"
    if rules_dir.is_dir():
        for path in sorted(rules_dir.rglob("*")):
            if not path.is_file():
                continue
            if path.suffix.lower() not in {".md", ".mdc", ".txt"}:
                continue
            if path in seen:
                continue
            rel = path.relative_to(root).as_posix()
            rows.append((rel, path))
            seen.add(path)
    return rows


def list_rules(*, root: Path | None = None) -> list[dict[str, object]]:
    project = root or find_project_root()
    if project is None:
        return []
    out: list[dict[str, object]] = []
    for label, path in collect_rule_files(project):
        try:
            size = path.stat().st_size
        except OSError:
            size = 0
        out.append({"label": label, "path": str(path), "bytes": size})
    return out


def context_for(
    goal: str = "",
    *,
    root: Path | None = None,
    limit_chars: int = 4000,
) -> str:
    """Build a truncated project-rules context block for agent prompts."""
    if not _enabled():
        return ""
    project = root or find_project_root()
    if project is None:
        return ""
    files = collect_rule_files(project)
    if not files:
        return ""

    tokens = [w.lower() for w in re.findall(r"[a-zA-Z0-9_-]{3,}", goal or "")]
    ranked = files
    if tokens:
        scored: list[tuple[int, str, Path]] = []
        for label, path in files:
            blob = f"{label} {_read_text(path, max_chars=2000)}".lower()
            score = sum(1 for t in tokens if t in blob)
            scored.append((score, label, path))
        scored.sort(key=lambda x: (-x[0], x[1]))
        ranked = [(label, path) for _, label, path in scored]

    lines = [f"Project rules ({project.name}):"]
    used = 0
    budget = max(200, limit_chars)
    for label, path in ranked:
        body = _read_text(path, max_chars=min(4000, budget - used))
        if not body:
            continue
        chunk = f"### {label}\n{body}"
        if used + len(chunk) > budget and used > 0:
            break
        lines.append(chunk)
        used += len(chunk)
        if used >= budget:
            break
    if len(lines) == 1:
        return ""
    out = "\n\n".join(lines).strip()
    if len(out) > budget:
        out = out[:budget].rstrip() + "\n…"
    return out


def status(*, root: Path | None = None) -> dict[str, object]:
    project = root or find_project_root()
    files = list_rules(root=project) if project else []
    return {
        "enabled": _enabled(),
        "root": str(project) if project else None,
        "files": len(files),
        "rules": files,
    }
