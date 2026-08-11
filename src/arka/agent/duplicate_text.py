"""Detect duplicate and near-duplicate visible text across project files."""
from __future__ import annotations

import argparse
import json
import re
import shlex
from collections import defaultdict
from difflib import SequenceMatcher
from pathlib import Path

_SKIP_DIRS = {"node_modules", ".git", "dist", "build", "__pycache__", ".next", "coverage", "venv", ".venv"}
_EXTENSIONS = {".html", ".htm", ".jsx", ".tsx", ".js", ".ts", ".vue", ".svelte", ".css", ".md", ".markdown"}

_TRIGGER_RE = re.compile(
    r"(?i)\b("
    r"duplicate\s+text|repeating\s+text|repeated\s+text|"
    r"semantically\s+same|near.?duplicate|similar\s+copy|"
    r"duplicate\s+copy|same\s+copy|copy\s+dedup|semantic\s+dedup|"
    r"find\s+(?:duplicate|similar|repeated)\s+(?:text|strings?|copy)|"
    r"check\s+for\s+duplicate|no\s+repeating\s+text|"
    r"duplicate_text|semantic_dedup|copy_dedup"
    r")\b"
)

_EXTRACTORS: tuple[re.Pattern[str], ...] = (
    re.compile(r"<(?:button|Button|Chip|chip|a|p|span|h[1-6]|label|Label)\b[^>]*>([^<{][^<]{2,})</", re.I),
    re.compile(
        r"(?:title|placeholder|aria-label|alt|label|description|heading|subtitle|message|tooltip|hint|text)"
        r'\s*=\s*["\']([^"\']{3,})["\']',
        re.I,
    ),
    re.compile(r'content\s*:\s*["\']([^"\']{3,})["\']', re.I),
    re.compile(r'^#+\s+(.+)$', re.M),
    re.compile(r'^\*\s+(.+)$', re.M),
    re.compile(r'^-\s+(.+)$', re.M),
)


def wants_duplicate_text(text: str) -> bool:
    return bool(_TRIGGER_RE.search(text or ""))


def _extract_path(text: str) -> str:
    match = re.search(r"(?:in|under|at)\s+([\w./~-]+)", text, re.I)
    return match.group(1) if match else "."


def route_command(text: str) -> str:
    if not wants_duplicate_text(text):
        return ""
    path = _extract_path(text)
    return f"duplicate_text {shlex.quote(path)}"


def normalize(text: str) -> str:
    cleaned = " ".join(text.split())
    cleaned = re.sub(r"[^a-z0-9\s]+", " ", cleaned.lower())
    return re.sub(r"\s+", " ", cleaned).strip()


def _should_skip(path: Path) -> bool:
    return any(part in _SKIP_DIRS for part in path.parts)


def _iter_files(root: Path) -> list[Path]:
    files: list[Path] = []
    for path in root.rglob("*"):
        if not path.is_file() or path.suffix.lower() not in _EXTENSIONS:
            continue
        if _should_skip(path):
            continue
        files.append(path)
    return files


def _extract_from_line(line: str, patterns: tuple[re.Pattern[str], ...] = _EXTRACTORS) -> list[str]:
    found: list[str] = []
    for pattern in patterns:
        for match in pattern.finditer(line):
            text = " ".join(match.group(1).split())
            if text:
                found.append(text)
    return found


def _extract_from_markdown(text: str) -> list[tuple[int, str]]:
    lines: list[tuple[int, str]] = []
    in_code = False
    for number, line in enumerate(text.splitlines(), 1):
        stripped = line.strip()
        if stripped.startswith("```"):
            in_code = not in_code
            continue
        if in_code or not stripped:
            continue
        for snippet in _extract_from_line(line):
            lines.append((number, snippet))
    return lines


def _extract_from_file(path: Path) -> list[tuple[int, str]]:
    try:
        text = path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return []
    if path.suffix.lower() in {".md", ".markdown"}:
        return _extract_from_markdown(text)
    found: list[tuple[int, str]] = []
    for number, line in enumerate(text.splitlines(), 1):
        for snippet in _extract_from_line(line):
            found.append((number, snippet))
    return found


def scan(
    root: str = ".",
    *,
    min_length: int = 4,
    near_threshold: float = 0.85,
    include_near: bool = True,
) -> dict[str, object]:
    base = Path(root).expanduser().resolve()
    groups: dict[str, list[dict[str, object]]] = defaultdict(list)
    unique_by_norm: dict[str, str] = {}

    for path in _iter_files(base):
        for line_no, snippet in _extract_from_file(path):
            norm = normalize(snippet)
            if len(norm) < min_length:
                continue
            unique_by_norm.setdefault(norm, snippet)
            groups[norm].append({"text": snippet, "file": str(path), "line": line_no})

    exact = [
        {"normalized": norm, "text": unique_by_norm[norm], "occurrences": values}
        for norm, values in sorted(groups.items())
        if len(values) > 1
    ]

    near: list[dict[str, object]] = []
    if include_near:
        norms = sorted(groups)
        used: set[str] = set()
        for idx, left in enumerate(norms):
            if left in used or len(groups[left]) > 1:
                continue
            for right in norms[idx + 1 :]:
                if right in used or len(groups[right]) > 1:
                    continue
                if left == right:
                    continue
                len_ratio = min(len(left), len(right)) / max(len(left), len(right))
                if len_ratio < 0.5:
                    continue
                ratio = SequenceMatcher(None, left, right).ratio()
                if ratio < near_threshold:
                    continue
                occurrences = groups[left] + groups[right]
                near.append(
                    {
                        "similarity": round(ratio, 3),
                        "normalized": [left, right],
                        "occurrences": occurrences,
                    }
                )
                used.add(left)
                used.add(right)
                break

    return {"path": str(base), "exact": exact, "near": near}


def format_report(payload: dict[str, object]) -> str:
    lines = [f"Duplicate text scan: {payload['path']}", ""]
    exact = payload.get("exact") or []
    near = payload.get("near") or []

    if not exact and not near:
        lines.append("No duplicate or near-duplicate text found.")
        return "\n".join(lines).strip()

    if exact:
        lines.append(f"Exact duplicates ({len(exact)}):")
        for item in exact:
            lines.append(f"- {item['normalized']!r}")
            for occ in item["occurrences"]:
                lines.append(f"  {occ['file']}:{occ['line']} ({occ['text']!r})")
        lines.append("")

    if near:
        lines.append(f"Near duplicates ({len(near)}):")
        for item in near:
            norms = item.get("normalized") or []
            lines.append(f"- similarity {item['similarity']}: {' ~ '.join(repr(n) for n in norms)}")
            for occ in item["occurrences"]:
                lines.append(f"  {occ['file']}:{occ['line']} ({occ['text']!r})")
        lines.append("")

    lines.append(f"Summary: {len(exact)} exact groups, {len(near)} near-duplicate groups")
    return "\n".join(lines).strip()


def main(argv: list[str] | None = None) -> int:
    import sys

    args = list(argv if argv is not None else sys.argv[1:])
    if args and args[0] == "route":
        line = route_command(" ".join(args[1:]))
        if line:
            print(line)
            return 0
        return 1

    parser = argparse.ArgumentParser(prog="arka duplicate_text", description="Find duplicate and near-duplicate text")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--json", action="store_true")
    parser.add_argument("--min-length", type=int, default=4)
    parser.add_argument("--near-threshold", type=float, default=0.85)
    parser.add_argument("--no-near", action="store_true", help="Skip near-duplicate detection")

    ns = parser.parse_args(args)
    payload = scan(
        ns.path,
        min_length=ns.min_length,
        near_threshold=ns.near_threshold,
        include_near=not ns.no_near,
    )
    if ns.json:
        print(json.dumps(payload, indent=2))
    else:
        print(format_report(payload))

    has_findings = bool(payload["exact"] or payload["near"])
    return 1 if has_findings else 0


if __name__ == "__main__":
    raise SystemExit(main())
