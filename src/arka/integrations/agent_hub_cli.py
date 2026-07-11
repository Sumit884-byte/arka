#!/usr/bin/env python3
"""Arka Agent Hub — shared MCP, memory, and skills for ollama launch agents."""

from __future__ import annotations

import argparse
import sys

from arka.integrations.agent_hub import (
    format_agent_list,
    format_doctor,
    format_status,
    launch_agent,
    nl_to_argv,
    sync_all,
)


def cmd_list(_args: argparse.Namespace) -> int:
    print(format_agent_list())
    return 0


def cmd_sync(args: argparse.Namespace) -> int:
    result = sync_all(force_adapters=args.force, use_symlink=args.symlink)
    print(f"synced_at\t{result.get('synced_at')}")
    mcp = result.get("mcp") or {}
    print(f"mcp\t{mcp.get('mode', '?')}\t{mcp.get('destination', '')}")
    memory = result.get("memory") or {}
    print(
        f"memory\t{memory.get('summary', '')}\t"
        f"facts={memory.get('fact_count', 0)} sessions={memory.get('session_count', 0)}"
    )
    skills = result.get("skills") or {}
    print(f"skills\t{skills.get('manifest', '')}\tcount={skills.get('count', 0)}")
    print(f"registry\t{result.get('registry', '')}")
    adapters = result.get("adapters") or []
    for row in adapters:
        written = "written" if row.get("written") else "snippet-only"
        print(f"adapter\t{row.get('label')}\t{written}\t{row.get('target')}")
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    print(format_status())
    return 0


def cmd_doctor(_args: argparse.Namespace) -> int:
    text, code = format_doctor()
    print(text)
    return code


def cmd_launch(args: argparse.Namespace) -> int:
    try:
        return launch_agent(
            args.name,
            list(args.extra or []),
            sync_on_launch=not args.no_sync,
        )
    except ValueError as exc:
        print(str(exc), file=sys.stderr)
        return 1


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(args.text)
    if not argv:
        return 1
    print("agent_hub " + " ".join(argv))
    return 0


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        prog="arka agent_hub",
        description="Shared MCP, memory, and skills hub for ollama launch agents",
    )
    sub = parser.add_subparsers(dest="command")

    sub.add_parser("list", help="List ollama launch agents")

    sync_p = sub.add_parser("sync", help="Refresh hub exports from Arka")
    sync_p.add_argument(
        "--force",
        action="store_true",
        help="Overwrite external MCP configs with hub servers (Cursor/Claude Desktop)",
    )
    sync_p.add_argument(
        "--symlink",
        action="store_true",
        help="Symlink hub/mcp.json to ~/.config/arka/mcp.json instead of copying",
    )

    sub.add_parser("status", help="Show sync state and configured agents")
    sub.add_parser("doctor", help="Check ollama and hub paths")

    launch_p = sub.add_parser("launch", help="Run ollama launch with shared hub env")
    launch_p.add_argument("name", help="Agent key (claude, hermes, openclaw, …)")
    launch_p.add_argument("extra", nargs=argparse.REMAINDER, help="Extra args for ollama launch")
    launch_p.add_argument(
        "--no-sync",
        action="store_true",
        help="Skip hub sync before launch (default: sync when AGENT_HUB_SYNC_ON_LAUNCH=1)",
    )

    parse_p = sub.add_parser("parse", help=argparse.SUPPRESS)
    parse_p.add_argument("text", help="Natural language request")
    return parser


def main(argv: list[str] | None = None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])
    if raw and raw[0] in ("-h", "--help", "help"):
        _print_help()
        return 0
    if not raw:
        _print_help()
        return 0

    parser = build_parser()
    args = parser.parse_args(raw)
    if not args.command:
        _print_help()
        return 0

    handlers = {
        "list": cmd_list,
        "sync": cmd_sync,
        "status": cmd_status,
        "doctor": cmd_doctor,
        "launch": cmd_launch,
        "parse": cmd_parse,
    }
    return handlers[args.command](args)


def _print_help() -> None:
    print(
        """Arka Agent Hub — shared config for ollama launch agents

Usage:
  arka agent_hub list                 List agents + launch commands
  arka agent_hub sync                 Copy MCP, export memory + skills manifest
  arka agent_hub sync --force         Also merge hub MCP into Cursor/Claude configs
  arka agent_hub status               Sync timestamps and adapter hints
  arka agent_hub doctor               Check ollama + hub paths
  arka agent_hub launch <name>        ollama launch with ARKA_HUB_* env vars

Shared paths (~/.config/arka/hub/):
  mcp.json              Canonical MCP (from ~/.config/arka/mcp.json)
  memory/summary.json   Lightweight memory export
  skills/manifest.json  Installed Arka skills
  agents.json           Registry + last sync times

Environment:
  ARKA_HUB_DIR              Hub root (default ~/.config/arka/hub)
  ARKA_MCP_CONFIG           MCP config path passed to agents
  ARKA_MEMORY_DIR           Memory export directory
  AGENT_HUB_SYNC_ON_LAUNCH  Sync before launch (default 1)

Examples:
  arka agent_hub sync
  arka agent_hub launch claude
  arka agent_hub launch hermes
  agent "sync agent hub"
  agent "launch claude code"
"""
    )


if __name__ == "__main__":
    raise SystemExit(main())
