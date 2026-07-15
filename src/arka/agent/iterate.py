"""Bounded iteration and interval loops, separate from the goal engine."""
from __future__ import annotations
import argparse
import time

def _run(command: str) -> int:
    from arka.dispatch import run_skill
    return run_skill(command)

def run_iterations(command: str, count: int) -> int:
    if count < 1 or count > 1000:
        raise ValueError("iteration count must be between 1 and 1000")
    for index in range(count):
        print(f"Iteration {index + 1}/{count}")
        if _run(command):
            return 1
    return 0

def run_loop(command: str, interval: float, count: int | None = None) -> int:
    if interval <= 0 or interval > 86400:
        raise ValueError("interval must be between 0 and 86400 seconds")
    completed = 0
    try:
        while count is None or completed < count:
            completed += 1
            print(f"Loop iteration {completed}")
            if _run(command):
                return 1
            if count is None or completed < count:
                time.sleep(interval)
    except KeyboardInterrupt:
        print(f"Stopped after {completed} loop iterations.")
    return 0

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Repeat an Arka skill or command")
    sub = p.add_subparsers(dest="mode", required=True)
    i = sub.add_parser("iterate", help="Run exactly N times")
    i.add_argument("count", type=int)
    i.add_argument("command", nargs=argparse.REMAINDER)
    loop_parser = sub.add_parser("loop", help="Run on an interval until stopped")
    loop_parser.add_argument("interval", type=float)
    loop_parser.add_argument("--count", type=int, default=None)
    loop_parser.add_argument("command", nargs=argparse.REMAINDER)
    args = p.parse_args(argv)
    command = " ".join(args.command).strip()
    if not command:
        p.error("a command is required")
    try:
        return run_iterations(command, args.count) if args.mode == "iterate" else run_loop(command, args.interval, args.count)
    except ValueError as exc:
        p.error(str(exc))
    return 2
