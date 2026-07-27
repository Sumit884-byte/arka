#!/usr/bin/env python3
"""Health reading — built-in track alias for daily_reading."""

from __future__ import annotations

from arka.agent.daily_reading import main as _daily_main

DEFAULT_TRACK = "health"


def main(argv: list[str] | None = None) -> int:
    """Run daily_reading with the health track as default."""
    args = list(argv or [])
    skip = {"init", "list-tracks", "use", "parse", "set-default"}
    has_track = any(a in ("--track", "-t") for a in args)
    if not has_track and (not args or args[0] not in skip):
        args = ["--track", DEFAULT_TRACK, *args]
    return _daily_main(args)


if __name__ == "__main__":
    raise SystemExit(main())
