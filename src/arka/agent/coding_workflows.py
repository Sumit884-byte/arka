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


def build_workflow_goal(flow: Workflow, task: str) -> str:
    lines = [
        f"Execute the Arka '{flow.name}' coding workflow.",
        f"Task: {task or '(infer from repo context and diff)'}",
        "",
        "Run these skills/steps in order. Inspect/plan before edits; verify with ci + review at the end:",
    ]
    for index, step in enumerate(flow.steps, 1):
        lines.append(f"{index}. {step}")
    lines.append("")
    lines.append(
        "Use existing Arka skills (repo_context, ci, review, repo_health, lint_project) explicitly. "
        "Keep edits minimal and scoped to the code project."
    )
    return "\n".join(lines)


def execute_workflow(flow: Workflow, task: str) -> int:
    goal = build_workflow_goal(flow, task)
    try:
        from arka.agent.goal import run_goal

        return int(
            run_goal(
                goal,
                max_steps=24,
                auto_yes=False,
                auto_continue=True,
            )
            or 0
        )
    except ImportError as exc:
        print(f"goal agent unavailable: {exc}", file=__import__("sys").stderr)
        return 1


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
        print("preview\tpass --run to execute via goal agent (approval-gated edits)")
        return 0
    print("execution\tstarting goal agent for workflow steps")
    return execute_workflow(flow, a.task)


if __name__ == "__main__":
    raise SystemExit(main())
