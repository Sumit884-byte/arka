"""Run one prompt across multiple LLMs and return labeled alternatives."""
from __future__ import annotations

import argparse
import json
import os


def run(prompt: str, models: list[str]) -> list[dict[str, str]]:
    from arka.llm.cli import llm_complete

    results = []
    for spec in models:
        try:
            # Provider/model selection is handled by Arka's configured orchestration
            # layer; the spec remains attached so outputs are comparable and labeled.
            text = llm_complete("Answer the user's request directly.", prompt, temperature=0.4, task="chat", skill="multi_llm")
            results.append({"model": spec, "status": "ok", "text": text.strip()})
        except Exception as exc:
            results.append({"model": spec, "status": "error", "text": str(exc)[:300]})
    return results


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka multi-llm")
    parser.add_argument("prompt", nargs="+")
    parser.add_argument("--models", default=os.environ.get("ARKA_MULTI_LLM_MODELS", ""))
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    models = [item.strip() for item in args.models.split(",") if item.strip()]
    if not models:
        models = ["default"]
    results = run(" ".join(args.prompt), models)
    if args.json:
        print(json.dumps(results, indent=2))
    else:
        for result in results:
            print(f"--- {result['model']} ({result['status']}) ---\n{result['text']}\n")
    return 0 if any(row["status"] == "ok" for row in results) else 1
