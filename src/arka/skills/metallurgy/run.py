#!/usr/bin/env python3
"""Arka metallurgy skill — alloy properties, composition, heat treatment."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lib import lookup_alloy, lookup_composition, lookup_heat_treatment  # noqa: E402


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print("Arka metallurgy — alloy lookup and heat-treatment flows")
        print("Usage:")
        print("  arka metallurgy properties <alloy>   — mechanical properties")
        print("  arka metallurgy composition <alloy>  — elemental composition")
        print("  arka metallurgy heat <topic>         — heat-treatment steps")
        print("  arka metallurgy lookup <alloy>")
        print("")
        print("NL examples:")
        print("  arka properties of steel 304")
        print("  arka alloy composition brass")
        print("  arka heat treatment steps for aluminum")
        return 0

    cmd = args[0].lower()
    rest = args[1:]

    if cmd in ("properties", "props", "property"):
        query = " ".join(rest).strip()
        if not query:
            print("Usage: arka metallurgy properties <alloy>", file=sys.stderr)
            return 1
        print(lookup_alloy(query))
        return 0

    if cmd in ("composition", "compose", "comp"):
        query = " ".join(rest).strip()
        if not query:
            print("Usage: arka metallurgy composition <alloy>", file=sys.stderr)
            return 1
        print(lookup_composition(query))
        return 0

    if cmd in ("heat", "heat-treatment", "heat_treatment", "treat"):
        topic = " ".join(rest).strip()
        if not topic:
            print("Usage: arka metallurgy heat <alloy or process>", file=sys.stderr)
            return 1
        print(lookup_heat_treatment(topic))
        return 0

    if cmd in ("lookup", "alloy", "steel", "grade"):
        query = " ".join(rest).strip() or cmd
        print(lookup_alloy(query))
        return 0

    text = " ".join(args).strip()
    if _is_heat_request(text):
        print(lookup_heat_treatment(text))
        return 0
    if _is_composition_request(text):
        print(lookup_composition(text))
        return 0
    print(lookup_alloy(text))
    return 0


def _is_heat_request(text: str) -> bool:
    import re

    return bool(re.search(r"(?i)\bheat\s*treat", text))


def _is_composition_request(text: str) -> bool:
    import re

    return bool(re.search(r"(?i)\bcomposition\b", text))


if __name__ == "__main__":
    raise SystemExit(main())
