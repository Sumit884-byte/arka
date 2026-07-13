#!/usr/bin/env python3
"""Scoped coding workspace — init a project folder, then restrict writes to it."""

from __future__ import annotations

import json
import os
import re
import shlex
import sys
import time
from pathlib import Path

from arka.paths import config_dir

_CONFIG_NAME = "code-project.json"
_ENV_KEY = "ARKA_CODE_PROJECT"
def not_init_message(*, cwd: Path | None = None) -> str:
    """Hint when agent_code / code write run without an initialized project."""
    here = (cwd or Path.cwd()).resolve()
    return f"No code project initialized. Run: arka code init .  (cwd: {here})"

CODE_WRITE_SKILLS = frozenset({"agent_code", "write_script", "goal", "code", "self_improve"})


class CodeProjectError(Exception):
    """Raised when code project scope is violated."""


def project_file() -> Path:
    return config_dir() / _CONFIG_NAME


def _load_data() -> dict:
    path = project_file()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_data(data: dict) -> None:
    config_dir().mkdir(parents=True, exist_ok=True)
    project_file().write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _normalize_root(path: str | Path) -> Path:
    candidate = Path(path).expanduser()
    if not candidate.is_absolute():
        candidate = Path.cwd() / candidate
    resolved = candidate.resolve()
    if not resolved.is_dir():
        raise CodeProjectError(f"Not a directory: {resolved}")
    return resolved


def get_active_root() -> Path | None:
    """Active project root from env override or persisted config."""
    if raw := os.environ.get(_ENV_KEY, "").strip():
        try:
            return _normalize_root(raw)
        except CodeProjectError:
            return None
    data = _load_data()
    root = (data.get("root") or "").strip()
    if not root:
        return None
    try:
        return _normalize_root(root)
    except CodeProjectError:
        return None


def apply_env() -> Path | None:
    """Export ARKA_CODE_PROJECT for child processes (fish goal, write_script)."""
    root = get_active_root()
    if root is not None:
        os.environ[_ENV_KEY] = str(root)
    else:
        os.environ.pop(_ENV_KEY, None)
    return root


def is_scoped() -> bool:
    return get_active_root() is not None


def init_project(path: str | Path = ".") -> Path:
    root = _normalize_root(path)
    _save_data(
        {
            "root": str(root),
            "name": root.name,
            "initialized_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
    )
    os.environ[_ENV_KEY] = str(root)
    return root


def clear_project() -> None:
    path = project_file()
    if path.is_file():
        path.unlink()
    os.environ.pop(_ENV_KEY, None)


def resolve_in_project(path: str | Path, *, root: Path | None = None) -> Path:
    """Resolve path and ensure it stays inside the project root (symlinks followed)."""
    project = root or get_active_root()
    if project is None:
        raise CodeProjectError(not_init_message())
    project = project.resolve()
    raw = Path(path).expanduser()
    target = (project / raw).resolve() if not raw.is_absolute() else raw.resolve()
    try:
        target.relative_to(project)
    except ValueError as exc:
        raise CodeProjectError(f"Path outside code project: {path}") from exc
    return target


def is_within_project(path: str | Path, *, root: Path | None = None) -> bool:
    try:
        resolve_in_project(path, root=root)
        return True
    except CodeProjectError:
        return False


def require_initialized() -> Path:
    root = get_active_root()
    if root is None:
        raise CodeProjectError(not_init_message())
    return root


def gate_code_write(skill_line: str) -> tuple[bool, str]:
    """Return (allowed, error_message) for code-writing skills."""
    parts = (skill_line or "").strip().split()
    head = parts[0] if parts else ""
    if head not in CODE_WRITE_SKILLS:
        return True, ""
    if head == "code" and len(parts) > 1 and parts[1] in (
        "init",
        "status",
        "clear",
        "help",
        "validate-write",
        "in",
    ):
        return True, ""
    if head == "goal" and not is_scoped():
        return True, ""
    if get_active_root() is None:
        return False, not_init_message()
    return True, ""


def gate_write_script_args(args: list[str]) -> tuple[bool, str]:
    if not args:
        return True, ""
    root = require_initialized()
    filename = args[0]
    try:
        resolve_in_project(filename, root=root)
    except CodeProjectError as exc:
        return False, str(exc)
    return True, ""


_REDIRECT_RE = re.compile(r"(?:^|[\s;|&])(?:>>?)\s*([^\s;&|]+)")
_WRITE_CMD_RE = re.compile(
    r"(?i)\b(?:cp|mv|touch|tee|install|sed\s+-i)\s+"
)


def check_shell_scope(cmd: str, *, root: Path | None = None) -> tuple[bool, str]:
    """Best-effort block for shell commands that write outside the project."""
    project = root or get_active_root()
    if project is None:
        return True, ""
    project = project.resolve()

    for match in _REDIRECT_RE.finditer(cmd):
        target = match.group(1).strip("'\"")
        if target in ("/dev/null", "2>&1", "&2"):
            continue
        if not is_within_project(target, root=project):
            return False, f"Blocked write outside project: {target}"

    if _WRITE_CMD_RE.search(cmd):
        try:
            tokens = shlex.split(cmd)
        except ValueError:
            tokens = cmd.split()
        for token in tokens[1:]:
            if token.startswith("-"):
                continue
            if "/" in token or token.endswith((".py", ".js", ".ts", ".go", ".rs", ".md", ".txt")):
                if not is_within_project(token, root=project):
                    return False, f"Blocked file operation outside project: {token}"
    return True, ""


def status_dict() -> dict[str, object]:
    root = get_active_root()
    data = _load_data()
    return {
        "initialized": root is not None,
        "root": str(root) if root else None,
        "name": data.get("name"),
        "initialized_at": data.get("initialized_at"),
        "config": str(project_file()),
    }


def route_code_nl(cmd: str) -> str | None:
    """Symbolic NL → 'code <subcommand> …'."""
    clean = cmd.strip()
    lower = clean.lower()
    if not clean:
        return None

    if lower in ("code", "code project", "code status", "show code project", "coding project status"):
        return "code status"

    m = re.match(
        r"(?i)^(?:initialize|init(?:ialize)?)\s+(?:the\s+)?(?:code\s+)?project\s+"
        r"(?:for\s+coding\s+)?(?:in\s+)?(?P<path>.+)$",
        clean,
    )
    if m:
        return f"code init {m.group('path').strip()}"

    m = re.match(r"(?i)^(?:arka\s+)?code\s+init\s+(?P<path>.+)$", clean)
    if m:
        return f"code init {m.group('path').strip()}"

    m = re.match(r"(?i)^(?:write\s+code|code\s+write)\s+(?P<goal>.+)$", clean)
    if m:
        return f"code write {m.group('goal').strip()}"

    m = re.match(r"(?i)^code\s+in\s+(?P<path>[^\s]+)\s+(?P<goal>.+)$", clean)
    if m:
        return f"code in {m.group('path').strip()} {m.group('goal').strip()}"

    m = re.match(r"(?i)^(?:code|implement|build)\s+(?:in\s+)?(?P<goal>.+)$", clean)
    if m and is_scoped():
        return f"code write {m.group('goal').strip()}"

    return None


def cmd_status() -> int:
    info = status_dict()
    if not info["initialized"]:
        print("Code project: not initialized")
        print(not_init_message())
        print(f"Config: {info['config']}")
        return 1
    print(f"Code project: {info['name']}")
    print(f"  Root: {info['root']}")
    if info.get("initialized_at"):
        print(f"  Since: {info['initialized_at']}")
    print(f"  Config: {info['config']}")
    return 0


def cmd_init(path: str) -> int:
    try:
        root = init_project(path)
    except CodeProjectError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(f"Code project initialized: {root}")
    print("  Write code with: arka code write \"<goal>\"")
    return 0


def cmd_clear() -> int:
    clear_project()
    print("Code project cleared.")
    return 0


def cmd_write(goal: str) -> int:
    goal = goal.strip()
    if not goal:
        print("Usage: arka code write <goal>", file=sys.stderr)
        return 1
    try:
        root = require_initialized()
    except CodeProjectError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    apply_env()
    from arka.core.mode import get_mode

    if get_mode() not in ("agent", "debug", "multitask"):
        print(
            f"Code writes require agent mode (current: {get_mode()}). "
            "Run: arka mode agent",
            file=sys.stderr,
        )
        return 1
    from arka.agent.core import code_agent

    return code_agent(goal, repo=str(root))


def main(argv: list[str] | None = None) -> int:
    args = list(argv or sys.argv[1:])
    if args and args[0] == "code":
        args = args[1:]

    if not args or args[0] in ("-h", "--help", "help"):
        print(
            "Usage: arka code [init|status|write|clear] …\n"
            "\n"
            "Scoped coding workspace — all writes stay inside the initialized folder.\n"
            "\n"
            "  arka code init <folder>     Initialize project (use . for cwd)\n"
            "  arka code status            Show active project folder\n"
            "  arka code write <goal>      Run repo-scoped coding agent\n"
            "  arka code clear             Clear active project\n"
            "\n"
            "Examples:\n"
            "  arka code init ~/dev/myapp\n"
            "  arka code write \"add login endpoint\"\n"
            "  arka initialize project for coding in ~/dev/myapp"
        )
        return 0

    sub = args[0].lower()
    if sub == "init":
        path = args[1] if len(args) > 1 else "."
        return cmd_init(path)
    if sub == "status":
        return cmd_status()
    if sub == "clear":
        return cmd_clear()
    if sub == "write":
        return cmd_write(" ".join(args[1:]))
    if sub == "validate-write":
        if len(args) < 2:
            print("Usage: arka code validate-write <filename>", file=sys.stderr)
            return 1
        ok, msg = gate_write_script_args([args[1]])
        if not ok:
            print(msg, file=sys.stderr)
            return 1
        return 0
    if sub == "in" and len(args) >= 3:
        path = args[1]
        goal = " ".join(args[2:])
        try:
            target = _normalize_root(path)
        except CodeProjectError as exc:
            print(str(exc), file=sys.stderr)
            return 1
        active = get_active_root()
        if active is None or active != target:
            init_project(path)
            print(f"Code project initialized: {target}")
        return cmd_write(goal)
    print(f"Unknown subcommand: {sub}", file=sys.stderr)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
