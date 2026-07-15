"""Preview and safely remove exact text from a file."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def inspect(path: str, text: str) -> int:
    target = Path(path).expanduser()
    content = target.read_text(encoding="utf-8")
    count = content.count(text)
    print(f"{target}: {count} match(es)")
    for number, line in enumerate(content.splitlines(), 1):
        if text in line:
            print(f"{number}: {line}")
    return 0


def remove(path: str, text: str, *, all_matches: bool = False, yes: bool = False, backup: bool = True) -> int:
    target = Path(path).expanduser()
    content = target.read_text(encoding="utf-8")
    count = content.count(text)
    if not count:
        print("No matches found")
        return 0
    if not yes:
        print(f"Found {count} match(es). Re-run with --yes to remove them.")
        return 2
    if backup:
        shutil.copy2(target, target.with_suffix(target.suffix + ".bak"))
    replacement = content.replace(text, "" if all_matches else "",  -1 if all_matches else 1)
    target.write_text(replacement, encoding="utf-8")
    print(f"Removed {count if all_matches else 1} match(es) from {target}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka text")
    sub = parser.add_subparsers(dest="action", required=True)
    for action in ("inspect", "remove"):
        p = sub.add_parser(action)
        p.add_argument("path")
        p.add_argument("text")
        if action == "remove":
            p.add_argument("--all", action="store_true", dest="all_matches")
            p.add_argument("--yes", action="store_true")
            p.add_argument("--no-backup", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.action == "inspect":
            return inspect(args.path, args.text)
        return remove(args.path, args.text, all_matches=args.all_matches, yes=args.yes, backup=not args.no_backup)
    except (OSError, UnicodeError) as exc:
        print(f"text: {exc}")
        return 2
