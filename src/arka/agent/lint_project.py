#!/usr/bin/env python3
"""Language-agnostic project linter — detect and run available lint tools."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

from arka.agent.repo_health import Check, detect_checks, _project_root as repo_project_root, _run


_TRIGGER_RE = re.compile(
    r"(?i)\b("
    r"lint\s+(?:this\s+)?(?:repo|project|codebase|workspace|folder|dir)|"
    r"run\s+(?:project\s+)?lint|"
    r"check\s+(?:project\s+)?lint|"
    r"lint\s+any\s+language|"
    r"lint\s+all\s+languages"
    r")\b"
)


def wants_lint_project(text: str) -> bool:
    return bool(_TRIGGER_RE.search(text or ""))


def route_command(text: str) -> str:
    if not wants_lint_project(text):
        return ""
    clean = (text or "").strip()
    if re.search(r"(?i)\bfix\b", clean):
        return "lint_project --fix"
    if re.search(r"(?i)\b(full|all)\b", clean):
        return "lint_project --full"
    return "lint_project"


def _project_root(explicit: str | None = None) -> Path:
    return repo_project_root(explicit)


def _filter_checks(checks: list[Check], *, full: bool = False) -> list[Check]:
    if full:
        return checks
    preferred = []
    for chk in checks:
        if chk.category == "lint":
            preferred.append(chk)
    return preferred or checks


def run_lint(root: Path, *, full: bool = False) -> dict:
    checks = _filter_checks(detect_checks(root), full=full)
    results: list[dict] = []
    passed = failed = skipped = 0
    for chk in checks:
        code, out, err = _run(chk.command, cwd=root, timeout=600)
        combined = (out + err).strip()
        preview = "\n".join(combined.splitlines()[:8])
        if code == 0:
            status = "passed"
            passed += 1
        elif code == 127 or "not found" in err.lower():
            status = "skipped"
            skipped += 1
        else:
            status = "failed"
            failed += 1
        results.append(
            {
                "name": chk.name,
                "category": chk.category,
                "command": list(chk.command),
                "status": status,
                "exit_code": code,
                "preview": preview,
            }
        )
        if failed and not full:
            break
    return {
        "path": str(root),
        "name": root.name,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "results": results,
        "ok": failed == 0,
    }


def lint_text(root: Path, *, full: bool = False) -> str:
    payload = run_lint(root, full=full)
    lines = [f"Lint run: {payload['name']}", ""]
    if not payload["results"]:
        lines.append("No lint checks detected.")
        return "\n".join(lines).strip()
    for row in payload["results"]:
        mark = "✓" if row["status"] == "passed" else "⊘" if row["status"] == "skipped" else "✗"
        lines.append(f"{mark} {row['name']}: {' '.join(row['command'])}")
        if row.get("preview"):
            for pline in str(row["preview"]).splitlines():
                lines.append(f"  {pline[:180]}")
        lines.append("")
    lines.append(f"Summary: {payload['passed']} passed, {payload['failed']} failed, {payload['skipped']} skipped")
    return "\n".join(lines).strip()


def cmd_run(args: argparse.Namespace) -> int:
    root = _project_root(args.path)
    payload = run_lint(root, full=args.full)
    print(lint_text(root, full=args.full))
    if payload["failed"] and args.fix:
        print("Fix mode is symbolic-only here; re-run after correcting the issues.", file=sys.stderr)
    return 0 if payload["ok"] else 1


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Language-agnostic project lint runner")
    sub = parser.add_subparsers(dest="cmd")

    p_run = sub.add_parser("run", help="Run detected lint checks")
    p_run.add_argument("path", nargs="?", default=None)
    p_run.add_argument("--full", action="store_true", help="Run all detected checks, not just lint")
    p_run.add_argument("--fix", action="store_true", help="Reserved: request symbolic repair suggestions")
    p_run.set_defaults(func=cmd_run)

    p_route = sub.add_parser("route", help="Map NL to lint_project")
    p_route.add_argument("text", nargs="+")

    args = parser.parse_args(argv)
    if args.cmd == "route":
        line = route_command(" ".join(args.text))
        if line:
            print(line)
            return 0
        return 1
    if hasattr(args, "func"):
        return int(args.func(args))
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
