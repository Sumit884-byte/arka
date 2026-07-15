"""Priority-aware multitasking loop for rapid development."""
from __future__ import annotations

import argparse
import json
import subprocess
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass
from pathlib import Path


@dataclass(frozen=True)
class Task:
    name: str
    command: str
    priority: int
    paths: tuple[str, ...] = ()
    test_command: str = ""


def changed_files(root: Path) -> set[str]:
    proc = subprocess.run(["git", "diff", "--name-only"], cwd=root, capture_output=True, text=True, check=False)
    return {line.strip() for line in proc.stdout.splitlines() if line.strip()}


def touched(task: Task, changed: set[str]) -> bool:
    return not task.paths or any(path in changed or any(path.startswith(prefix.rstrip("/") + "/") for prefix in task.paths) for path in changed)


def run_command(command: str, root: Path) -> int:
    from arka.dispatch import run_skill
    return run_skill(command)


def run(tasks: list[Task], iterations: int, *, root: Path | None = None, priorities: bool = True, auto_priority: bool = False) -> dict:
    root = root or Path.cwd()
    if iterations < 1 or iterations > 1000:
        raise ValueError("iterations must be between 1 and 1000")
    if auto_priority:
        tasks = [Task(task.name, task.command, 1, task.paths, task.test_command) for task in tasks]
    report: list[dict] = []
    for iteration in range(1, iterations + 1):
        before = changed_files(root)
        with ThreadPoolExecutor(max_workers=max(1, min(len(tasks), 8))) as pool:
            codes = list(pool.map(lambda task: run_command(task.command, root), tasks))
        after = changed_files(root)
        changed = after - before
        checks: list[str] = []
        for task, code in zip(tasks, codes):
            should_check = touched(task, changed)
            if priorities and task.priority == 1 and should_check:
                checks.append(task.test_command or task.command)
            report.append({"iteration": iteration, "task": task.name, "exit": code, "edited": should_check})
        for command in checks:
            run_command(command, root)
    # Priority zero work is intentionally tested once, after all iterations.
    if priorities:
        for task in tasks:
            if task.priority == 0 and touched(task, changed_files(root)):
                run_command(task.test_command or task.command, root)
    return {"iterations": iterations, "priority_mode": priorities, "auto_priority": auto_priority, "results": report}


def parse_task(value: str) -> Task:
    parts = value.split("|", 4)
    if len(parts) < 3:
        raise ValueError("--task format is name|priority|command[|path1,path2|test-command]")
    name, priority, command = parts[:3]
    paths = tuple(x.strip() for x in parts[3].split(",") if x.strip()) if len(parts) >= 4 else ()
    test_command = parts[4].strip() if len(parts) == 5 else ""
    if priority not in {"0", "1"}:
        raise ValueError("priority must be 0 or 1")
    return Task(name, command, int(priority), paths, test_command)


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka ultra-fast")
    parser.add_argument("--iterations", type=int, default=1)
    parser.add_argument("--task", action="append", required=True, help="name|priority|command[|path1,path2|test-command]")
    parser.add_argument("--no-priority", action="store_true", help="disable priority-aware checks")
    parser.add_argument("--auto-priority", action="store_true", help="treat every task as priority 1")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    try:
        result = run([parse_task(item) for item in args.task], args.iterations, priorities=not args.no_priority, auto_priority=args.auto_priority)
    except (ValueError, OSError) as exc:
        parser.error(str(exc))
    print(json.dumps(result, indent=2) if args.json else f"completed {args.iterations} iteration(s)")
    return 0 if all(row["exit"] == 0 for row in result["results"]) else 1
