"""Reusable plan/implement/verify loop for software-engineering tasks.

This is deliberately a small orchestration layer: it composes existing Arka
skills instead of copying a second goal engine.  Every run is bounded and has
an explicit verification gate, so it is safe to use from other workflows.
"""
from __future__ import annotations

import argparse
import json
import re
from dataclasses import asdict, dataclass

STAGES = ("observe", "plan", "implement", "verify", "review", "learn")
MAX_ITERATIONS = 20


@dataclass(frozen=True)
class LoopPlan:
    task: str
    iterations: int
    stages: tuple[str, ...]
    skills: tuple[str, ...]
    approval_required: bool = True


def _skills_for(task: str) -> tuple[str, ...]:
    lowered = task.lower()
    skills = ["repo_context", "repo_health", "plan"]
    if re.search(r"frontend|ui|ux|screenshot|component|css", lowered):
        skills.extend(("design_memory", "frontend_loop"))
    elif re.search(r"api|backend|service|endpoint", lowered):
        skills.extend(("urlkit", "lint_project"))
    else:
        skills.append("lint_project")
    skills.extend(("ci", "review"))
    return tuple(dict.fromkeys(skills))


def build_plan(task: str, iterations: int = 1) -> LoopPlan:
    """Build a bounded loop plan without making an LLM call or editing files."""
    task = task.strip()
    if not task:
        raise ValueError("a task is required")
    if iterations < 1 or iterations > MAX_ITERATIONS:
        raise ValueError(f"iterations must be between 1 and {MAX_ITERATIONS}")
    return LoopPlan(task, iterations, STAGES, _skills_for(task))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Plan a bounded engineering loop")
    parser.add_argument("task", nargs="+", help="task to plan and verify")
    parser.add_argument("--iterations", "-n", type=int, default=1)
    parser.add_argument("--apply", action="store_true", help="allow a later agent to apply the plan")
    parser.add_argument("--json", action="store_true", dest="as_json")
    args = parser.parse_args(argv)
    try:
        plan = build_plan(" ".join(args.task), args.iterations)
    except ValueError as exc:
        parser.error(str(exc))
    if args.apply:
        plan = LoopPlan(plan.task, plan.iterations, plan.stages, plan.skills, False)
    payload = asdict(plan)
    if args.as_json:
        print(json.dumps(payload, sort_keys=True))
    else:
        print(f"Engineering loop: {plan.task}")
        print(f"Iterations: {plan.iterations} (max {MAX_ITERATIONS})")
        print("Stages: " + " → ".join(plan.stages))
        print("Skills: " + ", ".join(plan.skills))
        print("Approval gate: " + ("required before edits" if plan.approval_required else "accepted; verify every iteration"))
    return 0

