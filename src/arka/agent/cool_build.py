"""Guarded ideate → plan → build → test → approve → deploy workflow."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def plan(idea: str) -> dict[str, object]:
    return {"idea": idea, "steps": ["research open-source patterns", "write a small implementation plan", "build a minimal vertical slice", "run app-check and focused tests", "review results with the user", "deploy only after explicit approval"]}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka build-something-cool")
    parser.add_argument("idea", nargs="+")
    parser.add_argument("--build", action="store_true")
    parser.add_argument("--deploy", action="store_true")
    parser.add_argument("--yes", action="store_true", help="Explicitly approve deployment")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    brief = plan(" ".join(args.idea))
    if args.json:
        print(json.dumps(brief, indent=2))
    else:
        print("Build-something-cool plan")
        for index, step in enumerate(brief["steps"], 1):
            print(f"{index}. {step}")
    if not args.build:
        print("Plan only. Re-run with --build after reviewing it.")
        return 0
    from arka.agent.app_check import check

    result = check(str(Path.cwd()), run=True)
    print(json.dumps(result, indent=2))
    if not result["ok"]:
        print("Build/test failed; deployment is blocked.")
        return 1
    if args.deploy and not args.yes:
        print("Build passed. Deployment requires explicit approval: add --yes.")
        return 2
    if args.deploy:
        from arka.agent.deploy import main as deploy_main
        return deploy_main(["--yes"])
    print("Build/test passed. Awaiting user approval before deployment.")
    return 0
