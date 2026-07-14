#!/usr/bin/env python3
"""Turn a design screenshot into a buildable product/spec brief."""

from __future__ import annotations

import argparse
import re
import shlex
import sys

from arka.vision.describe import describe_source

_KNOWN_CMDS = frozenset({"analyze", "parse", "help"})

DESIGN_PROMPT = (
    "Analyze this design screenshot as a product engineer. "
    "Return a concise implementation brief with: layout structure, key components, "
    "type scale, spacing rhythm, colors, interactions, and responsive behavior. "
    "Then list a practical build plan: suggested stack, component hierarchy, and a "
    "task breakdown that can be used to start building the project. "
    "If the screenshot looks like a website/app, infer the likely product type and "
    "call out any reusable design system patterns. Avoid vague praise."
)


def _normalize(text: str) -> str:
    t = re.sub(r"\s+", " ", (text or "").strip())
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        t = t[1:-1].strip()
    return t


def _looks_like_screenshot_target(text: str) -> bool:
    t = text.lower()
    return bool(
        re.search(r"\b(screenshot|screen|design|mockup|mock-up|wireframe|ui|ux|interface)\b", t)
        or re.search(r"\b(build|make|create|clone|recreate|implement)\b", t)
    )


def parse_request(text: str) -> tuple[str | None, str]:
    t = _normalize(text)
    if not t:
        return None, DESIGN_PROMPT

    m = re.search(
        r'(?i)(?:from|using|based on|with)\s+(?P<source>(?:~|/|\./|\.\./)[^\s"\']+|[^\s"\']+\.(?:png|jpe?g|webp|gif|bmp|tiff?|heic|svg))',
        t,
    )
    if m:
        source = m.group("source").strip("'\"")
        return source, t or DESIGN_PROMPT

    path_m = re.search(
        r'(?P<source>(?:~|/|\./|\.\./)[^\s"\']+|[^\s"\']+\.(?:png|jpe?g|webp|gif|bmp|tiff?|heic|svg))',
        t,
        re.I,
    )
    if path_m and _looks_like_screenshot_target(t):
        source = path_m.group("source").strip("'\"")
        return source, t or DESIGN_PROMPT

    if _looks_like_screenshot_target(t):
        return t, DESIGN_PROMPT
    return None, DESIGN_PROMPT


def nl_to_argv(text: str) -> list[str]:
    source, question = parse_request(_normalize(text))
    if not source:
        return []
    return ["analyze", source, question]


def route_command(text: str) -> str:
    raw = _normalize(text)
    if not raw:
        return ""
    low = raw.lower()
    if not _looks_like_screenshot_target(low):
        return ""
    if re.search(r"(?i)\b(screenshot|mockup|wireframe|ui|ux|design)\b", low):
        argv = nl_to_argv(raw)
        if argv:
            return "design_from_screenshot " + " ".join(shlex.quote(a) for a in argv)
    return ""


def cmd_analyze(args: argparse.Namespace) -> int:
    prompt = " ".join(args.prompt).strip() if args.prompt else DESIGN_PROMPT
    print(describe_source(args.source, prompt))
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(_normalize(" ".join(args.text)))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Turn design screenshots into product briefs")
    sub = p.add_subparsers(dest="cmd")

    p_an = sub.add_parser("analyze", help="Analyze a screenshot and print an implementation brief")
    p_an.add_argument("source", help="Image file or URL")
    p_an.add_argument("prompt", nargs="*", help="Optional focused prompt")
    p_an.set_defaults(func=cmd_analyze)

    p_parse = sub.add_parser("parse", help="Parse natural language → design_from_screenshot args")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)

    sub.add_parser("help", help="Show usage").set_defaults(
        func=lambda _a: (build_parser().print_help(), 0)[1]
    )
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        build_parser().print_help()
        return 0
    if argv[0] not in _KNOWN_CMDS:
        nl = nl_to_argv(" ".join(argv))
        if nl:
            argv = nl
        else:
            argv = ["analyze", *argv]
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
