"""Read-only production telemetry to codebase correlation."""

from __future__ import annotations
import argparse
import json
import re
from collections import Counter
from pathlib import Path
from typing import Any

PATH_RE = re.compile(
    r"(?:^|\s|\()([^\s():]+\.(?:py|js|jsx|ts|tsx|go|rs|java|rb|php|cs))(?::(\d+))?"
)


def _events(path: Path) -> list[dict[str, Any]]:
    payload = json.loads(path.read_text(encoding="utf-8"))
    if isinstance(payload, list):
        return [x for x in payload if isinstance(x, dict)]
    if isinstance(payload, dict):
        for key in ("events", "errors", "issues", "data", "results"):
            if isinstance(payload.get(key), list):
                return [x for x in payload[key] if isinstance(x, dict)]
        return [payload]
    return []


def correlate(source: Path, root: Path) -> dict[str, Any]:
    providers: Counter[str] = Counter()
    hotspots: Counter[str] = Counter()
    unmatched = 0
    for event in _events(source):
        providers[
            str(
                event.get("provider")
                or event.get("service")
                or event.get("source")
                or "unknown"
            )
        ] += 1
        found = False
        for raw, line in PATH_RE.findall(json.dumps(event, ensure_ascii=False)):
            candidates = (root / raw, root / Path(raw).name)
            match = next((p for p in candidates if p.is_file()), None)
            if match:
                rel = match.relative_to(root).as_posix()
                hotspots[f"{rel}:{line}" if line else rel] += 1
                found = True
        if not found:
            unmatched += 1
    return {
        "events": sum(providers.values()),
        "providers": dict(providers),
        "hotspots": hotspots.most_common(50),
        "unmatched": unmatched,
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        description="Correlate production telemetry JSON with repository files"
    )
    parser.add_argument("source", type=Path)
    parser.add_argument("--root", type=Path, default=Path.cwd())
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = correlate(args.source.expanduser(), args.root.expanduser().resolve())
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"events\t{report['events']}\nunmatched\t{report['unmatched']}")
        for path, count in report["hotspots"]:
            print(f"hotspot\t{count}\t{path}")
    return 0
