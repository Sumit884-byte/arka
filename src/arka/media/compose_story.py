#!/usr/bin/env python3
"""Labeled story videos — AI images + stock B-roll with auto gap-fill.

Thin wrapper around compose_video story mode for routing and MCP.
"""

from __future__ import annotations

import argparse
import sys

from arka.media.compose_video import (
    build_parser,
    cmd_check,
    cmd_compose,
    nl_to_story_argv,
)


def nl_to_argv(text: str) -> list[str]:
    return nl_to_story_argv(text)


def build_story_parser() -> argparse.ArgumentParser:
    p = build_parser()
    p.description = (
        "Compose labeled story videos — LLM script, beat labels, captions, "
        "stock B-roll with AI image gap-fill"
    )
    return p


def cmd_story_compose(args: argparse.Namespace) -> int:
    args.story = True
    if not args.llm and not args.script:
        args.llm = True
    return cmd_compose(args)


def main(argv: list[str] | None = None) -> int:
    parser = build_story_parser()
    if not argv:
        argv = sys.argv[1:]
    if argv and argv[0] not in {"compose", "check", "parse"}:
        argv = ["compose", *argv]
    args = parser.parse_args(argv)
    if args.cmd == "compose":
        return cmd_story_compose(args)
    func = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 1
    return int(func(args) or 0)


if __name__ == "__main__":
    raise SystemExit(main())
