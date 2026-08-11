"""Run independent Arka skill commands or sub-agents concurrently."""
from __future__ import annotations

import argparse
import contextlib
import io
import json
import sys
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


def _cmd_plan(args: argparse.Namespace) -> int:
    from arka.agent.parallel_plan import decompose_parallel, format_plan

    goal = " ".join(args.goal).strip()
    if not goal:
        print("Usage: arka parallel plan <goal>", file=sys.stderr)
        return 2
    plan = decompose_parallel(goal)
    if args.json:
        print(json.dumps(plan.to_dict(), indent=2))
    else:
        print(format_plan(plan))
    return 0


def _cmd_run(args: argparse.Namespace) -> int:
    from arka.agent.parallel_plan import decompose_parallel, format_plan, run_parallel_subagents

    goal = " ".join(args.goal).strip()
    if not goal:
        print("Usage: arka parallel run <goal>", file=sys.stderr)
        return 2
    plan = decompose_parallel(goal)
    if args.print_plan:
        print(format_plan(plan))
        print()
    if not plan.tasks:
        print("No tasks to run.", file=sys.stderr)
        return 1
    record = run_parallel_subagents(plan, sync=args.sync, plan_id=args.plan_id or None)
    if args.json:
        print(json.dumps(record, indent=2))
    else:
        print(f"Parallel run {record['plan_id']} ({record['mode']})")
        for row in record.get("agents", []):
            agent_id = row.get("agent_id", "?")
            status = row.get("status", row.get("error", "unknown"))
            print(f"  [{row.get('task_id')}] agent={agent_id} status={status} rule={row.get('rule')}")
    failed = [
        row for row in record.get("agents", [])
        if row.get("error") or row.get("exit_code") not in (None, 0) or row.get("status") == "failed"
    ]
    return 1 if failed else 0


def _cmd_status(args: argparse.Namespace) -> int:
    from arka.agent.parallel_plan import load_run

    plan_id = str(args.plan_id).strip()
    record = load_run(plan_id)
    if not record:
        print(f"No parallel run {plan_id!r}.", file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(record, indent=2))
    else:
        print(f"Parallel run {record.get('plan_id')} ({record.get('mode')})")
        for row in record.get("agents", []):
            print(
                f"  [{row.get('task_id')}] agent={row.get('agent_id')} "
                f"status={row.get('status')} goal={row.get('goal')}"
            )
    return 0


def _cmd_exec(args: argparse.Namespace) -> int:
    results = run_jobs(args.job, args.workers)
    for result in results:
        print(f"--- {result['job']} (exit {result['exit_code']}) ---")
        if result["output"]:
            print(result["output"], end="" if str(result["output"]).endswith("\n") else "\n")
    return 0 if all(result["exit_code"] == 0 for result in results) else 1


def main(argv: list[str] | None = None) -> int:
    if argv and argv[0] not in {"plan", "run", "status", "exec", "-h", "--help"} and any(
        item.startswith("--job") for item in argv
    ):
        parser = argparse.ArgumentParser(prog="arka parallel")
        parser.add_argument("--job", action="append", required=True, help="Independent skill command")
        parser.add_argument("--workers", type=int, default=3)
        args = parser.parse_args(argv)
        return _cmd_exec(args)

    parser = argparse.ArgumentParser(prog="arka parallel")
    sub = parser.add_subparsers(dest="cmd")

    p_plan = sub.add_parser("plan", help="symbolically decompose a goal into parallel subtasks")
    p_plan.add_argument("goal", nargs="+")
    p_plan.add_argument("--json", action="store_true")

    p_run = sub.add_parser("run", help="decompose a goal and spawn sub-agents")
    p_run.add_argument("goal", nargs="+")
    p_run.add_argument("--sync", action="store_true", help="Wait for each sub-agent to finish")
    p_run.add_argument("--print-plan", action="store_true", dest="print_plan")
    p_run.add_argument("--plan-id", default="")
    p_run.add_argument("--json", action="store_true")

    p_status = sub.add_parser("status", help="show a prior parallel run record")
    p_status.add_argument("plan_id")
    p_status.add_argument("--json", action="store_true")

    p_exec = sub.add_parser("exec", help="run independent skill commands concurrently")
    p_exec.add_argument("--job", action="append", required=True)
    p_exec.add_argument("--workers", type=int, default=3)

    args = parser.parse_args(argv)
    if args.cmd == "plan":
        return _cmd_plan(args)
    if args.cmd == "run":
        return _cmd_run(args)
    if args.cmd == "status":
        return _cmd_status(args)
    if args.cmd == "exec":
        return _cmd_exec(args)
    parser.print_help()
    return 1
