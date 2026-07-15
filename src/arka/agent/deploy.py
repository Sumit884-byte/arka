"""Auditable deployment command generation for popular hosting platforms."""
from __future__ import annotations
import argparse
import json
import shutil
import subprocess
from pathlib import Path

def detect_platform(root: Path) -> str:
    if (root / "vercel.json").is_file() or (root / ".vercel").is_dir():
        return "vercel"
    if (root / "netlify.toml").is_file():
        return "netlify"
    if (root / "railway.toml").is_file() or (root / "Dockerfile").is_file() or (root / "docker-compose.yml").is_file():
        return "railway"
    if (root / "render.yaml").is_file():
        return "render"
    if (root / "package.json").is_file():
        return "vercel"
    return "netlify"

def deployment_command(root: Path, platform: str, *, production: bool = False) -> list[str]:
    if platform == "vercel":
        return ["vercel", "--prod"] if production else ["vercel"]
    if platform == "netlify":
        return ["netlify", "deploy", "--prod"] if production else ["netlify", "deploy"]
    if platform == "railway":
        return ["railway", "up", "--ci"] if production else ["railway", "up", "--ci", "--detach"]
    if platform == "render":
        return ["render", "deploy"]
    raise ValueError("platform must be vercel, netlify, railway, or render")

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Preview or run a guarded deployment")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--platform", choices=["vercel", "netlify", "railway", "render"])
    p.add_argument("--production", action="store_true")
    p.add_argument("--yes", action="store_true")
    p.add_argument("--json", action="store_true")
    args = p.parse_args(argv)
    root = Path(args.path).expanduser().resolve()
    platform = args.platform or detect_platform(root)
    command = deployment_command(root, platform, production=args.production)
    payload = {"root": str(root), "platform": platform, "command": command, "available": shutil.which(command[0]) is not None}
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Platform: {platform}\nCommand: {' '.join(command)}\nCLI available: {'yes' if payload['available'] else 'no'}")
    if not args.yes:
        return 0
    if not payload["available"]:
        print(f"Install {command[0]} and authenticate before deploying.")
        return 1
    return subprocess.call(command, cwd=root)
