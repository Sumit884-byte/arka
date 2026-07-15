"""Remember concise, deterministic understanding of scripts Arka uses often."""
from __future__ import annotations

import argparse
import ast
import json
from pathlib import Path

from arka.paths import cache_dir


def _store() -> Path:
    return cache_dir() / "script_understanding.json"


def understand(path: str) -> dict[str, object]:
    target = Path(path).expanduser().resolve()
    source = target.read_text(encoding="utf-8")
    tree = ast.parse(source)
    functions = [node.name for node in ast.walk(tree) if isinstance(node, (ast.FunctionDef, ast.AsyncFunctionDef))]
    imports = [node.names[0].name for node in ast.walk(tree) if isinstance(node, ast.Import) and node.names]
    imports += [node.module for node in ast.walk(tree) if isinstance(node, ast.ImportFrom) and node.module]
    return {"path": str(target), "lines": len(source.splitlines()), "functions": sorted(set(functions)), "imports": sorted(set(imports)), "has_cli": "argparse" in imports or any(name == "main" for name in functions)}


def remember(path: str) -> dict[str, object]:
    payload = understand(path)
    try:
        data = json.loads(_store().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {}
    data[payload["path"]] = payload
    _store().parent.mkdir(parents=True, exist_ok=True)
    _store().write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")
    return payload


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka understand-script")
    sub = parser.add_subparsers(dest="action", required=True)
    p = sub.add_parser("remember")
    p.add_argument("path")
    p = sub.add_parser("show")
    p.add_argument("path")
    sub.add_parser("list")
    args = parser.parse_args(argv)
    if args.action == "remember":
        print(json.dumps(remember(args.path), indent=2))
    elif args.action == "show":
        print(json.dumps(understand(args.path), indent=2))
    else:
        try:
            print(json.dumps(json.loads(_store().read_text(encoding="utf-8")), indent=2))
        except (OSError, json.JSONDecodeError):
            print("{}")
    return 0
