#!/usr/bin/env python3
"""Ensure every Mintlify MDX page has a valid Font Awesome icon in frontmatter."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path

ICON_RE = re.compile(r'^icon:\s*["\']?([^"\']+)["\']?\s*$', re.MULTILINE)
ICON_TYPE_RE = re.compile(r'^iconType:\s*["\']?([^"\']+)["\']?\s*$', re.MULTILINE)

# Names that are Lucide-only or otherwise invalid in Font Awesome.
ICON_FIXES = {
    "hub": "sitemap",
    "brain-circuit": "brain",
    "grid": "table-cells",
    "settings": "gear",
}

BRAND_ICONS = frozenset({"google", "youtube", "docker", "x-twitter", "github"})

DEFAULT_BY_PREFIX = {
    "guides/": "book-open",
    "concepts/": "lightbulb",
    "reference/": "list",
    "changelog/": "clock-rotate-left",
    "cn/guides/": "book-open",
    "cn/concepts/": "lightbulb",
    "cn/reference/": "list",
}

DEFAULT_BY_BASENAME = {
    "index": "book-open",
    "quickstart": "play",
}


def _default_icon(rel: str) -> str:
    for prefix, icon in DEFAULT_BY_PREFIX.items():
        if rel.startswith(prefix):
            return icon
    base = rel.rsplit("/", 1)[-1]
    return DEFAULT_BY_BASENAME.get(base, "file-lines")


def _parse_frontmatter(text: str) -> tuple[str, str, str] | None:
    if not text.startswith("---"):
        return None
    parts = text.split("---", 2)
    if len(parts) < 3:
        return None
    return parts[0], parts[1], parts[2]


def _upsert_field(fm: str, key: str, value: str) -> str:
    pattern = re.compile(rf"^{re.escape(key)}:.*$", re.MULTILINE)
    line = f'{key}: "{value}"'
    if pattern.search(fm):
        return pattern.sub(line, fm, count=1)
    lines = fm.rstrip().splitlines()
    lines.append(line)
    return "\n".join(lines) + "\n"


def sync_file(path: Path, root: Path, *, apply: bool) -> list[str]:
    rel = path.relative_to(root).as_posix()
    text = path.read_text(encoding="utf-8")
    parsed = _parse_frontmatter(text)
    if parsed is None:
        return [f"{rel}: missing YAML frontmatter"]
    prefix, fm, body = parsed
    changes: list[str] = []

    icon_match = ICON_RE.search(fm)
    icon = icon_match.group(1).strip() if icon_match else ""
    if not icon:
        icon = _default_icon(rel)
        fm = _upsert_field(fm, "icon", icon)
        changes.append("added icon")

    fixed = ICON_FIXES.get(icon)
    if fixed:
        fm = _upsert_field(fm, "icon", fixed)
        changes.append(f"icon {icon} -> {fixed}")
        icon = fixed

    want_type = "brands" if icon in BRAND_ICONS else ""
    have_type = (ICON_TYPE_RE.search(fm) or [None, ""])[1].strip()
    if want_type:
        if have_type != want_type:
            fm = _upsert_field(fm, "iconType", want_type)
            changes.append(f"iconType -> {want_type}")
    elif have_type == "brands" and icon not in BRAND_ICONS:
        fm = ICON_TYPE_RE.sub("", fm).rstrip() + "\n"
        changes.append("removed iconType brands")

    if not changes:
        return []

    if apply:
        path.write_text(f"---{fm}---{body}", encoding="utf-8")
    return [f"{rel}: {', '.join(changes)}"]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Sync Mintlify page icons in docs/**/*.mdx")
    parser.add_argument("root", nargs="?", default="docs")
    parser.add_argument("--check", action="store_true", help="Fail if any file would change")
    args = parser.parse_args(argv)
    root = Path(args.root)
    updates: list[str] = []
    for path in sorted(root.rglob("*.mdx")):
        updates.extend(sync_file(path, root, apply=not args.check))

    if updates:
        label = "Docs icon check failed" if args.check else "Synced doc icons"
        print(label + ":", file=sys.stderr)
        for item in updates:
            print(f"  - {item}", file=sys.stderr)
        return 1

    print(f"Doc icons OK: {root}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
