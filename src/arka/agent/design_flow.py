"""Design-first workflow: draft, review, approve, then build."""
from __future__ import annotations
import argparse
import json
from pathlib import Path
from arka.paths import cache_dir

def _path() -> Path: return cache_dir() / "design-draft.json"
def draft(goal: str, feedback: str = "") -> dict:
    steps = ["Clarify users, constraints, and success criteria", "Choose architecture and interfaces", "Define implementation milestones", "Specify verification and rollback"]
    if feedback:
        steps.insert(0, f"Address requested redo feedback: {feedback}")
    return {"goal": goal, "feedback": feedback, "steps": steps, "status": "pending"}
def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(description="Design, approve, and build in separate steps")
    sub = p.add_subparsers(dest="cmd", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("goal")
    sub.add_parser("show")
    sub.add_parser("accept")
    redo = sub.add_parser("redo")
    redo.add_argument("feedback")
    build = sub.add_parser("build")
    build.add_argument("--yes", action="store_true")
    args = p.parse_args(argv)
    if args.cmd == "plan":
        data = draft(args.goal)
        _path().parent.mkdir(parents=True, exist_ok=True)
        _path().write_text(json.dumps(data, indent=2))
        print(json.dumps(data, indent=2))
        return 0
    if not _path().is_file():
        p.error("no draft exists; run design plan first")
    data = json.loads(_path().read_text())
    if args.cmd == "show":
        print(json.dumps(data, indent=2))
        return 0
    if args.cmd == "redo":
        data = draft(data["goal"], args.feedback)
        _path().write_text(json.dumps(data, indent=2))
        print(json.dumps(data, indent=2))
        return 0
    if args.cmd == "accept":
        data["status"] = "accepted"
        _path().write_text(json.dumps(data, indent=2))
        print("Design accepted. Run `arka design build --yes` to implement.")
        return 0
    if data.get("status") != "accepted" and not args.yes:
        p.error("design is not accepted; run design accept first")
    from arka.agent.core import code_agent
    return code_agent(data["goal"])
