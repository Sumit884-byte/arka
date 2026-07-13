#!/usr/bin/env python3
"""Metallurgy skill — alloy properties, composition, heat treatment."""

from __future__ import annotations

import argparse
import importlib.util
import re
import shlex
import sys
from pathlib import Path
from typing import Any


def _load_lib() -> Any:
    lib_path = Path(__file__).resolve().parents[1] / "skills" / "metallurgy" / "lib.py"
    spec = importlib.util.spec_from_file_location("_metallurgy_lib", lib_path)
    if spec is None or spec.loader is None:
        raise ImportError("metallurgy lib not found")
    mod = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(mod)
    return mod


def _is_metallurgy_request(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if re.match(r"(?i)^(?:arka\s+)?metallurgy\b", t):
        return True
    if re.search(
        r"(?i)\b(?:"
        r"metallurgy|"
        r"alloy\s+composition|"
        r"composition\s+of\s+(?:brass|bronze|steel|aluminum|aluminium|copper|titanium)|"
        r"properties\s+of\s+(?:steel|stainless|brass|bronze|aluminum|aluminium|alloy)|"
        r"steel\s+grade|"
        r"heat\s+treat(?:ment)?\s+(?:steps?\s+)?(?:for|of)\s+"
        r")\b",
        t,
    ):
        return True
    if re.search(r"(?i)\b(?:304|316|4140|6061|7075|brass|bronze|inconel)\s+(?:steel|alloy|stainless)?\b", t):
        if re.search(r"(?i)\b(?:properties|composition|heat)\b", t):
            return True
    return False


def _extract_alloy(text: str) -> str:
    t = text.strip()
    for pat in (
        r"(?i)^(?:arka\s+)?metallurgy\s+(?:properties|composition|heat|lookup)\s+",
        r"(?i)^(?:properties|property)\s+of\s+",
        r"(?i)^(?:alloy\s+)?composition\s+(?:of\s+)?",
        r"(?i)^(?:heat\s+treat(?:ment)?|heat-treatment)\s+(?:steps?\s+)?(?:for|of)\s+",
        r"(?i)^(?:steel\s+grade|grade)\s+",
    ):
        m = re.match(pat, t)
        if m:
            return t[m.end() :].strip(" ?.")
    return t


def nl_to_argv(text: str) -> list[str]:
    t = text.strip()
    if not t or not _is_metallurgy_request(t):
        return []

    if re.search(r"(?i)\bheat\s*treat", t):
        topic = _extract_alloy(t)
        return ["heat", topic] if topic else ["heat"]

    if re.search(r"(?i)\bcomposition\b", t):
        alloy = _extract_alloy(t)
        return ["composition", alloy] if alloy else ["composition"]

    if re.search(r"(?i)\bproperties\b", t):
        alloy = _extract_alloy(t)
        return ["properties", alloy] if alloy else ["properties"]

    if re.match(r"(?i)^(?:arka\s+)?metallurgy\s+\S", t):
        rest = re.sub(r"(?i)^(?:arka\s+)?metallurgy\s+", "", t).strip()
        return rest.split() if rest else []

    alloy = _extract_alloy(t)
    if alloy:
        return ["properties", alloy]
    return []


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Metallurgy lookups for Arka")
    sub = p.add_subparsers(dest="cmd")
    p_parse = sub.add_parser("parse", help="Parse natural language → metallurgy args")
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
        print(
            "Usage: metallurgy properties <alloy> | composition <alloy> | heat <topic>",
            file=sys.stderr,
        )
        return 1

    cmd = argv[0].lower()
    rest = argv[1:]

    if cmd in ("properties", "props", "property"):
        query = " ".join(rest).strip()
        print(lib.lookup_alloy(query))
        return 0

    if cmd in ("composition", "compose", "comp"):
        query = " ".join(rest).strip()
        print(lib.lookup_composition(query))
        return 0

    if cmd in ("heat", "heat-treatment", "heat_treatment", "treat"):
        topic = " ".join(rest).strip()
        print(lib.lookup_heat_treatment(topic))
        return 0

    print(lib.lookup_alloy(" ".join(argv)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
