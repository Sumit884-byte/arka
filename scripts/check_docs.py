#!/usr/bin/env python3
"""Lightweight docs reliability checks for Arka's Mintlify docs."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


LINK_RE = re.compile(r"\[[^\]]+\]\((/[^)\s#]+)(?:#[^)]+)?\)")
HREF_RE = re.compile(r'href="(/[^"#]+)(?:#[^"]+)?"')
TITLE_RE = re.compile(r"^title:\s*[\"']?(.+?)[\"']?\s*$", re.MULTILINE)
ICON_RE = re.compile(r"^icon:\s*[\"']?.+[\"']?\s*$", re.MULTILINE)


def _route_for(path: Path, root: Path) -> str:
    rel = "/" + path.relative_to(root).as_posix()
    rel = re.sub(r"\.(mdx|md)$", "", rel)
    return re.sub(r"/index$", "", rel) or "/"


def _routes(files: list[Path], root: Path) -> set[str]:
    routes = set()
    for file in files:
        route = _route_for(file, root)
        routes.add(route)
        if route == "/":
            routes.add("/index")
    return routes


def check_docs(root: Path) -> list[str]:
    files = sorted([*root.rglob("*.mdx"), *root.rglob("*.md")])
    routes = _routes(files, root)
    problems: list[str] = []
    for file in files:
        text = file.read_text(encoding="utf-8", errors="replace")
        if file.suffix == ".mdx" and not TITLE_RE.search(text):
            problems.append(f"{file}: missing frontmatter title")
        if file.suffix == ".mdx":
            fm = text.split("---", 2)[1] if text.startswith("---") else ""
            if not ICON_RE.search(fm):
                problems.append(f"{file}: missing frontmatter icon")
        for regex in (LINK_RE, HREF_RE):
            for match in regex.finditer(text):
                href = match.group(1)
                if href.startswith("//") or href in routes:
                    continue
                problems.append(f"{file}: broken internal link {href}")
    return problems


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Check Arka docs for broken internal links and basic metadata.")
    parser.add_argument("root", nargs="?", default="docs")
    args = parser.parse_args(argv)
    root = Path(args.root)
    problems = check_docs(root)
    if problems:
        print("Docs reliability check failed:", file=sys.stderr)
        for problem in problems:
            print(f"  - {problem}", file=sys.stderr)
        return 1
    print(f"Docs reliability check passed: {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
