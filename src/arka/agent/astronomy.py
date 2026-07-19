#!/usr/bin/env python3
"""Astronomy skill — stars, planets, moon phase, ISS passes."""

from __future__ import annotations

import argparse
import importlib.util
import re
import shlex
import sys
from pathlib import Path
from typing import Any

_ASTRONOMY_EXCLUDE = re.compile(
    r"(?i)\b(?:"
    r"astrophysics\s+paper|"
    r"astronomy\s+club|"
    r"astronomy\s+course|"
    r"radio\s+astronomy\s+telescope\s+build"
    r")\b"
)


def _load_lib() -> Any:
    lib_path = Path(__file__).resolve().parents[1] / "skills" / "astronomy" / "lib.py"
    spec = importlib.util.spec_from_file_location("_astronomy_lib", lib_path)
    if spec is None or spec.loader is None:
        raise ImportError("astronomy lib not found")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _is_astronomy_request(text: str) -> bool:
    t = text.strip()
    if not t or _ASTRONOMY_EXCLUDE.search(t):
        return False
    if re.match(r"(?i)^(?:arka\s+)?astronomy\b", t):
        return True
    if re.search(
        r"(?i)\b(?:"
        r"moon\s+phase|"
        r"iss\s+pass|"
        r"international\s+space\s+station|"
        r"what\s+star\s+is|"
        r"what\s+planet\s+is|"
        r"planet\s+position|"
        r"constellation\s+\w+|"
        r"look\s+up\s+(?:star|planet)|"
        r"(?:list|show)\s+(?:all\s+)?(?:planets?|galax(?:y|ies)|planets?\s+and\s+galax(?:y|ies))|"
        r"astronomy\b"
        r")\b",
        t,
    ):
        return True
    if re.search(
        r"(?i)\bwhat\s+is\s+(?:betelgeuse|sirius|vega|polaris|rigel|mars|jupiter|saturn|venus|mercury|orion|andromeda)\b",
        t,
    ):
        return True
    return False


def _extract_object(text: str) -> str:
    t = text.strip()
    for pat in (
        r"(?i)^(?:arka\s+)?astronomy\s+(?:what|lookup|object|star|planet|constellation|position)\s+",
        r"(?i)^(?:what\s+star\s+is|what\s+planet\s+is)\s+",
        r"(?i)^(?:what\s+is)\s+",
        r"(?i)^(?:look\s+up)\s+",
        r"(?i)^(?:planet\s+position)\s+(?:of\s+)?",
        r"(?i)^(?:constellation)\s+",
    ):
        m = re.match(pat, t)
        if m:
            return t[m.end() :].strip(" ?.")
    return t


def nl_to_argv(text: str) -> list[str]:
    t = text.strip()
    if not t or not _is_astronomy_request(t):
        return []

    if re.search(r"(?i)\b(?:moon\s+phase|phase\s+of\s+the\s+moon|lunar\s+phase)\b", t):
        return ["moon"]

    if re.search(r"(?i)\b(?:list|show)\b.*\bplanets?\b.*\bgalax(?:y|ies)\b|\b(?:list|show)\s+all\s+(?:planets?|galax(?:y|ies))", t):
        return ["list", "all"]
    if re.search(r"(?i)\b(?:list|show)\s+(?:planets?|planetary)", t):
        return ["list", "planets"]
    if re.search(r"(?i)\b(?:list|show)\s+galax(?:y|ies)", t):
        return ["list", "galaxies"]

    if re.search(r"(?i)\b(?:iss|international\s+space\s+station)\b", t):
        m = re.search(
            r"(?i)\b(?:iss|space\s+station)\s+(?:pass(?:es)?|times|over)\s+(?:for\s+)?(.+)$",
            t,
        )
        if m:
            loc = m.group(1).strip()
            if loc.lower() not in ("times", "time", "passes", "pass"):
                return ["iss", loc]
        m = re.search(r"(?i)\bin\s+([A-Za-z][A-Za-z\s,.-]+)$", t)
        if m and "moon" not in m.group(1).lower():
            return ["iss", m.group(1).strip()]
        return ["iss"]

    if re.match(r"(?i)^(?:arka\s+)?astronomy\s+\S", t):
        rest = re.sub(r"(?i)^(?:arka\s+)?astronomy\s+", "", t).strip()
        if rest.lower().startswith(("moon", "iss", "what", "lookup")):
            return rest.split()
        if rest:
            return ["what", rest]

    obj = _extract_object(t)
    if obj:
        return ["what", obj]
    return []


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Astronomy lookups for Arka")
    sub = p.add_subparsers(dest="cmd")
    p_parse = sub.add_parser("parse", help="Parse natural language → astronomy args")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)
    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if argv and argv[0] == "parse":
        args = build_parser().parse_args(argv)
        return args.func(args)

    if argv and argv[0] in {"-h", "--help", "help"}:
        build_parser().print_help()
        return 0

    nl = nl_to_argv(" ".join(argv))
    if nl:
        argv = nl

    lib = _load_lib()
    if not argv:
        print("Usage: astronomy what <object> | moon | iss [location]", file=sys.stderr)
        return 1

    cmd = argv[0].lower()
    rest = argv[1:]

    if cmd in ("what", "lookup", "object", "star", "planet", "constellation", "position"):
        query = " ".join(rest).strip()
        if not query:
            print("Usage: astronomy what <object>", file=sys.stderr)
            return 1
        print(lib.lookup_object(query))
        return 0

    if cmd == "moon":
        print(lib.format_moon_report())
        return 0

    if cmd == "iss":
        print(lib.format_iss_report(" ".join(rest).strip()))
        return 0

    print(lib.lookup_object(" ".join(argv)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
