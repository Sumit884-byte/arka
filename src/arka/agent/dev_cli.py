#!/usr/bin/env python3
"""Unified developer loop — init, test, review, ship, TUI, PR checks."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path

from arka.agent.dev_tools import (
    _repo_root,
    ci_text,
    cmd_doctor,
    cmd_hooks,
    cmd_review,
    review_text,
    run_ci,
)
from arka.core.code_project import get_active_root, init_project, status_dict


def _warn_code_project(root: Path) -> None:
    active = get_active_root()
    if active is None or active.resolve() != root.resolve():
        print(
            f"Tip: run `arka dev init {root}` to scope agent writes to this repository.",
            file=sys.stderr,
        )


def run_ship(
    root: Path,
    *,
    no_review: bool = False,
    fail_on_hints: bool = False,
    fix: bool = False,
    json_output: bool = False,
) -> int:
    """Review staged changes + run changed-only CI gates."""
    _warn_code_project(root)

    review_ok = True
    hints: list[str] = []
    report = ""

    if not no_review:
        report = review_text(root, staged=True)
        hints = [
            line.strip()
            for line in report.splitlines()
            if any(marker in line.lower() for marker in ("security:", "test-gap:", "docs:"))
        ]
        review_ok = not (fail_on_hints and hints)
        if not json_output:
            print(report)
            print()

    ci_payload = run_ci(root, changed_only=True)
    ci_ok = ci_payload["ok"]

    if not ci_ok and fix:
        try:
            from arka.agent.goal import run_goal

            run_goal(
                "Fix the first failing developer-tools CI gate and re-run verification.",
                max_steps=8,
                auto_yes=True,
                auto_continue=True,
            )
            ci_payload = run_ci(root, changed_only=True)
            ci_ok = ci_payload["ok"]
        except Exception as exc:
            print(f"goal agent unavailable: {exc}", file=sys.stderr)
            if json_output:
                print(json.dumps({"ok": False, "error": str(exc)}, indent=2))
            return 1

    if json_output:
        print(
            json.dumps(
                {
                    "path": str(root),
                    "ok": review_ok and ci_ok,
                    "review_ok": review_ok,
                    "ci_ok": ci_ok,
                    "hints": hints,
                    "report": report,
                    "ci": [
                        {"name": row["name"], "ok": row["ok"], "exit_code": row["exit_code"]}
                        for row in ci_payload["results"]
                    ],
                },
                indent=2,
            )
        )
    else:
        print(ci_text(root, changed_only=True))
        print()
        if review_ok and ci_ok:
            print("Summary: ship checks passed")
            print("Next: git commit, then `arka dev pr babysit` if opening a PR")
        elif not review_ok:
            print("Summary: review hints blocked ship (use --no-review to skip review)")
        elif not ci_ok:
            print("Summary: CI gates failed")
            print("Next: `arka dev test --fix` or fix failures manually")

    if not (review_ok and ci_ok):
        return 1
    return 0


def cmd_init(args: argparse.Namespace) -> int:
    root = init_project(args.path or ".")
    print(f"Code project initialized: {root}")
    print("  Write code with: arka code write \"<goal>\"")
    print("  Daily loop: arka dev tui")
    print("  Optional: arka dev hooks install")
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    root = _repo_root(args.path)
    info = status_dict()
    if info.get("initialized"):
        print(f"Code project: {info['name']}")
        print(f"  Root: {info['root']}")
    else:
        print("Code project: not initialized")
        print(f"  Run: arka dev init {root}")
    print()
    doctor_args = argparse.Namespace(path=str(root), json=False)
    return cmd_doctor(doctor_args)


def cmd_test(args: argparse.Namespace) -> int:
    from arka.agent.dev_tools import cmd_ci

    ci_args = argparse.Namespace(
        path=args.path,
        full=args.full,
        changed=not args.full,
        fix=args.fix,
        json=args.json,
    )
    return cmd_ci(ci_args)


def cmd_review(args: argparse.Namespace) -> int:
    review_args = argparse.Namespace(
        path=args.path,
        base=args.base or "",
        staged=True,
        fail_on_hints=args.fail_on_hints,
        json=args.json,
    )
    return cmd_review(review_args)


def cmd_ship(args: argparse.Namespace) -> int:
    root = _repo_root(args.path)
    return run_ship(
        root,
        no_review=args.no_review,
        fail_on_hints=args.fail_on_hints,
        fix=args.fix,
        json_output=args.json,
    )


def cmd_gaps(args: argparse.Namespace) -> int:
    from arka.agent.dev_workflows import test_gaps, test_gaps_for_files
    from arka.agent.pr_check import _run

    root = _repo_root(args.path)
    if args.staged:
        _, names_out, _ = _run(["git", "diff", "--cached", "--name-only"], cwd=root)
        files = [ln.strip() for ln in names_out.splitlines() if ln.strip()]
        gaps = test_gaps_for_files(files)
    else:
        gaps = test_gaps(root)
    if args.json:
        print(json.dumps({"path": str(root), "gaps": gaps, "count": len(gaps)}, indent=2))
    else:
        print(f"Test gaps: {len(gaps)}")
        for item in gaps:
            print(f"  {item}")
    return 0


def cmd_pr(args: argparse.Namespace) -> int:
    from arka.agent.pr_check import main as pr_check_main

    return pr_check_main(args.pr_argv)


def cmd_tui(args: argparse.Namespace) -> int:
    from arka.agent.coding_tui import main as coding_tui_main

    return coding_tui_main([args.path or "."])


def route_command(text: str) -> str:
    """Natural-language routing for dev loop commands."""
    raw = (text or "").strip()
    low = raw.lower()
    if re.search(r"(?i)\b(?:dev\s+ship|prepare\s+to\s+commit|ship\s+checks|run\s+dev\s+checks)\b", low):
        return "dev ship"
    if re.search(r"(?i)\b(?:dev\s+test|run\s+dev\s+test)\b", low):
        return "dev test"
    if re.search(r"(?i)\b(?:dev\s+review|dev\s+code\s+review)\b", low):
        return "dev review"
    if re.search(r"(?i)\b(?:dev\s+init|init\s+dev\s+project|initialize\s+code\s+project)\b", low):
        m = re.search(r"(?i)\b(?:in|at|for)\s+([^\s]+)\s*$", raw)
        return f"dev init {m.group(1)}" if m else "dev init ."
    if re.search(r"(?i)\b(?:dev\s+tui|open\s+dev\s+tui|coding\s+tui)\b", low):
        return "dev tui"
    if re.search(r"(?i)\b(?:dev\s+doctor|check\s+dev\s+setup)\b", low):
        return "dev doctor"
    if re.search(r"(?i)\b(?:dev\s+gaps|test\s+gaps)\b", low):
        return "dev gaps"
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="arka dev",
        description="Developer loop — init, test, review, ship, TUI, PR checks",
    )
    sub = parser.add_subparsers(dest="cmd")

    p_init = sub.add_parser("init", help="Initialize scoped code project")
    p_init.add_argument("path", nargs="?", default=".")
    p_init.set_defaults(func=cmd_init)

    p_status = sub.add_parser("status", help="Code project + repo dev doctor summary")
    p_status.add_argument("path", nargs="?", default=None)
    p_status.set_defaults(func=cmd_status)

    p_test = sub.add_parser("test", help="Run changed-only CI gates (alias: ci --changed)")
    p_test.add_argument("--full", action="store_true", help="Run full CI suite")
    p_test.add_argument("--fix", action="store_true", help="Hand first failure to goal agent")
    p_test.add_argument("--json", action="store_true")
    p_test.add_argument("path", nargs="?", default=None)
    p_test.set_defaults(func=cmd_test)

    p_review = sub.add_parser("review", help="Review staged changes")
    p_review.add_argument("--fail-on-hints", action="store_true")
    p_review.add_argument("--json", action="store_true")
    p_review.add_argument("--base", default="")
    p_review.add_argument("path", nargs="?", default=None)
    p_review.set_defaults(func=cmd_review)

    p_ship = sub.add_parser("ship", help="Review staged changes + run changed CI")
    p_ship.add_argument("--no-review", action="store_true")
    p_ship.add_argument("--fail-on-hints", action="store_true")
    p_ship.add_argument("--fix", action="store_true")
    p_ship.add_argument("--json", action="store_true")
    p_ship.add_argument("path", nargs="?", default=None)
    p_ship.set_defaults(func=cmd_ship)

    p_doctor = sub.add_parser("doctor", help="Repo dev preflight (not platform arka doctor)")
    p_doctor.add_argument("--json", action="store_true")
    p_doctor.add_argument("path", nargs="?", default=None)
    p_doctor.set_defaults(func=cmd_doctor)

    p_hooks = sub.add_parser("hooks", help="Git pre-commit hooks")
    hooks_sub = p_hooks.add_subparsers(dest="action", required=True)
    for action in ("install", "status", "restore"):
        p_hook = hooks_sub.add_parser(action)
        p_hook.add_argument("--force", action="store_true")
        p_hook.add_argument("path", nargs="?", default=None)
        p_hook.set_defaults(func=cmd_hooks)

    p_gaps = sub.add_parser("gaps", help="List source files without matching tests")
    p_gaps.add_argument("--staged", action="store_true")
    p_gaps.add_argument("--json", action="store_true")
    p_gaps.add_argument("path", nargs="?", default=None)
    p_gaps.set_defaults(func=cmd_gaps)

    p_pr = sub.add_parser("pr", help="GitHub PR diff, CI, explain, babysit")
    p_pr.add_argument("pr_argv", nargs=argparse.REMAINDER, help="pr_check subcommand args")
    p_pr.set_defaults(func=cmd_pr)

    p_tui = sub.add_parser("tui", help="Open coding TUI")
    p_tui.add_argument("path", nargs="?", default=".")
    p_tui.set_defaults(func=cmd_tui)

    p_route = sub.add_parser("route", help="NL → dev command (internal)")
    p_route.add_argument("text", nargs="+")

    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 0
    if args.cmd == "route":
        line = route_command(" ".join(args.text))
        if line:
            print(line)
            return 0
        return 1
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
