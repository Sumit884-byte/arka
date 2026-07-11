#!/usr/bin/env python3
"""Arka agent teams and workflows — cross-agent orchestration."""

from __future__ import annotations

import argparse
import json
import sys

from arka.teams.executor import format_run_result, run_team, run_workflow
from arka.teams.io import (
    ensure_layout,
    format_team_list,
    format_team_show,
    format_workflow_list,
    format_workflow_show,
    list_teams,
    list_workflows,
    load_team,
    load_workflow,
    save_team,
    save_workflow,
    templates_dir,
)
from arka.teams.resolve import format_resolved
from arka.teams.schema import parse_team, parse_workflow


def cmd_team_list(_args: argparse.Namespace) -> int:
    print(format_team_list())
    return 0


def cmd_team_show(args: argparse.Namespace) -> int:
    try:
        print(format_team_show(args.name))
        if args.resolve:
            print(format_resolved(load_team(args.name)))
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def cmd_team_create(args: argparse.Namespace) -> int:
    template = args.template or args.name
    src = templates_dir() / f"team-{template}.yaml"
    if not src.is_file():
        src = templates_dir() / f"team-{template}.json"
    if not src.is_file():
        print(f"Unknown team template: {template}", file=sys.stderr)
        print(f"Available: research, code-review", file=sys.stderr)
        return 1
    from arka.teams.io import _load_text

    data = _load_text(src)
    data["name"] = args.name
    team = parse_team(data)
    path = save_team(team, fmt=args.format)
    print(f"created\t{path}")
    return 0


def cmd_team_run(args: argparse.Namespace) -> int:
    task = (args.task or "").strip()
    if not task:
        print("Usage: arka team run <name> --task \"...\"", file=sys.stderr)
        return 1
    try:
        result = run_team(args.name, task, workflow_name=args.workflow)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_run_result(result))
    return 0 if result.get("ok") else 1


def cmd_workflow_list(_args: argparse.Namespace) -> int:
    print(format_workflow_list())
    return 0


def cmd_workflow_show(args: argparse.Namespace) -> int:
    try:
        print(format_workflow_show(args.name))
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    return 0


def cmd_workflow_create(args: argparse.Namespace) -> int:
    template = args.template or args.name
    src = templates_dir() / f"workflow-{template}.yaml"
    if not src.is_file():
        src = templates_dir() / f"workflow-{template}.json"
    if not src.is_file():
        print(f"Unknown workflow template: {template}", file=sys.stderr)
        print("Available: review-and-ship, code-review, brainstorm", file=sys.stderr)
        return 1
    from arka.teams.io import _load_text

    data = _load_text(src)
    data["name"] = args.name
    if args.team:
        data["team"] = args.team
    workflow = parse_workflow(data)
    path = save_workflow(workflow, fmt=args.format)
    print(f"created\t{path}")
    return 0


def cmd_workflow_run(args: argparse.Namespace) -> int:
    task = (args.task or "").strip()
    if not task:
        print('Usage: arka workflow run <name> --task "..."', file=sys.stderr)
        return 1
    try:
        result = run_workflow(args.name, task)
    except (FileNotFoundError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(format_run_result(result))
    return 0 if result.get("ok") else 1


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arka teams",
        description="Agent teams and workflows across agents, models, and providers",
    )
    sub = parser.add_subparsers(dest="group")

    team = sub.add_parser("team", help="Manage agent teams")
    team_sub = team.add_subparsers(dest="command")
    team_sub.add_parser("list", help="List teams")
    show_p = team_sub.add_parser("show", help="Show team config")
    show_p.add_argument("name")
    show_p.add_argument("--resolve", action="store_true", help="Show resolved launch targets")
    create_p = team_sub.add_parser("create", help="Create team from template")
    create_p.add_argument("name")
    create_p.add_argument("--template", help="Template name (default: same as name)")
    create_p.add_argument("--format", choices=("yaml", "json"), default="yaml")
    run_p = team_sub.add_parser("run", help="Run team default workflow")
    run_p.add_argument("name")
    run_p.add_argument("--task", required=True)
    run_p.add_argument("--workflow", help="Override workflow name")
    run_p.add_argument("--json", action="store_true")

    wf = sub.add_parser("workflow", help="Manage workflows")
    wf_sub = wf.add_subparsers(dest="command")
    wf_sub.add_parser("list", help="List workflows")
    wf_show = wf_sub.add_parser("show", help="Show workflow config")
    wf_show.add_argument("name")
    wf_create = wf_sub.add_parser("create", help="Create workflow from template")
    wf_create.add_argument("name")
    wf_create.add_argument("--template", help="Template name (default: same as name)")
    wf_create.add_argument("--team", help="Override team name")
    wf_create.add_argument("--format", choices=("yaml", "json"), default="yaml")
    wf_run = wf_sub.add_parser("run", help="Run workflow")
    wf_run.add_argument("name")
    wf_run.add_argument("--task", required=True)
    wf_run.add_argument("--json", action="store_true")

    return parser


def main(argv: list[str] | None = None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])
    if raw and raw[0] in ("-h", "--help", "help"):
        _print_help()
        return 0
    if not raw:
        _print_help()
        return 0

    ensure_layout()

    if raw[0] == "team":
        raw = ["team", *raw[1:]]
    elif raw[0] == "workflow":
        raw = ["workflow", *raw[1:]]
    elif raw[0] in ("teams",):
        if len(raw) >= 2 and raw[1] == "team":
            raw = raw[1:]
        else:
            raw = ["team", *raw[1:]]

    parser = build_parser()
    args = parser.parse_args(raw)
    if not args.group or not args.command:
        _print_help()
        return 0

    handlers = {
        ("team", "list"): cmd_team_list,
        ("team", "show"): cmd_team_show,
        ("team", "create"): cmd_team_create,
        ("team", "run"): cmd_team_run,
        ("workflow", "list"): cmd_workflow_list,
        ("workflow", "show"): cmd_workflow_show,
        ("workflow", "create"): cmd_workflow_create,
        ("workflow", "run"): cmd_workflow_run,
    }
    handler = handlers.get((args.group, args.command))
    if not handler:
        _print_help()
        return 1
    return handler(args)


def _print_help() -> None:
    print(
        """Arka Agent Teams — orchestrate agents, models, and providers

Usage:
  arka team list
  arka team show <name> [--resolve]
  arka team create <name> [--template research]
  arka team run <name> --task "..." [--workflow <name>]

  arka workflow list
  arka workflow show <name>
  arka workflow create <name> [--template review-and-ship] [--team research]
  arka workflow run <name> --task "..."

Config paths (under ~/.config/arka/):
  teams/       Team definitions (agents, models, providers by role)
  workflows/   Step graphs (sequential, parallel, round-robin)

Environment:
  ARKA_TEAMS_DIR       Override teams directory
  ARKA_WORKFLOWS_DIR   Override workflows directory
  TEAM_MAX_PARALLEL    Max parallel workflow steps (default 4)
  TEAM_RETRY_BACKOFF   Exponential retry delay (default off)
  TEAM_MCP_TOOL_ROUNDS MCP tool loop rounds for model steps (default 0)

Examples:
  arka team list
  arka team show research --resolve
  arka team run research --task "Summarize Rust async patterns"
  arka workflow run review-and-ship --task "Plan a v2 auth redesign"
"""
    )


if __name__ == "__main__":
    raise SystemExit(main())
