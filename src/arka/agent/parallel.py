"""Run independent Arka skill commands concurrently."""
from __future__ import annotations

import argparse
import contextlib
import io
from concurrent.futures import ThreadPoolExecutor, as_completed


def run_jobs(jobs: list[str], workers: int = 3) -> list[dict[str, object]]:
    from arka.dispatch import run_skill

    def one(job: str) -> dict[str, object]:
        output = io.StringIO()
        try:
            with contextlib.redirect_stdout(output), contextlib.redirect_stderr(output):
                code = run_skill(job)
            return {"job": job, "exit_code": code, "output": output.getvalue()}
        except Exception as exc:
            return {"job": job, "exit_code": 1, "output": str(exc)}

    results: list[dict[str, object]] = []
    with ThreadPoolExecutor(max_workers=max(1, min(workers, len(jobs)))) as pool:
        futures = [pool.submit(one, job) for job in jobs]
        for future in as_completed(futures):
            results.append(future.result())
    return sorted(results, key=lambda item: jobs.index(str(item["job"])))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka parallel")
    parser.add_argument("--job", action="append", required=True, help="Independent skill command; repeat for more jobs")
    parser.add_argument("--workers", type=int, default=3)
    args = parser.parse_args(argv)
    results = run_jobs(args.job, args.workers)
    for result in results:
        print(f"--- {result['job']} (exit {result['exit_code']}) ---")
        if result["output"]:
            print(result["output"], end="" if str(result["output"]).endswith("\n") else "\n")
    return 0 if all(result["exit_code"] == 0 for result in results) else 1
