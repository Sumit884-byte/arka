#!/usr/bin/env python3
"""Arka astronomy skill — stars, planets, moon phase, ISS passes."""

from __future__ import annotations

import sys
from pathlib import Path

_ROOT = Path(__file__).resolve().parent
if str(_ROOT) not in sys.path:
    sys.path.insert(0, str(_ROOT))

from lib import (  # noqa: E402
    format_iss_report,
    format_moon_report,
    lookup_object,
)


def main() -> int:
    args = sys.argv[1:]
    if not args or args[0] in ("-h", "--help", "help"):
        print("Arka astronomy — object lookup, moon phase, ISS passes")
        print("Usage:")
        print("  arka astronomy what <object>     — star/planet/galaxy info")
        print("  arka astronomy moon [tonight]    — current lunar phase")
        print("  arka astronomy iss [city|lat,lon] — ISS position and pass times")
        print("  arka astronomy lookup <name>")
        print("")
        print("NL examples:")
        print("  arka what is Betelgeuse")
        print("  arka moon phase tonight")
        print("  arka ISS pass times")
        return 0

    cmd = args[0].lower()
    rest = args[1:]

    if cmd in ("what", "lookup", "object", "star", "planet"):
        query = " ".join(rest).strip()
        if not query:
            print("Usage: arka astronomy what <object>", file=sys.stderr)
            return 1
        print(lookup_object(query))
        return 0

    if cmd == "moon":
        print(format_moon_report())
        return 0

    if cmd == "iss":
        location = " ".join(rest).strip()
        print(format_iss_report(location))
        return 0

    if cmd in ("position", "constellation"):
        query = " ".join(rest).strip() or cmd
        print(lookup_object(query))
        return 0

    # Passthrough: `arka astronomy Betelgeuse` or `arka astronomy moon phase`
    text = " ".join(args).strip()
    if re_is_moon(text):
        print(format_moon_report())
        return 0
    if re_is_iss(text):
        print(format_iss_report())
        return 0
    print(lookup_object(text))
    return 0


def re_is_moon(text: str) -> bool:
    import re

    return bool(re.search(r"(?i)\bmoon\b", text))


def re_is_iss(text: str) -> bool:
    import re

    return bool(re.search(r"(?i)\biss\b", text))


if __name__ == "__main__":
    raise SystemExit(main())
