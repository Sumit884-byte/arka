"""Keyword-first, ambiguity-safe file editing."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def find(path: str, keyword: str) -> list[tuple[int, str]]:
    lines = Path(path).expanduser().read_text(encoding="utf-8").splitlines()
    return [(i, line) for i, line in enumerate(lines, 1) if keyword.lower() in line.lower()]


def edit(path: str, keyword: str, replacement: str, *, all_matches: bool = False, yes: bool = False) -> int:
    target = Path(path).expanduser()
    content = target.read_text(encoding="utf-8")
    count = content.lower().count(keyword.lower())
    if count == 0:
        print("No relevant keyword found; no edit made")
        return 2
    if count > 1 and not all_matches:
        for line, text in find(path, keyword):
            print(f"{line}: {text}")
        print(f"Ambiguous: found {count} matches; refine the keyword or use --all --yes")
        return 2
    if not yes:
        print(f"Found {count} match(es); re-run with --yes to apply the surgical edit")
        return 2
    shutil.copy2(target, target.with_suffix(target.suffix + ".bak"))
    if all_matches:
        output = content.replace(keyword, replacement)
    else:
        index = content.lower().index(keyword.lower())
        output = content[:index] + replacement + content[index + len(keyword):]
    target.write_text(output, encoding="utf-8")
    print(f"Edited {target} ({count} match(es))")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka surgical-edit")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("find")
    p.add_argument("path")
    p.add_argument("keyword")
    p = sub.add_parser("edit")
    p.add_argument("path")
    p.add_argument("keyword")
    p.add_argument("replacement")
    p.add_argument("--all", action="store_true")
    p.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    if args.action == "find":
        for line, text in find(args.path, args.keyword):
            print(f"{line}: {text}")
        return 0
    return edit(args.path, args.keyword, args.replacement, all_matches=args.all, yes=args.yes)
