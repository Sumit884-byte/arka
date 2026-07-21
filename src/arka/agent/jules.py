#!/usr/bin/env python3
"""Jules-style async coding sessions — assign tasks, track progress, open PRs."""

from __future__ import annotations

import argparse
import contextlib
import io
import json
import os
import re
import shlex
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path
from typing import Any

try:
    from arka.paths import cache_dir, load_env_file

    load_env_file()
except ImportError:

    def cache_dir() -> Path:
        return Path.home() / ".cache" / "fish-agent"

    def load_env_file() -> None:
        pass

DEFAULT_MAX_STEPS = int(os.environ.get("JULES_MAX_STEPS", "20"))
DEFAULT_MAX_CONCURRENT = int(os.environ.get("JULES_MAX", "2"))
RESULT_LIMIT = 4000


def _env(primary: str, legacy: str, default: str = "") -> str:
    val = os.environ.get(primary, "").strip()
    if val:
        return val
    val = os.environ.get(legacy, "").strip()
    if val:
        return val
    return default


def _enabled() -> bool:
    return _env("JULES_ENABLED", "ARKA_JULES", "1").lower() not in ("0", "false", "no", "off")


def jules_root() -> Path:
    if raw := _env("JULES_DIR", "ARKA_JULES_DIR", ""):
        return Path(raw).expanduser()
    return cache_dir() / "jules"


def _max_concurrent() -> int:
    try:
        return max(1, int(_env("JULES_MAX", "ARKA_JULES_MAX", str(DEFAULT_MAX_CONCURRENT))))
    except ValueError:
        return DEFAULT_MAX_CONCURRENT


def _session_path(session_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in session_id)
    return jules_root() / f"{safe}.json"


def _load(session_id: str) -> dict | None:
    path = _session_path(session_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _save(data: dict) -> None:
    root = jules_root()
    root.mkdir(parents=True, exist_ok=True)
    session_id = data.get("id") or uuid.uuid4().hex[:10]
    data["id"] = session_id
    data["updated"] = time.time()
    _session_path(session_id).write_text(json.dumps(data, indent=2), encoding="utf-8")


def _running_count() -> int:
    root = jules_root()
    if not root.is_dir():
        return 0
    count = 0
    for path in root.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("status") == "running":
                count += 1
        except (OSError, json.JSONDecodeError):
            continue
    return count


def _security_gate(task: str) -> tuple[bool, str]:
    task = (task or "").strip()
    if not task:
        return False, "empty task"
    if len(task) > int(_env("JULES_MAX_CHARS", "ARKA_JULES_MAX_CHARS", "8000")):
        return False, "task too long"
    try:
        from arka.core.security import verify_user_prompt

        gate = verify_user_prompt(task)
        if gate.status == "block":
            return False, gate.reason
    except ImportError:
        pass
    return True, ""


def _run(cmd: list[str], *, cwd: Path | None = None, timeout: int = 120) -> tuple[int, str, str]:
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


def _git_root() -> Path | None:
    try:
        from arka.agent.pr_check import git_root

        return git_root()
    except ImportError:
        code, out, _ = _run(["git", "rev-parse", "--show-toplevel"])
        if code != 0:
            return None
        root = Path(out.strip())
        return root if root.is_dir() else None


def _gh_available() -> bool:
    try:
        from arka.agent.pr_check import gh_available

        return gh_available()
    except ImportError:
        from shutil import which

        if not which("gh"):
            return False
        code, _, _ = _run(["gh", "auth", "status"])
        return code == 0


def _resolve_repo(explicit: str | None = None) -> str:
    if explicit and explicit.strip():
        return explicit.strip()
    if _gh_available():
        code, out, _ = _run(["gh", "repo", "view", "--json", "nameWithOwner"])
        if code == 0:
            try:
                data = json.loads(out)
                owner = str(data.get("nameWithOwner") or "").strip()
                if owner:
                    return owner
            except json.JSONDecodeError:
                pass
    root = _git_root()
    if root:
        code, out, _ = _run(["git", "remote", "get-url", "origin"], cwd=root)
        if code == 0:
            match = re.search(r"github\.com[:/](?P<owner>[^/]+)/(?P<repo>[^/.]+)", out.strip())
            if match:
                return f"{match.group('owner')}/{match.group('repo')}"
    return ""


def fetch_issue(issue_number: int, *, repo: str = "") -> dict | None:
    if not _gh_available():
        return None
    repo = repo or _resolve_repo()
    if not repo:
        return None
    fields = "number,title,body,url,state,labels"
    code, out, err = _run(["gh", "issue", "view", str(issue_number), "--repo", repo, "--json", fields])
    if code != 0:
        if err.strip():
            print(err.strip(), file=sys.stderr)
        return None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None
    return data if isinstance(data, dict) else None


def build_issue_goal(issue: dict, *, repo: str = "") -> str:
    labels = issue.get("labels") or []
    label_names = ", ".join(
        str(item.get("name", item) if isinstance(item, dict) else item) for item in labels
    )
    parts = [
        f"Fix GitHub issue #{issue.get('number')} in {repo or _resolve_repo()}.",
        f"Title: {issue.get('title', '')}",
        f"URL: {issue.get('url', '')}",
    ]
    if label_names:
        parts.append(f"Labels: {label_names}")
    body = str(issue.get("body") or "").strip()
    if body:
        parts.append(f"Issue description:\n{body[:6000]}")
    parts.extend(
        [
            "",
            "Instructions:",
            "- Reproduce or understand the issue from the description.",
            "- Implement a minimal, focused fix in the current repo.",
            "- Run relevant tests (pytest or project test command).",
            "- Do not run git commit or git push.",
            "- Stop with status done when tests pass and the fix is complete.",
        ]
    )
    return "\n".join(parts)


def _create_branch(session_id: str, issue_number: int | None = None) -> tuple[str | None, str | None]:
    root = _git_root()
    if not root:
        return None, "not in a git repository"
    if issue_number is not None:
        branch = f"jules/issue-{issue_number}-{session_id[:6]}"
    else:
        branch = f"jules/task-{session_id[:6]}"
    code, _, err = _run(["git", "checkout", "-b", branch], cwd=root)
    if code != 0:
        return None, err.strip() or f"failed to create branch {branch}"
    return branch, None


def _run_goal_captured(goal: str, *, max_steps: int) -> tuple[str, int]:
    buf = io.StringIO()
    try:
        from arka.agent.goal import run_goal

        with contextlib.redirect_stdout(buf), contextlib.redirect_stderr(buf):
            code = run_goal(
                goal,
                max_steps=max_steps,
                auto_yes=True,
                auto_continue=True,
            )
        output = buf.getvalue().strip()
        return output[-RESULT_LIMIT:] or f"Goal finished (exit {code})", int(code or 0)
    except ImportError as exc:
        return f"Goal agent unavailable: {exc}", 1


def _maybe_create_pr(data: dict) -> str:
    if data.get("pr_url"):
        return str(data["pr_url"])
    if not _gh_available():
        return ""
    root = _git_root()
    if not root:
        return ""
    branch = str(data.get("branch") or "").strip()
    if not branch:
        return ""
    title = str(data.get("task") or data.get("goal") or "Jules session")[:120]
    body_parts = [f"Automated fix from Jules session `{data.get('id')}`.", ""]
    if data.get("issue_number"):
        body_parts.append(f"Closes #{data['issue_number']}")
    if data.get("issue_url"):
        body_parts.append(f"Issue: {data['issue_url']}")
    body = "\n".join(body_parts)
    code, out, err = _run(
        [
            "gh",
            "pr",
            "create",
            "--head",
            branch,
            "--title",
            title,
            "--body",
            body,
        ],
        cwd=root,
        timeout=180,
    )
    if code != 0:
        print(err.strip() or out.strip() or "gh pr create failed", file=sys.stderr)
        return ""
    url = out.strip().splitlines()[-1].strip() if out.strip() else ""
    if url.startswith("http"):
        return url
    return ""


def _execute(session_id: str, *, open_pr: bool = False) -> None:
    data = _load(session_id)
    if not data or data.get("status") not in {"pending", "running"}:
        return
    if data.get("status") == "cancelled":
        return
    data["status"] = "running"
    data["started"] = time.time()
    _save(data)

    goal = str(data.get("goal") or data.get("task") or "")
    max_steps = int(data.get("max_steps") or DEFAULT_MAX_STEPS)
    output, code = _run_goal_captured(goal, max_steps=max_steps)

    data = _load(session_id) or data
    if data.get("status") == "cancelled":
        return
    data["status"] = "done" if code == 0 else "failed"
    data["finished"] = time.time()
    data["exit_code"] = code
    data["result"] = output
    if open_pr and code == 0:
        pr_url = _maybe_create_pr(data)
        if pr_url:
            data["pr_url"] = pr_url
    _save(data)

    try:
        from arka.integrations.heartbeat import ping

        ping(f"jules.{data['status']}", source="jules")
    except Exception:
        pass


def assign(
    task: str,
    *,
    background: bool = True,
    max_steps: int = DEFAULT_MAX_STEPS,
    open_pr: bool = False,
    branch: bool = False,
) -> tuple[dict | None, str | None]:
    if not _enabled():
        return None, "jules disabled"
    ok, reason = _security_gate(task)
    if not ok:
        return None, reason
    if _running_count() >= _max_concurrent():
        return None, f"max concurrent Jules sessions ({_max_concurrent()}) reached"

    session_id = uuid.uuid4().hex[:10]
    data: dict[str, Any] = {
        "id": session_id,
        "kind": "assign",
        "task": task.strip(),
        "goal": task.strip(),
        "status": "pending",
        "max_steps": max_steps,
        "open_pr": open_pr,
        "created": time.time(),
        "when": datetime.now().isoformat(timespec="seconds"),
    }
    if branch:
        created, err = _create_branch(session_id)
        if err:
            return None, err
        data["branch"] = created
    _save(data)

    sync = _env("JULES_SYNC", "ARKA_JULES_SYNC", "").lower() in ("1", "true", "yes")
    if background and not sync:
        thread = threading.Thread(
            target=_execute,
            args=(session_id,),
            kwargs={"open_pr": open_pr},
            daemon=True,
        )
        thread.start()
    else:
        _execute(session_id, open_pr=open_pr)
        data = _load(session_id) or data
    return data, None


def assign_issue(
    issue_number: int,
    *,
    repo: str = "",
    background: bool = True,
    max_steps: int = DEFAULT_MAX_STEPS,
    open_pr: bool = True,
) -> tuple[dict | None, str | None]:
    if not _enabled():
        return None, "jules disabled"
    if not _gh_available():
        return None, "GitHub CLI (gh) not available or not authenticated"
    repo = repo or _resolve_repo()
    if not repo:
        return None, "could not resolve GitHub repo (use --repo owner/name)"
    issue = fetch_issue(issue_number, repo=repo)
    if not issue:
        return None, f"issue #{issue_number} not found in {repo}"
    if str(issue.get("state", "")).lower() == "closed":
        return None, f"issue #{issue_number} is already closed"

    goal = build_issue_goal(issue, repo=repo)
    ok, reason = _security_gate(goal)
    if not ok:
        return None, reason
    if _running_count() >= _max_concurrent():
        return None, f"max concurrent Jules sessions ({_max_concurrent()}) reached"

    session_id = uuid.uuid4().hex[:10]
    branch, err = _create_branch(session_id, issue_number=issue_number)
    if err:
        return None, err

    data: dict[str, Any] = {
        "id": session_id,
        "kind": "issue",
        "task": f"Fix issue #{issue_number}: {issue.get('title', '')}",
        "goal": goal,
        "status": "pending",
        "issue_number": issue_number,
        "issue_url": issue.get("url", ""),
        "repo": repo,
        "branch": branch,
        "max_steps": max_steps,
        "open_pr": open_pr,
        "created": time.time(),
        "when": datetime.now().isoformat(timespec="seconds"),
    }
    _save(data)

    sync = _env("JULES_SYNC", "ARKA_JULES_SYNC", "").lower() in ("1", "true", "yes")
    if background and not sync:
        thread = threading.Thread(
            target=_execute,
            args=(session_id,),
            kwargs={"open_pr": open_pr},
            daemon=True,
        )
        thread.start()
    else:
        _execute(session_id, open_pr=open_pr)
        data = _load(session_id) or data
    return data, None


def list_sessions(*, limit: int = 20) -> list[dict]:
    root = jules_root()
    if not root.is_dir():
        return []
    rows: list[tuple[float, dict]] = []
    for path in root.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                rows.append((float(data.get("created") or 0), data))
        except (OSError, json.JSONDecodeError):
            continue
    rows.sort(key=lambda x: x[0], reverse=True)
    out: list[dict] = []
    for _, data in rows[:limit]:
        out.append(
            {
                "id": data.get("id"),
                "kind": data.get("kind"),
                "status": data.get("status"),
                "task": str(data.get("task", ""))[:120],
                "issue_number": data.get("issue_number"),
                "branch": data.get("branch"),
                "pr_url": data.get("pr_url"),
                "when": data.get("when"),
                "exit_code": data.get("exit_code"),
            }
        )
    return out


def session_status(session_id: str) -> dict | None:
    return _load(session_id)


def cancel_session(session_id: str) -> tuple[bool, str]:
    data = _load(session_id)
    if not data:
        return False, f"unknown session {session_id}"
    status = str(data.get("status") or "")
    if status in {"done", "failed", "cancelled"}:
        return False, f"session already {status}"
    data["status"] = "cancelled"
    data["finished"] = time.time()
    _save(data)
    if status == "running":
        return True, "marked cancelled (background work may still finish)"
    return True, "cancelled"


def create_pr(session_id: str) -> tuple[str | None, str | None]:
    data = _load(session_id)
    if not data:
        return None, f"unknown session {session_id}"
    if data.get("pr_url"):
        return str(data["pr_url"]), None
    if str(data.get("status")) != "done":
        return None, f"session is {data.get('status')} — wait until done"
    url = _maybe_create_pr(data)
    if not url:
        return None, "could not create PR (check branch has commits and gh is configured)"
    data["pr_url"] = url
    _save(data)
    return url, None


def status_summary() -> dict:
    root = jules_root()
    rows = list_sessions(limit=100)
    by_status: dict[str, int] = {}
    for row in rows:
        st = str(row.get("status", "?"))
        by_status[st] = by_status.get(st, 0) + 1
    return {
        "enabled": _enabled(),
        "root": str(root),
        "max_concurrent": _max_concurrent(),
        "running": _running_count(),
        "total": len(list(root.glob("*.json"))) if root.is_dir() else 0,
        "by_status": by_status,
    }


def print_status() -> None:
    info = status_summary()
    print(f"Jules sessions: {'on' if info['enabled'] else 'off'}")
    print(f"  Root: {info['root']}")
    print(f"  Running: {info['running']} / {info['max_concurrent']}")
    print(f"  Stored: {info['total']}")
    if info.get("by_status"):
        parts = [f"{k}={v}" for k, v in sorted(info["by_status"].items())]
        print(f"  Status: {', '.join(parts)}")


def route_command(text: str) -> str:
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if not raw:
        return ""
    low = raw.lower()

    if re.search(r"(?i)\bjules\b.*\b(?:list|status|sessions?)\b", low) or low in {
        "jules list",
        "jules status",
        "list jules sessions",
        "show jules sessions",
    }:
        return "jules list"

    if re.search(r"(?i)\b(?:cancel|stop|abort)\b.*\bjules\b", low):
        match = re.search(r"\b([a-f0-9]{6,10})\b", raw)
        if match:
            return f"jules cancel {match.group(1)}"
        return "jules list"

    if re.search(r"(?i)\b(?:resume|check|show)\b.*\bjules\b", low):
        match = re.search(r"\b([a-f0-9]{6,10})\b", raw)
        if match:
            return f"jules resume {match.group(1)}"
        return "jules list"

    issue_match = re.search(
        r"(?i)(?:fix|work on|resolve|tackle)\s+(?:github\s+)?issue\s+#?(\d+)",
        raw,
    )
    if issue_match or re.search(r"(?i)\bjules\b.*\bissue\s+#?(\d+)\b", raw):
        num = (issue_match or re.search(r"(?i)\bissue\s+#?(\d+)\b", raw)).group(1)
        open_pr = "--no-pr" not in low
        line = f"jules issue {num}"
        if not open_pr:
            line += " --no-pr"
        return line

    if re.search(
        r"(?i)\b(?:work on|fix|implement|add|create)\b.*\b(?:async|background|later)\b",
        low,
    ) or re.search(r"(?i)\b(?:async|background)\b.*\b(?:coding|code|task|fix|implement)\b", low):
        task = re.sub(
            r"(?i)^(?:arka\s+)?(?:please\s+)?(?:work on|fix|implement|add|create)\s+",
            "",
            raw,
        )
        task = re.sub(r"(?i)\b(?:async|in the background|later)\b", "", task).strip()
        task = re.sub(r"(?i)^(?:background\s+coding|async\s+coding)\s+", "", task).strip()
        if task:
            return f"jules assign {shlex.quote(task)}"

    if re.search(r"(?i)\bcreate\s+(?:a\s+)?pr\b.*\bjules\b", low):
        match = re.search(r"\b([a-f0-9]{6,10})\b", raw)
        if match:
            return f"jules pr {match.group(1)}"

    if re.search(r"(?i)^jules\b", raw):
        rest = re.sub(r"(?i)^(?:arka\s+)?jules\s*", "", raw).strip()
        return f"jules {rest}".strip() if rest else "jules list"

    if re.search(r"(?i)\bassign\b.*\bjules\b|\bjules\b.*\bassign\b", low):
        task = re.sub(r"(?i).*\bassign\b", "", raw).strip()
        task = re.sub(r"(?i)\bjules\b", "", task).strip()
        if task:
            return f"jules assign {shlex.quote(task)}"

    return ""


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    parser = argparse.ArgumentParser(
        description="Jules-style async coding sessions — assign, track, open PRs",
    )
    sub = parser.add_subparsers(dest="cmd")

    p_assign = sub.add_parser("assign", help="Assign a background coding task")
    p_assign.add_argument("task", nargs="+", help="Natural-language task")
    p_assign.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    p_assign.add_argument("--branch", action="store_true", help="Create a jules/* branch first")
    p_assign.add_argument("--pr", action="store_true", help="Open PR when done")
    p_assign.add_argument("--sync", action="store_true", help="Run synchronously (for tests)")

    p_issue = sub.add_parser("issue", help="Fix a GitHub issue in the background")
    p_issue.add_argument("issue_number", type=int)
    p_issue.add_argument("--repo", default="", help="owner/repo (default: current repo)")
    p_issue.add_argument("--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    p_issue.add_argument("--no-pr", action="store_true", help="Do not open PR when done")
    p_issue.add_argument("--sync", action="store_true")

    sub.add_parser("list", help="List recent sessions")
    p_status = sub.add_parser("status", help="Show session or summary status")
    p_status.add_argument("session_id", nargs="?")

    p_cancel = sub.add_parser("cancel", help="Cancel a pending session")
    p_cancel.add_argument("session_id")

    p_resume = sub.add_parser("resume", help="Show session result")
    p_resume.add_argument("session_id")

    p_pr = sub.add_parser("pr", help="Create PR for a completed session")
    p_pr.add_argument("session_id")

    p_route = sub.add_parser("route")
    p_route.add_argument("text", nargs="+")

    args = parser.parse_args(argv)

    if args.cmd == "assign":
        if args.sync:
            os.environ["JULES_SYNC"] = "1"
        task = " ".join(args.task).strip()
        data, err = assign(
            task,
            max_steps=max(1, args.max_steps),
            open_pr=args.pr,
            branch=args.branch,
        )
        if err:
            print(f"Assign blocked: {err}", file=sys.stderr)
            return 1
        assert data is not None
        print(f"Jules session {data['id']} [{data.get('status', 'pending')}]")
        if data.get("branch"):
            print(f"  Branch: {data['branch']}")
        print(f"  Check: arka jules status {data['id']}")
        if data.get("result"):
            print(data["result"])
        if data.get("pr_url"):
            print(f"  PR: {data['pr_url']}")
        return 0 if data.get("status") != "failed" else 1

    if args.cmd == "issue":
        if args.sync:
            os.environ["JULES_SYNC"] = "1"
        data, err = assign_issue(
            args.issue_number,
            repo=args.repo,
            max_steps=max(1, args.max_steps),
            open_pr=not args.no_pr,
        )
        if err:
            print(f"Issue assign blocked: {err}", file=sys.stderr)
            return 1
        assert data is not None
        print(f"Jules session {data['id']} [{data.get('status', 'pending')}]")
        print(f"  Issue: #{data.get('issue_number')} {data.get('issue_url', '')}")
        if data.get("branch"):
            print(f"  Branch: {data['branch']}")
        print(f"  Check: arka jules status {data['id']}")
        if data.get("result"):
            print(data["result"])
        if data.get("pr_url"):
            print(f"  PR: {data['pr_url']}")
        return 0 if data.get("status") != "failed" else 1

    if args.cmd == "list":
        rows = list_sessions()
        if not rows:
            print("No Jules sessions.")
            return 0
        for row in rows:
            issue = f" #{row['issue_number']}" if row.get("issue_number") else ""
            pr = f" → {row['pr_url']}" if row.get("pr_url") else ""
            print(f"[{row['status']}] {row['id']}{issue}  {row.get('when', '')}{pr}")
            print(f"  {row.get('task', '')}")
        return 0

    if args.cmd == "status":
        if args.session_id:
            data = session_status(args.session_id)
            if not data:
                print(f"No session {args.session_id}.", file=sys.stderr)
                return 1
            print(json.dumps(data, indent=2))
            return 0
        print_status()
        return 0

    if args.cmd == "cancel":
        ok, msg = cancel_session(args.session_id)
        if not ok:
            print(msg, file=sys.stderr)
            return 1
        print(msg)
        return 0

    if args.cmd == "resume":
        data = session_status(args.session_id)
        if not data:
            print(f"No session {args.session_id}.", file=sys.stderr)
            return 1
        print(f"Session {data.get('id')} [{data.get('status')}]")
        print(f"Task: {data.get('task', '')}")
        if data.get("branch"):
            print(f"Branch: {data['branch']}")
        if data.get("pr_url"):
            print(f"PR: {data['pr_url']}")
        if data.get("result"):
            print(f"Result:\n{data['result']}")
        return 0

    if args.cmd == "pr":
        url, err = create_pr(args.session_id)
        if err:
            print(err, file=sys.stderr)
            return 1
        assert url
        print(url)
        return 0

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
