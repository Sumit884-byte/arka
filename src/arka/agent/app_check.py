"""Detect and validate common app build/test commands."""
from __future__ import annotations

import argparse
import json
import subprocess
from pathlib import Path


def commands(root: Path) -> list[list[str]]:
    if (root / "package.json").is_file():
        return [["npm", "run", "build"], ["npm", "test", "--", "--runInBand"]]
    if (root / "pyproject.toml").is_file() or (root / "setup.py").is_file():
        return [["python", "-m", "compileall", "-q", "."], ["python", "-m", "pytest", "-q"]]
    if (root / "Cargo.toml").is_file():
        return [["cargo", "check"], ["cargo", "test"]]
    if (root / "go.mod").is_file():
        return [["go", "build", "./..."], ["go", "test", "./..."]]
    return []


def check(root: str = ".", *, run: bool = False) -> dict:
    path = Path(root).expanduser().resolve()
    plan = commands(path)
    results = []
    if run:
        for command in plan:
            proc = subprocess.run(command, cwd=path, text=True, capture_output=True, timeout=900, check=False)
            results.append({"command": command, "exit_code": proc.returncode, "output": (proc.stdout + proc.stderr)[-4000:]})
            if proc.returncode:
                break
    return {"root": str(path), "commands": plan, "results": results, "ok": not results or all(item["exit_code"] == 0 for item in results)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka app-check")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--run", action="store_true", help="Run the detected build and test checks")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    payload = check(args.path, run=args.run)
    if args.json:
        print(json.dumps(payload, indent=2))
    else:
        print(f"Detected checks for {payload['root']}:")
        for command in payload["commands"]:
            print("  "+" ".join(command))
        for result in payload["results"]:
            print(f"  {'PASS' if result['exit_code'] == 0 else 'FAIL'} {' '.join(result['command'])}")
            if result["exit_code"]:
                print(result["output"])
    return 0 if payload["ok"] else 1
