"""Format git working-tree changes for terminal output."""
from __future__ import annotations

import subprocess
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class ChangedFile:
    path: str
    status: str


_STATUS_ORDER = {"D": 0, "M": 1, "R": 2, "A": 3, "?": 4}


def _status_code(index: str, worktree: str) -> str:
    if index == "?" and worktree == "?":
        return "A"
    if index == "!" or worktree == "!":
        return "!"
    if "D" in (index, worktree):
        return "D"
    if "A" in (index, worktree):
        return "A"
    if "R" in (index, worktree):
        return "R"
    if "M" in (index, worktree):
        return "M"
    if "C" in (index, worktree):
        return "C"
    return "M"


def list_changed_files(root: Path) -> list[ChangedFile]:
    """Return changed paths relative to *root* with compact git status codes."""
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), "status", "--porcelain"],
            capture_output=True,
            text=True,
            timeout=5,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return []
    if proc.returncode != 0:
        return []

    files: list[ChangedFile] = []
    for line in proc.stdout.splitlines():
        if len(line) < 4:
            continue
        xy = line[:2]
        path = line[3:].strip()
        if " -> " in path:
            path = path.split(" -> ", 1)[1].strip()
        if not path:
            continue
        files.append(ChangedFile(path=path, status=_status_code(xy[0], xy[1])))

    files.sort(key=lambda row: (_STATUS_ORDER.get(row.status, 9), row.path))
    return files


def _section_header(title: str, count: int | None = None) -> str:
    label = title.strip()
    if count is not None:
        label = f"{label} ({count})"
    return f"━━━ {label} ━━━"


def format_changed_files(
    root: Path,
    *,
    files: list[ChangedFile] | None = None,
    title: str = "Changed files",
    empty_message: str = "○ No changes.",
    include_stat: bool = False,
) -> str:
    """Render a boxed list of changed files with M/A/D/R status codes."""
    rows = files if files is not None else list_changed_files(root)
    if not rows:
        return empty_message

    lines = [_section_header(title, len(rows)), ""]
    lines.extend(f"  {row.status}  {row.path}" for row in rows)

    if include_stat:
        try:
            proc = subprocess.run(
                ["git", "-C", str(root), "diff", "--stat"],
                capture_output=True,
                text=True,
                timeout=5,
                check=False,
            )
        except (OSError, subprocess.SubprocessError):
            proc = None
        stat = (proc.stdout or "").strip() if proc and proc.returncode == 0 else ""
        if stat:
            lines.extend(["", stat])

    return "\n".join(lines)


def format_plan_files(
    entries: list[tuple[str, str]],
    *,
    title: str = "Files to touch",
) -> str:
    """Render numbered plan file entries with optional reasons."""
    cleaned = [(path.strip(), reason.strip()) for path, reason in entries if path.strip()]
    if not cleaned:
        return ""

    lines = [_section_header(title, len(cleaned)), ""]
    for index, (path, reason) in enumerate(cleaned, 1):
        suffix = f" — {reason}" if reason else ""
        lines.append(f"  {index}. {path}{suffix}")
    return "\n".join(lines)
