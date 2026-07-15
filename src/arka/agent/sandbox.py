"""Safe, disposable project workspaces for Arka.

This is a directory/process sandbox, not a VM.  It is intended for generated
code and experiments; hostile code should run in Docker or a dedicated VM.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
from datetime import datetime, timezone
from pathlib import Path

from arka.core.security import check_action
from arka.paths import cache_dir

_NAME = re.compile(r"^[a-z][a-z0-9_-]{0,63}$")
_SKIP = shutil.ignore_patterns(".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache")


def root() -> Path:
    value = os.environ.get("ARKA_SANDBOX_DIR", "").strip()
    return Path(value).expanduser().resolve() if value else cache_dir() / "sandboxes"


def _path(name: str) -> Path:
    if not _NAME.fullmatch(name):
        raise ValueError("sandbox name must start with a letter and contain only a-z, 0-9, _ or -")
    return root() / name


def create(name: str, source: str | None = None) -> dict:
    target = _path(name)
    if target.exists():
        raise ValueError(f"sandbox already exists: {name}")
    target.parent.mkdir(parents=True, exist_ok=True)
    if source:
        src = Path(source).expanduser().resolve()
        if not src.is_dir() or src == target or target.is_relative_to(src):
            raise ValueError("--from must be an existing directory outside the sandbox")
        shutil.copytree(src, target, ignore=_SKIP)
    else:
        target.mkdir()
    meta = {"name": name, "created_at": datetime.now(timezone.utc).isoformat(), "isolation": "directory/process", "source": source}
    (target / ".arka-sandbox.json").write_text(json.dumps(meta, indent=2) + "\n", encoding="utf-8")
    return meta


def list_sandboxes() -> list[dict]:
    base = root()
    if not base.is_dir():
        return []
    result = []
    for item in sorted(base.iterdir()):
        if item.is_dir() and _NAME.fullmatch(item.name):
            try:
                result.append(json.loads((item / ".arka-sandbox.json").read_text(encoding="utf-8")))
            except (OSError, json.JSONDecodeError):
                result.append({"name": item.name, "isolation": "directory/process"})
    return result


def run(name: str, command: list[str], timeout: float = 60) -> int:
    if not command:
        raise ValueError("a command is required")
    if not 1 <= timeout <= 900:
        raise ValueError("timeout must be between 1 and 900 seconds")
    target = _path(name)
    if not target.is_dir():
        raise ValueError(f"sandbox does not exist: {name}")
    text = " ".join(shlex.quote(part) for part in command)
    decision = check_action(text)
    if decision.status == "block":
        raise ValueError(decision.reason)
    env = os.environ.copy()
    env["ARKA_SANDBOX"] = "1"
    env["HOME"] = str(target)
    try:
        completed = subprocess.run(command, cwd=target, env=env, text=True, capture_output=True, timeout=timeout, check=False)
    except subprocess.TimeoutExpired:
        print(f"sandbox command timed out after {timeout:g}s")
        return 124
    if completed.stdout:
        print(completed.stdout, end="")
    if completed.stderr:
        print(completed.stderr, end="", file=__import__("sys").stderr)
    return completed.returncode


def destroy(name: str, confirmed: bool = False) -> None:
    if not confirmed:
        raise ValueError("refusing to destroy sandbox without --yes")
    target = _path(name)
    if target.exists():
        shutil.rmtree(target)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka sandbox", description="Create and run disposable project sandboxes")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("create")
    p.add_argument("name")
    p.add_argument("--from", dest="source")
    sub.add_parser("list")
    p = sub.add_parser("status")
    p.add_argument("name", nargs="?")
    p = sub.add_parser("run")
    p.add_argument("name")
    p.add_argument("--timeout", type=float, default=60)
    p.add_argument("command", nargs=argparse.REMAINDER)
    p = sub.add_parser("destroy")
    p.add_argument("name")
    p.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "create":
            print(json.dumps(create(args.name, args.source), indent=2))
        elif args.action == "list":
            print(json.dumps(list_sandboxes(), indent=2))
        elif args.action == "status":
            items = list_sandboxes()
            print(json.dumps(next((x for x in items if x["name"] == args.name), None) if args.name else items, indent=2))
        elif args.action == "run":
            return run(args.name, args.command, args.timeout)
        elif args.action == "destroy":
            destroy(args.name, args.yes)
            print(f"destroyed {args.name}")
    except (OSError, ValueError) as exc:
        print(f"sandbox: {exc}", file=__import__("sys").stderr)
        return 2
    return 0
