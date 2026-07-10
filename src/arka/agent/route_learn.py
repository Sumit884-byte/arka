#!/usr/bin/env python3
"""Teach Arka how to route natural language to CLI integrations."""

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
    from arka.routing.learned import (
        delete_route,
        learn_from_trace,
        learn_route,
        match_learned,
        route_management_command,
        wants_route_management,
    )

    parser = argparse.ArgumentParser(
        description="Learn and manage NL → skill routing rules"
    )
    sub = parser.add_subparsers(dest="cmd")

    p_learn = sub.add_parser("learn", help="Teach a phrase → skill mapping")
    p_learn.add_argument("phrase", nargs="?", help="Natural language trigger phrase")
    p_learn.add_argument("skill", nargs="?", help="Skill/command line to run")
    p_learn.add_argument("--id", help="Optional route id")
    p_learn.add_argument("--note", default="", help="Optional note")
    p_learn.add_argument(
        "--from-trace",
        action="store_true",
        help="Use last routing trace input (and --correct skill)",
    )
    p_learn.add_argument(
        "--correct",
        default="",
        help="Skill line to pair with trace input (--from-trace)",
    )

    sub.add_parser("list", help="List learned routes").set_defaults(func=_cmd_list)
    sub.add_parser("show", help="Alias for list").set_defaults(func=_cmd_list)

    p_delete = sub.add_parser("delete", help="Delete a learned route by id or phrase")
    p_delete.add_argument("route_id")
    p_delete.set_defaults(func=_cmd_delete)

    p_test = sub.add_parser("test", help="Test how a phrase would route")
    p_test.add_argument("phrase", nargs="+")
    p_test.set_defaults(func=_cmd_test)

    p_match = sub.add_parser("match", help="Return skill line for phrase (internal)")
    p_match.add_argument("text", nargs="+")
    p_match.set_defaults(func=_cmd_match)

    p_route = sub.add_parser("route", help="Map NL management/teach request to command")
    p_route.add_argument("text", nargs="+")
    p_route.set_defaults(func=_cmd_route)

    args = parser.parse_args(argv)

    if args.cmd == "learn":
        return _cmd_learn(args, learn_route=learn_route, learn_from_trace=learn_from_trace)
    if hasattr(args, "func"):
        return int(args.func(args))
    parser.print_help()
    return 1


def _cmd_list(_args: argparse.Namespace) -> int:
    from arka.routing.learned import format_routes_text

    print(format_routes_text())
    return 0


def _cmd_delete(args: argparse.Namespace) -> int:
    from arka.routing.learned import delete_route

    if delete_route(args.route_id):
        print(f"Deleted route: {args.route_id}")
        return 0
    print(f"No route found for: {args.route_id}", file=sys.stderr)
    return 1


def _cmd_test(args: argparse.Namespace) -> int:
    from arka.routing.learned import match_learned

    phrase = " ".join(args.phrase).strip()
    hit = match_learned(phrase)
    if hit:
        print(hit)
        return 0
    print("(no learned route match)")
    return 1


def _cmd_match(args: argparse.Namespace) -> int:
    from arka.routing.learned import match_learned

    text = " ".join(args.text).strip()
    hit = match_learned(text)
    if hit:
        print(hit)
        return 0
    return 1


def _cmd_route(args: argparse.Namespace) -> int:
    from arka.routing.learned import route_management_command, wants_route_management

    text = " ".join(args.text).strip()
    if not wants_route_management(text):
        return 1
    cmd = route_management_command(text)
    if cmd:
        print(cmd)
        return 0
    return 1


def _cmd_learn(
    args: argparse.Namespace,
    *,
    learn_route,
    learn_from_trace,
) -> int:
    if args.from_trace:
        try:
            entry = learn_from_trace(correct=args.correct, phrase=args.phrase or "")
        except (ValueError, RuntimeError) as exc:
            print(str(exc), file=sys.stderr)
            return 1
        print(f"Learned from trace: {entry.get('id')}")
        print(f"  say: {', '.join(entry.get('triggers') or [])}")
        print(f"  run: {entry.get('skill')}")
        return 0

    phrase = (args.phrase or "").strip()
    skill = (args.skill or "").strip()
    if not phrase or not skill:
        print(
            "Usage: route_learn learn <phrase> <skill>\n"
            "       route_learn learn --from-trace --correct \"skill line\"",
            file=sys.stderr,
        )
        return 1
    entry = learn_route(phrase, skill, route_id=args.id or "", note=args.note or "")
    print(f"Learned route: {entry.get('id')}")
    print(f"  say: {', '.join(entry.get('triggers') or [])}")
    print(f"  run: {entry.get('skill')}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
