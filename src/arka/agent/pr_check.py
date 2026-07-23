#!/usr/bin/env python3
"""PR diff, CI status, failure explain, and babysit loop — local git + GitHub CLI."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import time
from pathlib import Path

try:
    from arka.paths import load_env_file

    load_env_file()
except ImportError:

    def load_env_file() -> None:
        pass

from arka.env import env_int

MAX_DIFF_CHARS = env_int("PR_CHECK_MAX_DIFF", 14000)
MAX_LOG_CHARS = env_int("PR_CHECK_MAX_LOG", 9000)
BABYSIT_POLL_SEC = env_int("PR_CHECK_POLL_SEC", 20)


def _run(
    cmd: list[str],
    *,
    cwd: Path | None = None,
    timeout: int = 120,
) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            cwd=str(cwd) if cwd else None,
            capture_output=True,
            text=True,
            timeout=timeout,
            env=os.environ.copy(),
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", f"Command timed out after {timeout}s"
    except OSError as exc:
        return 1, "", str(exc)


def _which(name: str) -> str | None:
    from shutil import which

    return which(name)


def git_root() -> Path | None:
    code, out, _ = _run(["git", "rev-parse", "--show-toplevel"])
    if code != 0:
        return None
    root = Path(out.strip())
    return root if root.is_dir() else None


def gh_available() -> bool:
    if not _which("gh"):
        return False
    code, _, _ = _run(["gh", "auth", "status"])
    return code == 0


def current_branch(root: Path) -> str:
    _, out, _ = _run(["git", "branch", "--show-current"], cwd=root)
    return out.strip() or "HEAD"


def detect_base(root: Path, explicit: str | None = None) -> str:
    if explicit:
        return explicit.strip()
    for candidate in ("main", "master", "develop"):
        code, _, _ = _run(["git", "rev-parse", "--verify", candidate], cwd=root)
        if code == 0:
            return candidate
    code, out, _ = _run(
        ["git", "rev-parse", "--abbrev-ref", "origin/HEAD"],
        cwd=root,
    )
    if code == 0 and out.strip().startswith("origin/"):
        return out.strip().split("/", 1)[1]
    return "main"


def merge_base(root: Path, base: str) -> str | None:
    code, out, _ = _run(["git", "merge-base", base, "HEAD"], cwd=root)
    if code != 0:
        return None
    return out.strip() or None


def collect_diff(root: Path, base: str, *, stat_only: bool = False) -> tuple[str, list[str]]:
    mb = merge_base(root, base)
    if not mb:
        return f"Could not find merge-base with {base}.", []
    diff_cmd = ["git", "diff", "--stat", mb, "HEAD"]
    if stat_only:
        code, out, err = _run(diff_cmd, cwd=root)
        text = out if code == 0 else err
        _, names_out, _ = _run(["git", "diff", "--name-only", mb, "HEAD"], cwd=root)
        files = [ln.strip() for ln in names_out.splitlines() if ln.strip()]
        return text.strip(), files
    code, out, err = _run(["git", "diff", mb, "HEAD"], cwd=root)
    text = out if code == 0 else err
    _, names_out, _ = _run(["git", "diff", "--name-only", mb, "HEAD"], cwd=root)
    files = [ln.strip() for ln in names_out.splitlines() if ln.strip()]
    if len(text) > MAX_DIFF_CHARS:
        text = text[:MAX_DIFF_CHARS] + f"\n\n… truncated ({len(text) - MAX_DIFF_CHARS} chars omitted)"
    return text.strip(), files


def resolve_pr(root: Path, pr: int | None) -> dict | None:
    if not gh_available():
        return None
    fields = "number,title,state,url,headRefName,baseRefName,isDraft"
    if pr is not None:
        code, out, err = _run(
            ["gh", "pr", "view", str(pr), "--json", fields],
            cwd=root,
        )
    else:
        code, out, err = _run(["gh", "pr", "view", "--json", fields], cwd=root)
    if code != 0:
        if err.strip():
            print(err.strip(), file=sys.stderr)
        return None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def list_runs(root: Path, *, branch: str, limit: int = 5) -> list[dict]:
    if not gh_available():
        return []
    code, out, _ = _run(
        [
            "gh",
            "run",
            "list",
            "--branch",
            branch,
            "--limit",
            str(limit),
            "--json",
            "databaseId,conclusion,status,displayTitle,workflowName,url,event",
        ],
        cwd=root,
    )
    if code != 0:
        return []
    try:
        rows = json.loads(out)
    except json.JSONDecodeError:
        return []
    return rows if isinstance(rows, list) else []


def failed_run_logs(root: Path, run_id: int | None = None, *, branch: str) -> tuple[str, dict | None]:
    run: dict | None = None
    if run_id is not None:
        runs = list_runs(root, branch=branch, limit=10)
        run = next((r for r in runs if r.get("databaseId") == run_id), None)
    if run is None:
        runs = list_runs(root, branch=branch, limit=8)
        run = next(
            (r for r in runs if r.get("conclusion") == "failure" or r.get("status") == "completed"
             and r.get("conclusion") not in ("success", "skipped", None)),
            runs[0] if runs else None,
        )
    if run is None:
        return "", None
    rid = run.get("databaseId")
    if not rid:
        return "", run
    code, out, err = _run(["gh", "run", "view", str(rid), "--log-failed"], cwd=root, timeout=180)
    logs = out if code == 0 else err
    if len(logs) > MAX_LOG_CHARS:
        logs = logs[-MAX_LOG_CHARS:]
        logs = f"… (log truncated)\n{logs}"
    return logs.strip(), run


def pr_checks(root: Path, pr: int | None = None) -> list[dict]:
    if not gh_available():
        return []
    cmd = ["gh", "pr", "checks"]
    if pr is not None:
        cmd.append(str(pr))
    code, out, err = _run(cmd, cwd=root)
    if code != 0 and not out.strip():
        return []
    rows: list[dict] = []
    for line in out.splitlines():
        parts = line.split("\t")
        if len(parts) >= 2:
            rows.append({"name": parts[0].strip(), "status": parts[1].strip(), "url": parts[2].strip() if len(parts) > 2 else ""})
        elif line.strip():
            m = re.match(r"(\S+)\s+(pass|fail|pending|skipping|cancel)", line, re.I)
            if m:
                rows.append({"name": m.group(1), "status": m.group(2), "url": ""})
    return rows


def cmd_diff(base: str | None, *, stat_only: bool) -> int:
    root = git_root()
    if not root:
        print("Not inside a git repository.", file=sys.stderr)
        return 1
    base_ref = detect_base(root, base)
    mb = merge_base(root, base_ref)
    branch = current_branch(root)
    print(f"Branch: {branch}  vs  {base_ref}" + (f"  (merge-base {mb[:8]})" if mb else ""))
    print()
    diff, files = collect_diff(root, base_ref, stat_only=stat_only)
    if not diff and not files:
        print("No changes vs base.")
        return 0
    print(diff)
    if files:
        print()
        print(f"Files changed ({len(files)}): " + ", ".join(files[:12]) + ("…" if len(files) > 12 else ""))
    return 0


def _llm_summary(diff_stat: str, files: list[str], base: str, branch: str) -> str:
    try:
        from arka.llm.cli import llm_complete
    except ImportError:
        return ""
    system = (
        "Summarize a git diff for a pull request. Plain terminal text only — no markdown headers. "
        "Cover: what changed, risk areas, and a short test plan (3 bullets max)."
    )
    user = (
        f"Branch: {branch} vs {base}\n"
        f"Files: {', '.join(files[:40])}\n\n"
        f"Diff stat / excerpt:\n{diff_stat[:8000]}"
    )
    return llm_complete(system, user, temperature=0.2, task="default").strip()


def cmd_summary(base: str | None) -> int:
    root = git_root()
    if not root:
        print("Not inside a git repository.", file=sys.stderr)
        return 1
    base_ref = detect_base(root, base)
    branch = current_branch(root)
    stat, files = collect_diff(root, base_ref, stat_only=True)
    if not files:
        print("No changes vs base — nothing to summarize.")
        return 0
    print(f"Summarizing {len(files)} file(s) vs {base_ref}…", file=sys.stderr)
    summary = _llm_summary(stat, files, base_ref, branch)
    if not summary:
        print(stat)
        return 0
    print(summary)
    return 0


def _print_ci_status(root: Path, *, branch: str, pr_data: dict | None) -> tuple[bool, bool]:
    """Return (all_green, any_failed)."""
    if pr_data:
        print(f"PR #{pr_data.get('number')}: {pr_data.get('title')}")
        print(f"  {pr_data.get('url', '')}")
        print(f"  {pr_data.get('headRefName')} → {pr_data.get('baseRefName')}  ({pr_data.get('state')})")
        print()

    checks = pr_checks(root)
    any_failed = False
    any_pending = False
    if checks:
        print("Checks:")
        for row in checks:
            status = row["status"].lower()
            mark = "✓" if status in ("pass", "success") else "✗" if status in ("fail", "failure") else "…"
            if status in ("fail", "failure"):
                any_failed = True
            if status in ("pending", "in_progress", "queued"):
                any_pending = True
            print(f"  {mark} {row['name']:<28} {row['status']}")
        print()

    runs = list_runs(root, branch=branch, limit=5)
    if runs:
        print("Recent workflow runs:")
        for run in runs:
            conclusion = run.get("conclusion") or run.get("status") or "?"
            mark = "✓" if conclusion == "success" else "✗" if conclusion == "failure" else "…"
            if conclusion == "failure":
                any_failed = True
            if run.get("status") in ("in_progress", "queued", "pending"):
                any_pending = True
            print(
                f"  {mark} {run.get('workflowName', '?')[:32]:<32} "
                f"{conclusion:<10} {run.get('url', '')}"
            )
        print()

    all_green = not any_failed and not any_pending and bool(checks or runs)
    if all_green and (checks or runs):
        print("All checks passed.")
    elif any_failed:
        print("Some checks failed — run: pr_check explain")
    elif any_pending:
        print("Checks still running…")
    return all_green, any_failed


def cmd_ci(*, pr: int | None) -> int:
    root = git_root()
    if not root:
        print("Not inside a git repository.", file=sys.stderr)
        return 1
    if not gh_available():
        print("GitHub CLI not available or not logged in. Run: gh auth login", file=sys.stderr)
        return 1
    branch = current_branch(root)
    pr_data = resolve_pr(root, pr)
    _print_ci_status(root, branch=branch, pr_data=pr_data)
    return 0


def _llm_explain(logs: str, diff_stat: str, files: list[str], run: dict | None) -> str:
    try:
        from arka.llm.cli import llm_complete
    except ImportError:
        return logs[:2000] if logs else "Install arka LLM deps for explanation."
    title = (run or {}).get("displayTitle") or "CI run"
    workflow = (run or {}).get("workflowName") or "workflow"
    system = (
        "You diagnose CI / GitHub Actions failures from logs and a diff summary. "
        "Plain terminal text: no markdown. Structure:\n"
        "1. One-line summary of what failed\n"
        "2. Likely cause (tie to changed files when possible)\n"
        "3. Concrete fix steps (numbered, max 5)\n"
        "Do not suggest editing workflow YAML unless the failure is clearly a workflow misconfiguration."
    )
    user = (
        f"Workflow: {workflow}\nRun: {title}\n"
        f"Changed files: {', '.join(files[:30])}\n\n"
        f"Diff stat:\n{diff_stat[:4000]}\n\n"
        f"Failed log excerpt:\n{logs[:7000]}"
    )
    return llm_complete(system, user, temperature=0.15, task="default").strip()


def cmd_explain(*, base: str | None, pr: int | None, run_id: int | None) -> int:
    root = git_root()
    if not root:
        print("Not inside a git repository.", file=sys.stderr)
        return 1
    if not gh_available():
        print("GitHub CLI not available or not logged in. Run: gh auth login", file=sys.stderr)
        return 1
    base_ref = detect_base(root, base)
    branch = current_branch(root)
    stat, files = collect_diff(root, base_ref, stat_only=True)
    logs, run = failed_run_logs(root, run_id, branch=branch)
    if not logs:
        print("No failed workflow logs found for this branch.", file=sys.stderr)
        _, any_failed = _print_ci_status(root, branch=branch, pr_data=resolve_pr(root, pr))
        return 1 if any_failed else 0
    if run:
        print(f"Explaining failed run: {run.get('workflowName')} — {run.get('displayTitle')}", file=sys.stderr)
    explanation = _llm_explain(logs, stat, files, run)
    print(explanation)
    return 0


def _dispatch_agent_code(goal: str) -> int:
    try:
        from arka.fish_bridge import delegate_to_fish

        code = delegate_to_fish(["agent_code", goal])
        return int(code or 0)
    except ImportError:
        print(f"→ agent_code {shlex.quote(goal)}", file=sys.stderr)
        return 0


def cmd_babysit(
    *,
    base: str | None,
    pr: int | None,
    max_rounds: int,
    fix: bool,
    wait: bool,
) -> int:
    root = git_root()
    if not root:
        print("Not inside a git repository.", file=sys.stderr)
        return 1
    if not gh_available():
        print("GitHub CLI not available or not logged in. Run: gh auth login", file=sys.stderr)
        return 1

    base_ref = detect_base(root, base)
    branch = current_branch(root)
    print(f"PR babysit — {branch} vs {base_ref} (max {max_rounds} rounds)", file=sys.stderr)

    for round_num in range(1, max_rounds + 1):
        print(f"\n── Round {round_num}/{max_rounds} ──", file=sys.stderr)
        stat, files = collect_diff(root, base_ref, stat_only=True)
        if files:
            print(f"  {len(files)} file(s) changed vs {base_ref}", file=sys.stderr)

        pr_data = resolve_pr(root, pr)
        all_green, any_failed = _print_ci_status(root, branch=branch, pr_data=pr_data)

        if all_green:
            print("\n✓ PR looks merge-ready (checks green).", file=sys.stderr)
            return 0

        if any_failed:
            logs, run = failed_run_logs(root, None, branch=branch)
            explanation = _llm_explain(logs, stat, files, run) if logs else ""
            if explanation:
                print()
                print(explanation)
            if fix and explanation:
                goal = (
                    f"Fix the CI failure for branch {branch}. "
                    f"Only change files related to this PR scope.\n\n{explanation}"
                )
                print("\n→ Running agent_code to apply fix…", file=sys.stderr)
                rc = _dispatch_agent_code(goal)
                if rc != 0:
                    return rc
                print("→ Fix applied — re-check CI on next round.", file=sys.stderr)
            else:
                print("\nRun with --fix to attempt agent_code repair, or fix manually.", file=sys.stderr)
                return 1

        if wait and round_num < max_rounds:
            print(f"Waiting {BABYSIT_POLL_SEC}s for checks…", file=sys.stderr)
            time.sleep(BABYSIT_POLL_SEC)
        elif not any_failed:
            print("Checks pending — re-run babysit when workflows finish.", file=sys.stderr)
            return 2

    print("Max rounds reached — PR not merge-ready yet.", file=sys.stderr)
    return 1


def route_command(text: str) -> str:
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if not raw:
        return ""
    low = raw.lower()

    if re.search(r"\b(?:fix|resolve)\b.*\b(?:github|gh)\b.*\bissues?\b.*\b(?:code|repo|repository)\b", low):
        return "agent_code inspect open GitHub issues, reproduce the relevant problems, implement fixes, and run focused tests"

    if re.search(r"(?i)\b(pr_check|pr check)\b", low):
        rest = re.sub(r"(?i)^(?:arka\s+)?(?:pr_check|pr check)\s*", "", raw).strip()
        return f"pr_check {rest}".strip() if rest else "pr_check ci"

    if re.search(r"(?i)\b(babysit|baby.?sit)\b.*\b(pr|pull request)\b", low) or re.search(
        r"(?i)\b(pr|pull request)\b.*\b(babysit|merge.?ready|merge ready)\b", low
    ):
        return "pr_check babysit"

    if re.search(
        r"(?i)\b(why did ci fail|why did (the )?ci fail|explain (the )?ci|ci failed|"
        r"github actions failed|workflow failed|fix ci|failed checks)\b",
        low,
    ):
        return "pr_check explain"

    if re.search(r"(?i)\b(pr diff|diff vs main|diff against main|what changed vs|my changes vs)\b", low):
        return "pr_check diff"

    if re.search(r"(?i)\b(pr checks|ci status|github actions status|check(s)? status)\b", low):
        return "pr_check ci"

    if re.search(
        r"(?i)\b(summarize (my )?(pr|changes|diff)|pr summary|summary of (my )?changes)\b",
        low,
    ):
        return "pr_check summary"

    return ""


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    parser = argparse.ArgumentParser(
        description="PR diff, CI status, failure explain, babysit until merge-ready",
    )
    sub = parser.add_subparsers(dest="cmd")

    p_diff = sub.add_parser("diff", help="Show diff vs base branch")
    p_diff.add_argument("--base", "-b", default="", help="Base branch (default: main/master)")
    p_diff.add_argument("--stat", action="store_true", help="Stat only")

    p_sum = sub.add_parser("summary", help="LLM summary of changes vs base")
    p_sum.add_argument("--base", "-b", default="")

    p_ci = sub.add_parser("ci", help="PR / workflow check status")
    p_ci.add_argument("--pr", type=int, default=None)

    p_ex = sub.add_parser("explain", help="Explain latest failed CI run")
    p_ex.add_argument("--base", "-b", default="")
    p_ex.add_argument("--pr", type=int, default=None)
    p_ex.add_argument("--run", type=int, default=None, dest="run_id")

    p_bb = sub.add_parser("babysit", help="Check diff + CI; optionally fix failures")
    p_bb.add_argument("--base", "-b", default="")
    p_bb.add_argument("--pr", type=int, default=None)
    p_bb.add_argument("--max-rounds", type=int, default=3)
    p_bb.add_argument("--fix", action="store_true", help="Run agent_code on CI failure")
    p_bb.add_argument("--wait", action="store_true", help="Poll between rounds")

    p_route = sub.add_parser("route")
    p_route.add_argument("text", nargs="+")

    args = parser.parse_args(argv)
    if args.cmd == "diff":
        return cmd_diff(args.base or None, stat_only=args.stat)
    if args.cmd == "summary":
        return cmd_summary(args.base or None)
    if args.cmd == "ci":
        return cmd_ci(pr=args.pr)
    if args.cmd == "explain":
        return cmd_explain(base=args.base or None, pr=args.pr, run_id=args.run_id)
    if args.cmd == "babysit":
        return cmd_babysit(
            base=args.base or None,
            pr=args.pr,
            max_rounds=max(1, args.max_rounds),
            fix=args.fix,
            wait=args.wait,
        )
    if args.cmd == "route":
        line = route_command(" ".join(args.text))
        if line:
            print(line)
            return 0
        return 1
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
