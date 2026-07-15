"""Safely move files with preview, collision protection, and optional ref updates."""
from __future__ import annotations

import argparse
import shutil
from pathlib import Path


def move(source: str, destination: str, *, yes: bool = False, update_refs: bool = False) -> dict[str, object]:
    src = Path(source).expanduser().resolve()
    dest = Path(destination).expanduser().resolve()
    if not src.is_file():
        raise FileNotFoundError(f"source file not found: {src}")
    if dest.exists():
        raise FileExistsError(f"destination already exists: {dest}")
    result: dict[str, object] = {"source": str(src), "destination": str(dest), "updated_refs": []}
    if not yes:
        result["applied"] = False
        return result
    dest.parent.mkdir(parents=True, exist_ok=True)
    shutil.move(str(src), str(dest))
    if update_refs:
        old_names = {src.name, src.as_posix()}
        updated: list[str] = []
        root = src.parents[0]
        for path in root.rglob("*"):
            if not path.is_file() or path == dest or path.suffix.lower() not in {".py", ".ts", ".tsx", ".js", ".jsx", ".json", ".md", ".yaml", ".yml"}:
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            changed = text
            for old in old_names:
                changed = changed.replace(old, dest.name)
            if changed != text:
                path.write_text(changed, encoding="utf-8")
                updated.append(str(path))
        result["updated_refs"] = updated
    result["applied"] = True
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka move-file")
    parser.add_argument("source")
    parser.add_argument("destination")
    parser.add_argument("--yes", action="store_true", help="apply the move; otherwise preview")
    parser.add_argument("--update-refs", action="store_true", help="update simple textual references after moving")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = move(args.source, args.destination, yes=args.yes, update_refs=args.update_refs)
    except (OSError, ValueError) as exc:
        parser.error(str(exc))
    if args.json:
        import json
        print(json.dumps(result, indent=2))
    elif result["applied"]:
        print(f"Moved {result['source']} → {result['destination']}")
    else:
        print(f"Preview: move {result['source']} → {result['destination']}; re-run with --yes to apply")
    return 0
