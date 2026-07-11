#!/usr/bin/env python3
"""Top-level ``arka memory`` CLI — flat alias over unified memory + scoped scratchpad."""

from __future__ import annotations

import sys

from arka.core.unified_memory import print_status, run_cli

_MEMORY_USAGE = """\
Arka memory — remember, recall, status, scope, scratchpad, promote

Usage:
  arka memory                              Show status + commands
  arka memory remember <text>              Store in the best layer
  arka memory recall <goal>                Aggregate context by goal
  arka memory status                       Layer counts and scope stats
  arka memory scope status                 Trust cap and scratchpad stats
  arka memory scratchpad list [--team T]     List workflow scratchpad entries
  arka memory scratchpad show <id>         Show one scratchpad entry
  arka memory promote <id>                 Promote scratchpad entry to global facts

Legacy aliases unified_memory and memory_scope still work.
"""


def normalize_memory_argv(argv: list[str]) -> list[str]:
    """Map flat ``memory`` subcommands to unified_memory argv."""
    if not argv:
        return ["status"]
    head = argv[0].lower()
    if head in {"remember", "store", "save"}:
        return ["remember", *argv[1:]]
    if head in {"recall", "context", "ctx"}:
        return ["recall", *argv[1:]]
    if head == "status":
        return ["status", *argv[1:]]
    if head == "scope":
        return ["scope", *argv[1:]]
    if head == "scratchpad":
        return ["scope", "scratchpad", *argv[1:]]
    if head == "promote":
        return ["scope", "promote", *argv[1:]]
    return argv


def main(argv: list[str] | None = None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])
    normalized = normalize_memory_argv(raw)
    if not raw:
        print_status()
        print()
        print(_MEMORY_USAGE.rstrip())
        return 0
    return run_cli(normalized)


if __name__ == "__main__":
    raise SystemExit(main())
