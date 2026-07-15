"""Agentic race: parallel contestants followed by an independent judge."""
from __future__ import annotations

import argparse
import json
from concurrent.futures import ThreadPoolExecutor, as_completed


def _parse_model(spec: str) -> tuple[str, str] | None:
    if "/" not in spec:
        return None
    provider, model = spec.split("/", 1)
    return provider.strip(), model.strip()


def contestant(task: str, spec: str) -> dict[str, str]:
    try:
        from arka.llm.cli import llm_complete

        chain = [_parse_model(spec)] if _parse_model(spec) else None
        text = llm_complete("Solve the task rigorously. Return a concrete, testable result.", task, temperature=0.35, task="agent", skill="race", skip_security=False) if chain is None else __import__("arka.llm.fallback", fromlist=["llm_complete"]).llm_complete("Solve the task rigorously. Return a concrete, testable result.", task, temperature=0.35, task="agent", skill="race", chain=chain)
        return {"model": spec, "status": "ok", "answer": text.strip()}
    except Exception as exc:
        return {"model": spec, "status": "error", "answer": str(exc)[:500]}


def judge(task: str, answers: list[dict[str, str]], judge_spec: str = "") -> dict[str, object]:
    evidence = "\n\n".join(f"CONTESTANT {i} ({row['model']}):\n{row['answer']}" for i, row in enumerate(answers, 1))
    prompt = f"Task:\n{task}\n\n{evidence}\n\nRank the contestants for correctness, completeness, testability, and safety. Return JSON with winner (contestant number), scores (object keyed by contestant number, 0-10), rationale, and recommended_answer. Do not invent evidence."
    try:
        from arka.llm.fallback import llm_complete
        chain = [_parse_model(judge_spec)] if _parse_model(judge_spec) else None
        raw = llm_complete("You are an impartial judge. Output valid JSON only.", prompt, temperature=0.1, task="agent", skill="race_judge", chain=chain)
        return json.loads(raw)
    except Exception as exc:
        return {"winner": None, "scores": {}, "rationale": f"Judge unavailable: {exc}", "recommended_answer": ""}


def run(task: str, models: list[str], judge_model: str = "") -> dict[str, object]:
    results: list[dict[str, str]] = []
    with ThreadPoolExecutor(max_workers=max(1, min(len(models), 8))) as pool:
        futures = [pool.submit(contestant, task, model) for model in models]
        for future in as_completed(futures):
            results.append(future.result())
    results.sort(key=lambda row: row["model"])
    return {"task": task, "contestants": results, "judge": judge(task, results, judge_model)}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka race")
    parser.add_argument("task", nargs="+")
    parser.add_argument("--models", required=True, help="comma-separated provider/model contestants")
    parser.add_argument("--judge", default="", help="provider/model used for judging")
    parser.add_argument("--json", action="store_true")
    args = parser.parse_args(argv)
    result = run(" ".join(args.task), [x.strip() for x in args.models.split(",") if x.strip()], args.judge)
    print(json.dumps(result, indent=2) if args.json else f"winner: {result['judge'].get('winner')}\n{result['judge'].get('rationale', '')}")
    return 0 if result["contestants"] else 1
