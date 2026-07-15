"""Reverse-engineer a local Git repository into a build-ready prompt."""
from __future__ import annotations
import argparse
import subprocess
from pathlib import Path

def reverse(root: Path, *, commits: int = 20) -> str:
    log = subprocess.run(["git", "log", f"-{commits}", "--date=short", "--pretty=format:%h %ad %s", "--stat"], cwd=root, capture_output=True, text=True, check=False)
    files = subprocess.run(["git", "ls-files"], cwd=root, capture_output=True, text=True, check=False)
    return "# Repository reverse-engineering prompt\n\n" + f"Root: {root}\n\n## Files\n" + (files.stdout[:12000] or "(none)") + "\n\n## Recent evolution\n" + (log.stdout[:16000] or "(no Git history)") + "\n\n## Build brief\nReconstruct the architecture, identify stable interfaces, preserve behavior, and verify changes with the project’s tests."

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Turn Git history and layout into a build prompt")
    p.add_argument("path", nargs="?", default=".")
    p.add_argument("--commits", type=int, default=20)
    p.add_argument("--output")
    args = p.parse_args(argv)
    text = reverse(Path(args.path).expanduser().resolve(), commits=max(1, min(args.commits, 200)))
    if args.output:
        Path(args.output).expanduser().write_text(text, encoding="utf-8")
    else:
        print(text)
    return 0
