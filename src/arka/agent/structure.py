"""Read-only repository structure audit with safe, actionable suggestions."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

IGNORED = {".git", ".venv", "venv", "node_modules", "__pycache__", "dist", "build"}


def _ignored(path: Path) -> bool:
    return any(part in IGNORED or part.startswith(".venv") for part in path.parts)


def audit(root: Path) -> dict:
    root = root.resolve()
    top_files = sorted(p.name for p in root.iterdir() if p.is_file() and p.name not in {"README.md", "LICENSE"})
    caches = sorted(p.relative_to(root).as_posix() for p in root.rglob("__pycache__") if not _ignored(p.relative_to(root)))
    suggestions = []
    for name in top_files:
        if name.endswith(".py") and name not in {"setup.py", "conftest.py"}:
            suggestions.append({"path": name, "reason": "runtime Python should live under src/ or scripts/", "action": "review before moving"})
    return {"root": str(root), "top_level_files": top_files, "cache_directories": caches, "suggestions": suggestions}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka structure")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = audit(Path(args.path).expanduser())
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"root\t{result['root']}\ntop_level_files\t{len(result['top_level_files'])}\ncaches\t{len(result['cache_directories'])}")
        for item in result["suggestions"]:
            print(f"suggestion\t{item['path']}\t{item['reason']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
