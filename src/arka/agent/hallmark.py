"""Optional adapter for Nutlope's Hallmark design skill."""
from __future__ import annotations

import argparse
import json
from pathlib import Path

HALLMARK_URL = "https://github.com/Nutlope/hallmark"


def build_request(action: str, target: str) -> dict[str, str]:
    if action not in {"build", "audit", "redesign", "study"}:
        raise ValueError("action must be build, audit, redesign, or study")
    if not target.strip():
        raise ValueError("a target or brief is required")
    return {
        "skill": "hallmark",
        "action": action,
        "target": target.strip(),
        "prompt": f"Use Hallmark's anti-AI-slop design process to {action} {target.strip()}. Preserve user intent and content; run the visual quality gates before returning output.",
        "source": HALLMARK_URL,
        "license": "MIT",
    }


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka hallmark")
    parser.add_argument("action", choices=("build", "audit", "redesign", "study"))
    parser.add_argument("target", nargs="+")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    request = build_request(args.action, " ".join(args.target))
    installed = any((Path.home() / path / "hallmark" / "SKILL.md").exists() for path in (".codex/skills", ".claude/skills"))
    request["installed"] = str(installed).lower()
    if args.as_json:
        print(json.dumps(request, indent=2))
    else:
        print(f"Hallmark {args.action}: {request['target']}")
        print("Installed: " + ("yes" if installed else "no (run: npx skills add nutlope/hallmark)"))
        print(request["prompt"])
    return 0
