"""Persist design references and consistency instructions for coding tasks."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

from arka.paths import cache_dir


def _file() -> Path:
    return cache_dir() / "design_references.json"


def load() -> list[dict[str, str]]:
    try:
        data = json.loads(_file().read_text(encoding="utf-8"))
        return data if isinstance(data, list) else []
    except (OSError, json.JSONDecodeError):
        return []


def remember(reference: str, note: str = "") -> None:
    rows = load()
    rows.append({"reference": str(Path(reference).expanduser()) if "/" in reference or reference.endswith((".png", ".jpg", ".jpeg", ".webp")) else reference, "note": note})
    _file().parent.mkdir(parents=True, exist_ok=True)
    _file().write_text(json.dumps(rows[-20:], indent=2) + "\n", encoding="utf-8")


def context() -> str:
    rows = load()
    if not rows:
        return ""
    return "Design references to preserve while editing:\n" + "\n".join(
        f"- {row['reference']}: {row.get('note', '')}" for row in rows
    ) + "\nDo not change a design mode that already looks good; preserve button order and interaction order."


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka design-memory")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("remember")
    p.add_argument("reference")
    p.add_argument("--note", default="")
    sub.add_parser("list")
    args = parser.parse_args(argv)
    if args.action == "remember":
        remember(args.reference, args.note)
        print("Design reference remembered")
    else:
        print(context() or "No design references saved")
    return 0
