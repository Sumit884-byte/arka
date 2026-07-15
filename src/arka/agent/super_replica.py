"""Repository-pattern advisor with stage-aware, question-first guidance."""
from __future__ import annotations

import argparse
import json
from pathlib import Path


def analyze(root: str = ".", stage: str = "startup") -> dict[str, object]:
    base = Path(root).expanduser().resolve()
    files = [p for p in base.rglob("*") if p.is_file() and not any(part in {".git", "node_modules", ".venv", "dist", "build"} for part in p.parts)]
    names = {p.name for p in files}
    frontend = any(p.suffix in {".tsx", ".jsx", ".vue", ".svelte", ".css"} for p in files)
    backend = any(p.name in {"manage.py", "Cargo.toml", "go.mod", "Dockerfile"} or p.suffix in {".py", ".go", ".rs"} for p in files)
    stack = []
    if "package.json" in names:
        stack.append("Node/JavaScript")
    if "pyproject.toml" in names or "requirements.txt" in names:
        stack.append("Python")
    if "Cargo.toml" in names:
        stack.append("Rust")
    questions = []
    if not stack:
        questions.append("Which frontend and backend stack do you want to use?")
    if not frontend and not backend:
        questions.append("Is this repository intended to be a frontend, backend, or full-stack app?")
    if stage == "startup":
        advice = "Prioritize a clear user journey, fast iteration, basic error handling, and simple deployment; defer complex scalability work until usage requires it."
    else:
        advice = "Prioritize observability, performance budgets, reliable deployments, and explicit scaling boundaries based on measured usage."
    return {"root": str(base), "stack": stack, "frontend_detected": frontend, "backend_detected": backend, "stage": stage, "questions": questions, "advice": advice}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka super-replica")
    parser.add_argument("path", nargs="?", default=".")
    parser.add_argument("--stage", choices=["startup", "growth", "scale"], default="startup")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = analyze(args.path, args.stage)
    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(f"Stack: {', '.join(result['stack']) or 'unspecified'}")
        print(f"Advice: {result['advice']}")
        for question in result["questions"]:
            print(f"Question: {question}")
    return 0
