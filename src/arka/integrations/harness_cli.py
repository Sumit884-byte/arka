#!/usr/bin/env python3
"""CLI for agent harness (HarnessBench Lite)."""

from __future__ import annotations

import argparse
import json
import sys

try:
    from arka.paths import load_env_file

    load_env_file()
except ImportError:

    def load_env_file() -> None:
        pass


def main(argv: list[str] | None = None) -> int:
    load_env_file()

    parser = argparse.ArgumentParser(
        description="Run YAML agent harness suites — route, skill, and agent smoke tasks"
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("init", help="Install default harness suite").set_defaults(func=_cmd_init)
    sub.add_parser("list", help="List harness suites").set_defaults(func=_cmd_list)

    p_run = sub.add_parser("run", help="Run a harness suite")
    p_run.add_argument("suite", nargs="?", default="default", help="Suite name (default: default)")
    p_run.add_argument("--dry-run", action="store_true", help="Offline run using dry_response stubs")
    p_run.add_argument("--task", dest="task_id", default="", help="Run one task id only")
    p_run.add_argument("--json", action="store_true", help="Print JSON summary")
    p_run.set_defaults(func=_cmd_run)

    p_show = sub.add_parser("show", help="Show stored harness results")
    p_show.add_argument("suite", nargs="?", help="Filter to one suite")
    p_show.set_defaults(func=_cmd_show)

    args = parser.parse_args(argv)
    if hasattr(args, "func"):
        return int(args.func(args))
    parser.print_help()
    return 1


def _cmd_init(_args: argparse.Namespace) -> int:
    from arka.agent.harness import ensure_default_suite

    path = ensure_default_suite()
    print(f"Harness suite ready: {path}")
    print("Edit tasks, then run: arka harness run [--dry-run]")
    return 0


def _cmd_list(_args: argparse.Namespace) -> int:
    from arka.agent.harness import harnesses_dir, list_suites

    names = list_suites()
    print(f"Suites in {harnesses_dir()}:")
    for name in names:
        print(f"  - {name}")
    if not names:
        print("  (none)")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    from arka.agent.harness import HarnessSuite, load_suite, run_suite, store_suite_run

    suite = load_suite(args.suite)
    if args.task_id:
        tasks = [t for t in suite.tasks if t.id == args.task_id]
        if not tasks:
            print(f"Task not found: {args.task_id}", file=sys.stderr)
            return 1
        suite = HarnessSuite(name=suite.name, description=suite.description, tasks=tasks)

    payload = run_suite(suite, dry_run=bool(args.dry_run))
    path = store_suite_run(suite.name, payload)
    mode = "dry-run" if args.dry_run else "live"

    if args.json:
        print(json.dumps(payload, indent=2, ensure_ascii=False))
    else:
        print(f"Harness complete ({mode}) → {path}")
        print(f"  passed: {payload.get('passed')}/{payload.get('total')}")
        for row in payload.get("tasks") or []:
            mark = "ok" if row.get("passed") else "FAIL"
            line = f"  [{mark}] {row.get('task_id')} ({row.get('backend')}, {row.get('wall_ms')}ms)"
            print(line)
            if row.get("error"):
                print(f"       {row['error']}")

    return 0 if payload.get("failed", 1) == 0 else 1


def _cmd_show(args: argparse.Namespace) -> int:
    from arka.agent.harness import format_results_text

    print(format_results_text(suite_name=args.suite))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
