"""Discover services and frontend boundaries in a polyrepo/monorepo workspace."""

from __future__ import annotations
import argparse
import json
from pathlib import Path

IGNORE = {".git", "node_modules", "venv", ".venv", "dist", "build", "__pycache__"}
MANIFESTS = {
    "package.json": "node",
    "pyproject.toml": "python",
    "requirements.txt": "python",
    "go.mod": "go",
    "Cargo.toml": "rust",
    "Dockerfile": "container",
}


def discover(root: Path, depth: int = 3) -> dict:
    services = []
    for path in sorted(root.rglob("*")):
        if (
            not path.is_file()
            or len(path.relative_to(root).parts) > depth
            or any(p in IGNORE for p in path.parts)
        ):
            continue
        if path.name not in MANIFESTS:
            continue
        rel = path.parent.relative_to(root).as_posix() or "."
        kind = (
            "frontend"
            if path.name == "package.json"
            and any(
                x in path.parent.as_posix().lower()
                for x in ("front", "web", "ui", "app")
            )
            else "service"
        )
        services.append(
            {
                "path": rel,
                "manifest": path.name,
                "runtime": MANIFESTS[path.name],
                "kind": kind,
            }
        )
    return {"root": str(root), "services": services, "count": len(services)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka workspace")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--depth", type=int, default=3)
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    report = discover(Path(args.path).expanduser().resolve(), max(1, args.depth))
    if args.json:
        print(json.dumps(report, indent=2))
    else:
        print(f"workspace\t{report['root']}\nservices\t{report['count']}")
        for item in report["services"]:
            print(f"service\t{item['kind']}\t{item['runtime']}\t{item['path']}")
    return 0
