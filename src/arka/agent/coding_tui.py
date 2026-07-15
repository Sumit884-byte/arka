"""Small dependency-free terminal UI for the Arka coding agent."""
from __future__ import annotations

import argparse
from pathlib import Path


HELP = "Commands: /help, /status, /plan <goal>, /run <goal>, /quit. Plain text is treated as a plan request."


def status(root: Path) -> str:
    files = sum(1 for p in root.rglob("*") if p.is_file() and ".git" not in p.parts)
    return f"repo: {root}\nfiles: {files}\nTip: use /plan before /run for a reviewable change plan."


def run(root: str = ".") -> int:
    repo = Path(root).expanduser().resolve()
    from arka.agent.core import code_agent

    print(f"Arka coding TUI — {repo}")
    print(HELP)
    while True:
        try:
            line = input("arka> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line in {"/quit", "/exit", "quit", "exit"}:
            return 0
        if line == "/help":
            print(HELP)
        elif line == "/status":
            print(status(repo))
        elif line.startswith("/plan "):
            print(f"Plan request queued: {line[6:].strip()}")
            print("Review the plan before asking Arka to run it.")
        elif line.startswith("/run "):
            code_agent(line[5:].strip(), repo=str(repo))
        else:
            print(f"Plan request: {line}\nUse /run <goal> to execute after review.")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka coding-tui")
    parser.add_argument("path", nargs="?", default=".")
    return run(parser.parse_args(argv).path)
