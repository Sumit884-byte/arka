"""Detect duplicate button/chip labels in frontend source."""
from __future__ import annotations

import argparse
import re
from collections import defaultdict
from pathlib import Path

_LABEL = re.compile(r"<(?:button|Button|Chip|chip|a)\b[^>]*>([^<{][^<]*)</(?:button|Button|Chip|chip|a)>", re.I)


def audit(root: str = ".") -> list[dict[str, object]]:
    base = Path(root).expanduser().resolve()
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    for path in base.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in {".html", ".htm", ".jsx", ".tsx", ".vue", ".svelte"}:
            continue
        if any(part in {"node_modules", ".git", "dist", "build"} for part in path.parts):
            continue
        try:
            lines = path.read_text(encoding="utf-8").splitlines()
        except (OSError, UnicodeDecodeError):
            continue
        for number, line in enumerate(lines, 1):
            for match in _LABEL.finditer(line):
                label = " ".join(match.group(1).split())
                key = re.sub(r"[^a-z0-9]+", " ", label.lower()).strip()
                if key:
                    groups[key].append({"label": label, "file": str(path), "line": number})
    return [{"phrase": key, "occurrences": values} for key, values in sorted(groups.items()) if len(values) > 1]


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka ui-copy", description="Find duplicate button/chip phrases")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    import json

    findings = audit(args.path)
    if args.json:
        print(json.dumps(findings, indent=2))
    elif not findings:
        print("No duplicate button/chip phrases found")
    else:
        for item in findings:
            print(f"duplicate: {item['phrase']}")
            for occurrence in item["occurrences"]:
                print(f"  {occurrence['file']}:{occurrence['line']} ({occurrence['label']})")
    return 1 if findings else 0
