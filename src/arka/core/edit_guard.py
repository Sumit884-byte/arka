#!/usr/bin/env python3
"""Guardrails for file edits — block sensitive or protected paths before writes."""

from __future__ import annotations

import fnmatch
import os
import re
from dataclasses import dataclass
from pathlib import Path

try:
    from arka.paths import config_dir, load_env_file

    load_env_file()
except ImportError:

    def load_env_file() -> None:
        pass

    def config_dir() -> Path:
        return Path.home() / ".config" / "arka"


@dataclass(frozen=True)
class EditGuardResult:
    allowed: bool
    reason: str = ""
    pattern: str = ""
    path: str = ""


_DEFAULT_BLOCKED_RES: tuple[tuple[re.Pattern[str], str], ...] = (
    (re.compile(r"(?i)(?:^|/)\.env$"), "secret env file (.env)"),
    (re.compile(r"(?i)(?:^|/)\.env\.(?!example(?:\.|$))[^/]+$"), "secret env file (.env.*)"),
    (re.compile(r"(?i)(?:^|/)secrets(?:/|$)"), "secrets/ directory"),
    (re.compile(r"(?i)(?:^|/)node_modules(?:/|$)"), "node_modules/"),
    (re.compile(r"(?i)(?:^|/)\.git(?:/|$)"), ".git/ metadata"),
    (re.compile(r"(?i)(?:^|/)bundled/"), "bundled/ (use scripts/sync_bundled.py)"),
    (re.compile(r"(?i)(?:^|/)(?:id_rsa|id_ed25519|known_hosts)$"), "SSH private material"),
    (re.compile(r"(?i)\.(?:pem|p12|pfx|key)$"), "private key material"),
    (re.compile(r"(?i)(?:^|/)credentials(?:\.|/|$)"), "credentials file or directory"),
    (re.compile(r"(?i)(?:^|/)?\.?aws/credentials$"), "AWS credentials"),
)


def _enabled() -> bool:
    return os.environ.get("EDIT_GUARD", "1").strip().lower() not in ("0", "false", "no", "off")


def _mode() -> str:
    raw = os.environ.get("EDIT_GUARD_MODE", "enforce").strip().lower()
    if raw in {"off", "disabled", "0"}:
        return "off"
    if raw in {"warn", "warning"}:
        return "warn"
    return "enforce"


def _csv_patterns(name: str) -> list[str]:
    raw = os.environ.get(name, "").strip()
    if not raw:
        return []
    return [part.strip() for part in raw.split(",") if part.strip()]


def _file_patterns(path: Path) -> list[str]:
    if not path.is_file():
        return []
    lines: list[str] = []
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        clean = line.strip()
        if not clean or clean.startswith("#"):
            continue
        lines.append(clean)
    return lines


def blocked_pattern_sources(*, root: Path | None = None) -> dict[str, list[str]]:
    project = root.resolve() if root else None
    project_file = project / ".arka" / "blocked-edit-paths" if project else None
    return {
        "env_blocked": _csv_patterns("BLOCKED_EDIT_PATHS"),
        "env_allowed": _csv_patterns("ALLOWED_EDIT_PATHS"),
        "user_file": _file_patterns(config_dir() / "blocked-edit-paths.txt"),
        "project_file": _file_patterns(project_file) if project_file and project_file.is_file() else [],
        "defaults": [label for _, label in _DEFAULT_BLOCKED_RES],
    }


def _collect_glob_patterns(*, root: Path | None = None) -> tuple[list[str], list[str]]:
    blocked = [
        *_csv_patterns("BLOCKED_EDIT_PATHS"),
        *_file_patterns(config_dir() / "blocked-edit-paths.txt"),
    ]
    if root is not None:
        project_file = root.resolve() / ".arka" / "blocked-edit-paths"
        blocked.extend(_file_patterns(project_file))
    allowed = _csv_patterns("ALLOWED_EDIT_PATHS")
    return blocked, allowed


def rel_path_str(path: Path | str, root: Path | None = None) -> str:
    target = Path(path).expanduser()
    try:
        resolved = target.resolve()
    except OSError:
        resolved = target
    if root is not None:
        try:
            return resolved.relative_to(root.resolve()).as_posix()
        except ValueError:
            pass
    return resolved.as_posix()


def _glob_match(rel: str, pattern: str) -> bool:
    rel_norm = rel.replace("\\", "/").lstrip("./")
    pat = pattern.replace("\\", "/").lstrip("./")
    if not pat:
        return False
    candidates = (rel_norm, f"./{rel_norm}", f"/{rel_norm}")
    for candidate in candidates:
        if fnmatch.fnmatchcase(candidate, pat):
            return True
        if fnmatch.fnmatchcase(candidate, f"**/{pat}"):
            return True
    return fnmatch.fnmatchcase(rel_norm, pat)


def check_edit_path(path: Path | str, *, root: Path | None = None) -> EditGuardResult:
    rel = rel_path_str(path, root)
    if not _enabled() or _mode() == "off":
        return EditGuardResult(True, path=rel)

    blocked_globs, allowed_globs = _collect_glob_patterns(root=root)
    for pattern in allowed_globs:
        if _glob_match(rel, pattern):
            return EditGuardResult(True, path=rel, reason="allowed by ALLOWED_EDIT_PATHS")

    for regex, label in _DEFAULT_BLOCKED_RES:
        if regex.search(rel):
            return EditGuardResult(False, reason=f"edit blocked: {label}", pattern=label, path=rel)

    for pattern in blocked_globs:
        if _glob_match(rel, pattern):
            return EditGuardResult(
                False,
                reason=f"edit blocked: matches protected pattern {pattern!r}",
                pattern=pattern,
                path=rel,
            )

    return EditGuardResult(True, path=rel)


def assert_edit_allowed(path: Path | str, *, root: Path | None = None) -> None:
    result = check_edit_path(path, root=root)
    if result.allowed:
        return
    if _mode() == "warn":
        return
    raise EditGuardError(result.reason or f"edit blocked: {result.path}")


class EditGuardError(PermissionError):
    """Raised when a file edit is blocked by guardrails."""


def check_edit_paths(paths: list[str], *, root: Path | None = None) -> EditGuardResult:
    for raw in paths:
        rel = raw.strip()
        if not rel or rel == "/dev/null":
            continue
        result = check_edit_path(rel, root=root)
        if not result.allowed:
            return result
    return EditGuardResult(True)


def files_in_unified_diff(diff: str) -> list[str]:
    files: list[str] = []
    for line in diff.splitlines():
        if line.startswith("+++ b/"):
            rel = line[6:].split("\t", 1)[0].strip()
            if rel and rel != "/dev/null" and rel not in files:
                files.append(rel)
        elif line.startswith("--- a/"):
            rel = line[6:].split("\t", 1)[0].strip()
            if rel and rel != "/dev/null" and rel not in files:
                files.append(rel)
    return files


def guard_payload(
    *,
    action: str = "check",
    path: str = "",
    root: Path | str | None = None,
    diff: str = "",
) -> dict[str, object]:
    project = Path(root).expanduser().resolve() if root else None
    act = (action or "check").strip().lower()

    if act == "status":
        return {
            "ok": True,
            "enabled": _enabled(),
            "mode": _mode(),
            "patterns": blocked_pattern_sources(root=project),
            "hint": "Set BLOCKED_EDIT_PATHS or ~/.config/arka/blocked-edit-paths.txt",
        }

    if act == "list":
        return {"ok": True, "patterns": blocked_pattern_sources(root=project)}

    if act == "check":
        if diff.strip():
            files = files_in_unified_diff(diff)
            result = check_edit_paths(files, root=project)
            return {
                "ok": result.allowed,
                "allowed": result.allowed,
                "blocked": not result.allowed,
                "files": files,
                "path": result.path,
                "reason": result.reason,
                "pattern": result.pattern,
            }
        if not path.strip():
            raise ValueError("path or diff is required when action=check")
        result = check_edit_path(path, root=project)
        return {
            "ok": result.allowed,
            "allowed": result.allowed,
            "blocked": not result.allowed,
            "path": result.path,
            "reason": result.reason,
            "pattern": result.pattern,
        }

    raise ValueError("action must be check, list, or status")


def nl_to_argv(cmd: str) -> list[str] | None:
    clean = (cmd or "").strip()
    if not clean:
        return None
    lower = clean.lower()
    if lower in {"edit guard", "edit guard status", "edit guard list", "edit guard check"}:
        if lower.endswith("list"):
            return ["list"]
        if lower.endswith("check"):
            return ["status"]
        return ["status"]
    if re.search(r"(?i)\b(?:edit|file|patch)\s+guard\b|\bedit_guard\b|\bblocked\s+edit\s+paths?\b", clean):
        if re.search(r"(?i)\b(?:list|show)\b.*\b(?:blocked|protected|patterns?)\b", clean):
            return ["list"]
        if re.search(r"(?i)\b(?:status|state|config)\b", clean):
            return ["status"]
        m = re.search(r"(?i)\b(?:check|can\s+i\s+edit)\b.*\b([~/][^\s]+|\S+\.(?:py|md|json|yaml|env))\b", clean)
        if m:
            return ["check", m.group(1)]
        return ["status"]
    return None


def route_command(text: str) -> str:
    argv = nl_to_argv(text)
    if not argv:
        return ""
    return "edit_guard " + " ".join(argv)


def main(argv: list[str] | None = None) -> int:
    import argparse
    import json

    parser = argparse.ArgumentParser(prog="arka edit_guard", description="Edit guard status and path checks")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("status").set_defaults(action="status")
    sub.add_parser("list").set_defaults(action="list")
    check_p = sub.add_parser("check", help="Check whether a path may be edited")
    check_p.add_argument("path")
    check_p.set_defaults(action="check")
    args = parser.parse_args(argv)
    if not getattr(args, "action", None):
        parser.print_help()
        return 1
    if args.action == "check":
        payload = guard_payload("check", path=args.path)
    else:
        payload = guard_payload(args.action)
    print(json.dumps(payload, indent=2))
    return 0 if payload.get("ok", True) else 1


if __name__ == "__main__":
    raise SystemExit(main())
