"""Apply unified diffs or search-replace patches inside the code project scope."""
from __future__ import annotations

import re
import subprocess
from pathlib import Path
from typing import Any


class PatchError(ValueError):
    """Raised when a patch cannot be applied safely."""


def _project_root(path: str | Path | None = None) -> Path:
    if path:
        return Path(path).expanduser().resolve()
    try:
        from arka.core.code_project import get_active_root

        active = get_active_root()
        if active is not None:
            return active.resolve()
    except ImportError:
        pass
    try:
        from arka.agent.pr_check import git_root

        root = git_root()
        if root is not None:
            return root.resolve()
    except ImportError:
        pass
    return Path.cwd().resolve()


def _assert_in_scope(target: Path, root: Path) -> None:
    resolved = target.resolve()
    root_resolved = root.resolve()
    if resolved == root_resolved:
        return
    try:
        resolved.relative_to(root_resolved)
    except ValueError as exc:
        raise PatchError(f"path outside code project scope: {target}") from exc


def _apply_search_replace(root: Path, *, file: str, old: str, new: str) -> dict[str, Any]:
    target = (root / file).resolve()
    _assert_in_scope(target, root)
    if not target.is_file():
        raise PatchError(f"file not found: {file}")
    text = target.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise PatchError(f"expected exactly one match for search-replace in {file}, found {count}")
    target.write_text(text.replace(old, new, 1), encoding="utf-8")
    return {"mode": "search_replace", "file": file, "replacements": 1}


def _apply_unified_diff(root: Path, diff: str) -> dict[str, Any]:
    import tempfile

    with tempfile.NamedTemporaryFile("w", suffix=".patch", delete=False, encoding="utf-8") as handle:
        handle.write(diff if diff.endswith("\n") else diff + "\n")
        patch_path = Path(handle.name)
    try:
        check = subprocess.run(
            ["git", "apply", "--check", str(patch_path)],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if check.returncode != 0:
            raise PatchError((check.stderr or check.stdout or "git apply --check failed").strip())
        apply = subprocess.run(
            ["git", "apply", str(patch_path)],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
            check=False,
        )
        if apply.returncode != 0:
            raise PatchError((apply.stderr or apply.stdout or "git apply failed").strip())
    finally:
        patch_path.unlink(missing_ok=True)
    touched = re.findall(r"^\+\+\+ b/(.+)$", diff, flags=re.MULTILINE)
    for rel in touched:
        _assert_in_scope((root / rel).resolve(), root)
    return {"mode": "unified_diff", "files": touched}


def apply_patch_payload(
    *,
    root: Path | str | None = None,
    diff: str = "",
    file: str = "",
    search: str = "",
    replace: str = "",
) -> dict[str, Any]:
    project = _project_root(root)
    if diff.strip():
        result = _apply_unified_diff(project, diff.strip())
    elif file and search:
        result = _apply_search_replace(project, file=file, old=search, new=replace)
    else:
        raise ValueError("provide diff or file+search (+ optional replace)")
    return {
        "ok": True,
        "path": str(project),
        **result,
        "verify_hint": "Run tests or `arka dev test --changed` to verify the patch.",
    }
