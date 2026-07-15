"""User-managed enabled/disabled skill preferences."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from arka.paths import config_dir


def _path() -> Path:
    return config_dir() / "skills.json"


def disabled() -> set[str]:
    try:
        return set(json.loads(_path().read_text()).get("disabled", []))
    except (OSError, ValueError):
        return set()


def is_disabled(name: str) -> bool:
    return name in disabled()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka skills")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for command in ("disable", "enable"):
        sub.add_parser(command).add_argument("name")
    sub.add_parser("list")
    args = parser.parse_args(argv)
    names = disabled()
    if args.cmd == "list":
        print("disabled\t" + (", ".join(sorted(names)) if names else "none"))
        return 0
    if args.cmd == "enable":
        names.discard(args.name)
    else:
        names.add(args.name)
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps({"disabled": sorted(names)}, indent=2) + "\n")
    print(f"{args.cmd}d\t{args.name}")
    return 0
