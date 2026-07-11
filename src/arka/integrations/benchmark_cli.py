#!/usr/bin/env python3
"""CLI for benchmark-based orchestration."""

from __future__ import annotations

import argparse
import sys

try:
    from arka.paths import load_env_file

    load_env_file()
except ImportError:

    def load_env_file() -> None:
        pass


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    from arka.llm.benchmarks import (
        apply_rankings,
        ensure_default_suite,
        format_rankings_text,
        list_suites,
        load_suite,
        run_suite,
        store_suite_run,
    )

    parser = argparse.ArgumentParser(
        description="Benchmark providers/models and use results for orchestration routing"
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("init", help="Install default benchmark suite config").set_defaults(func=_cmd_init)

    p_run = sub.add_parser("run", help="Run a benchmark suite")
    p_run.add_argument("suite", nargs="?", default="default", help="Suite name (default: default)")
    p_run.add_argument(
        "--dry-run",
        action="store_true",
        help="Offline deterministic run (no API calls)",
    )
    p_run.add_argument(
        "--candidate",
        action="append",
        dest="candidates",
        default=[],
        help="Override candidate (provider/model or orchestrator:name)",
    )
    p_run.set_defaults(func=_cmd_run)

    sub.add_parser("list", help="List benchmark suites").set_defaults(func=_cmd_list)

    p_show = sub.add_parser("show", help="Show stored benchmark rankings")
    p_show.add_argument("profile", nargs="?", help="Task profile (chat, route, agent, …)")
    p_show.set_defaults(func=_cmd_show)

    p_apply = sub.add_parser("apply", help="Apply benchmark winners to llm-skill-models.json")
    p_apply.add_argument("--profile", action="append", dest="profiles", default=[])
    p_apply.add_argument("--suite", default="", help="Use rankings from one suite")
    p_apply.add_argument("--dry-run", action="store_true", help="Print apply plan only")
    p_apply.set_defaults(func=_cmd_apply)

    args = parser.parse_args(argv)
    if hasattr(args, "func"):
        return int(args.func(args))
    parser.print_help()
    return 1


def _cmd_init(_args: argparse.Namespace) -> int:
    from arka.llm.benchmarks import ensure_default_suite

    path = ensure_default_suite()
    print(f"Benchmark suite ready: {path}")
    print("Edit tasks/candidates, then run: arka benchmark run [--dry-run]")
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    from arka.llm.benchmarks import load_suite, parse_candidate_specs, run_suite, store_suite_run

    suite = load_suite(args.suite)
    if args.candidates:
        suite.candidates = parse_candidate_specs(args.candidates)
    if not suite.candidates:
        print("No candidates configured in suite.", file=sys.stderr)
        return 1
    if not suite.tasks:
        print("No tasks configured in suite.", file=sys.stderr)
        return 1

    payload = run_suite(suite, dry_run=bool(args.dry_run))
    path = store_suite_run(suite.name, payload)
    mode = "dry-run" if args.dry_run else "live"
    print(f"Benchmark complete ({mode}) → {path}")
    for profile, rows in sorted((payload.get("rankings") or {}).items()):
        if not rows:
            continue
        winner = rows[0]
        print(f"  {profile}: {winner.get('candidate')} (score={winner.get('score')})")
    return 0


def _cmd_list(_args: argparse.Namespace) -> int:
    from arka.llm.benchmarks import benchmarks_dir, list_suites

    names = list_suites()
    print(f"Suites in {benchmarks_dir()}:")
    for name in names:
        print(f"  - {name}")
    if not names:
        print("  (none)")
    return 0


def _cmd_show(args: argparse.Namespace) -> int:
    from arka.llm.benchmarks import format_rankings_text

    print(format_rankings_text(profile=args.profile))
    return 0


def _cmd_apply(args: argparse.Namespace) -> int:
    from arka.llm.benchmarks import apply_rankings

    profiles = args.profiles or None
    applied = apply_rankings(
        profiles=profiles,
        suite_name=args.suite or None,
        dry_run=bool(args.dry_run),
    )
    if not applied:
        print("No benchmark rankings to apply. Run: arka benchmark run", file=sys.stderr)
        return 1
    verb = "Would apply" if args.dry_run else "Applied"
    for profile, spec in applied:
        print(f"{verb} {profile} → {spec}")
    if not args.dry_run:
        print("Orchestration will prefer these models via llm-skill-models.json")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
