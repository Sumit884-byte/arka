"""Deterministic coding workflows that make Arka skill use explicit."""
from __future__ import annotations
import argparse
from dataclasses import dataclass
from pathlib import Path

@dataclass(frozen=True)
class Workflow:
    name: str
    steps: tuple[str, ...]

WORKFLOWS = {
    "feature": Workflow("feature", ("repo_context", "plan", "write code", "lint_project", "ci", "review")),
    "bugfix": Workflow("bugfix", ("repo_health", "reproduce", "write minimal fix", "tests", "ci", "review")),
    "frontend": Workflow("frontend", ("design_memory", "design_from_screenshot", "frontend_loop", "ci", "review")),
    "api": Workflow("api", ("repo_context", "urlkit", "write API integration", "lint_project", "ci", "review")),
}


def discover_skills() -> tuple[str, ...]:
    root = Path(__file__).resolve().parent
    return tuple(sorted(path.stem for path in root.glob("*.py") if not path.stem.startswith("_") and path.stem not in {"__init__", "coding_workflows"}))


def exhaustive_workflow() -> Workflow:
    skills = discover_skills()
    verify = ("lint_project", "ci", "review", "repo_health")
    steps = tuple(f"{skill} (inspect/plan only)" for skill in skills if skill not in verify) + verify
    return Workflow("exhaustive", steps)

def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="arka coding-workflow")
    p.add_argument("workflow", choices=sorted((*WORKFLOWS, "exhaustive")))
    p.add_argument("--run", action="store_true")
    p.add_argument("--task", default="")
    a = p.parse_args(argv)
    flow = exhaustive_workflow() if a.workflow == "exhaustive" else WORKFLOWS[a.workflow]
    print(f"workflow\t{flow.name}\ntask\t{a.task or '(not specified)'}")
    for index, step in enumerate(flow.steps, 1):
        print(f"step_{index}\t{step}")
    if not a.run:
        print("preview\tpass --run to execute; review each generated change")
        return 0
    print("execution\tUse the listed Arka skills explicitly in order; automatic code edits remain approval-gated.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
