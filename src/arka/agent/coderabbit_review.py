#!/usr/bin/env python3
"""CodeRabbit integration — local CLI reviews and GitHub PR triggers/comments."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
from pathlib import Path

from arka.agent.pr_check import _run, gh_available, git_root, resolve_pr

CODERABBIT_BOTS = ("coderabbitai", "coderabbitai[bot]")
TRIGGER_INCREMENTAL = "@coderabbitai review"
TRIGGER_FULL = "@coderabbitai full review"


def cr_cli_available() -> bool:
    return cr_bin() is not None


def cr_bin() -> str | None:
    return shutil.which("cr") or shutil.which("coderabbit")


def repo_slug(root: Path) -> str | None:
    if not gh_available():
        return None
    code, out, _ = _run(["gh", "repo", "view", "--json", "nameWithOwner"], cwd=root)
    if code != 0:
        return None
    try:
        data = json.loads(out)
    except json.JSONDecodeError:
        return None
    slug = str(data.get("nameWithOwner") or "").strip()
    return slug or None


def _is_coderabbit_user(login: str) -> bool:
    low = (login or "").lower()
    return any(low == bot or low.startswith("coderabbit") for bot in CODERABBIT_BOTS)


def run_local_review(
    root: Path,
    *,
    base: str | None = None,
    uncommitted: bool = False,
    agent_json: bool = False,
    light: bool = False,
) -> tuple[int, str]:
    """Run CodeRabbit CLI when installed; return (exit_code, output)."""
    exe = cr_bin()
    if not exe:
        return 1, (
            "CodeRabbit CLI not installed.\n"
            "Install: curl -fsSL https://cli.coderabbit.ai/install.sh | sh\n"
            "Then: cr auth login\n"
            "Or trigger a PR review: coderabbit trigger"
        )
    cmd = [exe, "review"]
    if agent_json:
        cmd.append("--agent")
    if light:
        cmd.append("--light")
    if uncommitted:
        cmd.append("--uncommitted")
    if base:
        cmd.extend(["--base", base])
    api_key = os.environ.get("CODERABBIT_API_KEY", "").strip()
    if api_key:
        cmd.extend(["--api-key", api_key])
    code, out, err = _run(cmd, cwd=root, timeout=600)
    text = (out or err).strip()
    return code, text or "(no output from CodeRabbit CLI)"


def trigger_pr_review(root: Path, pr: int | None = None, *, full: bool = False) -> dict:
    """Comment on a PR to request a CodeRabbit review."""
    if not gh_available():
        return {"ok": False, "error": "GitHub CLI (gh) not authenticated"}
    pr_data = resolve_pr(root, pr)
    if not pr_data:
        return {
            "ok": False,
            "error": "No open pull request found. Push a branch and run: gh pr create",
        }
    number = int(pr_data["number"])
    body = TRIGGER_FULL if full else TRIGGER_INCREMENTAL
    code, out, err = _run(
        ["gh", "pr", "comment", str(number), "--body", body],
        cwd=root,
    )
    if code != 0:
        return {"ok": False, "error": (err or out or "gh pr comment failed").strip(), "pr": pr_data}
    return {
        "ok": True,
        "pr": pr_data,
        "trigger": body,
        "message": f"Requested CodeRabbit review on PR #{number}",
        "url": pr_data.get("url"),
    }


def _gh_api_json(root: Path, endpoint: str) -> list | dict | None:
    code, out, _ = _run(["gh", "api", endpoint], cwd=root)
    if code != 0 or not out.strip():
        return None
    try:
        return json.loads(out)
    except json.JSONDecodeError:
        return None


def fetch_pr_feedback(root: Path, pr: int | None = None) -> dict:
    """Collect CodeRabbit issue comments, review comments, and review summaries."""
    if not gh_available():
        return {"ok": False, "error": "GitHub CLI (gh) not authenticated"}
    pr_data = resolve_pr(root, pr)
    if not pr_data:
        return {"ok": False, "error": "No pull request found for current branch"}
    number = int(pr_data["number"])
    slug = repo_slug(root)
    if not slug:
        return {"ok": False, "error": "Could not resolve repository slug"}

    issue_comments = _gh_api_json(root, f"repos/{slug}/issues/{number}/comments") or []
    review_comments = _gh_api_json(root, f"repos/{slug}/pulls/{number}/comments") or []
    reviews = _gh_api_json(root, f"repos/{slug}/pulls/{number}/reviews") or []

    def _pick(rows: list) -> list[dict]:
        out: list[dict] = []
        for row in rows if isinstance(rows, list) else []:
            user = row.get("user") or {}
            login = str(user.get("login") or "")
            if not _is_coderabbit_user(login):
                continue
            out.append(
                {
                    "id": row.get("id"),
                    "user": login,
                    "body": str(row.get("body") or "").strip(),
                    "path": row.get("path"),
                    "line": row.get("line") or row.get("original_line"),
                    "created_at": row.get("created_at"),
                    "url": row.get("html_url"),
                }
            )
        return out

    picked_issue = _pick(issue_comments if isinstance(issue_comments, list) else [])
    picked_inline = _pick(review_comments if isinstance(review_comments, list) else [])
    picked_reviews: list[dict] = []
    for row in reviews if isinstance(reviews, list) else []:
        user = row.get("user") or {}
        login = str(user.get("login") or "")
        if not _is_coderabbit_user(login):
            continue
        picked_reviews.append(
            {
                "id": row.get("id"),
                "user": login,
                "state": row.get("state"),
                "body": str(row.get("body") or "").strip(),
                "submitted_at": row.get("submitted_at"),
            }
        )

    return {
        "ok": True,
        "pr": pr_data,
        "issue_comments": picked_issue,
        "inline_comments": picked_inline,
        "reviews": picked_reviews,
        "total": len(picked_issue) + len(picked_inline) + len(picked_reviews),
    }


def format_feedback(data: dict) -> str:
    if not data.get("ok"):
        return str(data.get("error") or "CodeRabbit feedback unavailable")
    lines = [f"CodeRabbit feedback — PR #{data['pr'].get('number')}: {data['pr'].get('title')}"]
    lines.append(str(data["pr"].get("url") or ""))
    lines.append(f"Items: {data.get('total', 0)}")
    for label, key in (
        ("Reviews", "reviews"),
        ("PR comments", "issue_comments"),
        ("Inline comments", "inline_comments"),
    ):
        rows = data.get(key) or []
        if not rows:
            continue
        lines.append("")
        lines.append(f"## {label}")
        for row in rows[:20]:
            body = str(row.get("body") or "").strip()
            if len(body) > 1200:
                body = body[:1200] + "…"
            prefix = ""
            if row.get("path"):
                prefix = f"{row['path']}"
                if row.get("line"):
                    prefix += f":{row['line']}"
                prefix += " — "
            lines.append(f"- {prefix}{body.splitlines()[0] if body else '(empty)'}")
            if body.count("\n"):
                lines.append(body)
    return "\n".join(lines).strip()


def cmd_review(args: argparse.Namespace) -> int:
    root = git_root()
    if not root:
        print("Not inside a git repository.", file=sys.stderr)
        return 1
    code, text = run_local_review(
        root,
        base=args.base or None,
        uncommitted=args.uncommitted,
        agent_json=args.agent,
        light=args.light,
    )
    print(text)
    return code


def cmd_trigger(args: argparse.Namespace) -> int:
    root = git_root()
    if not root:
        print("Not inside a git repository.", file=sys.stderr)
        return 1
    result = trigger_pr_review(root, args.pr, full=args.full)
    if args.json:
        print(json.dumps(result, indent=2))
    elif result.get("ok"):
        print(result.get("message", "Triggered"))
    else:
        print(result.get("error", "trigger failed"), file=sys.stderr)
    return 0 if result.get("ok") else 1


def cmd_comments(args: argparse.Namespace) -> int:
    root = git_root()
    if not root:
        print("Not inside a git repository.", file=sys.stderr)
        return 1
    data = fetch_pr_feedback(root, args.pr)
    if args.json:
        print(json.dumps(data, indent=2))
    else:
        print(format_feedback(data))
    return 0 if data.get("ok") else 1


def cmd_doctor(_args: argparse.Namespace) -> int:
    root = git_root()
    lines = [
        f"cli_installed: {cr_cli_available()}",
        f"gh_authenticated: {gh_available()}",
        f"git_root: {root}",
    ]
    if cr_cli_available():
        exe = cr_bin() or "cr"
        code, out, err = _run([exe, "auth", "status"], cwd=root, timeout=30)
        lines.append(f"cr_auth_status_exit: {code}")
        if out.strip():
            lines.append(out.strip())
        if err.strip():
            lines.append(err.strip())
    if root and gh_available():
        pr = resolve_pr(root, None)
        lines.append(f"current_pr: {pr.get('number') if pr else 'none'}")
    print("\n".join(lines))
    return 0


def route_command(text: str) -> str:
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if not raw:
        return ""
    low = raw.lower()
    if not re.search(r"(?i)\bcoderabbit\b", low):
        return ""
    if re.search(r"(?i)\b(trigger|request|ask)\b", low):
        return "coderabbit trigger" + (" --full" if re.search(r"(?i)\bfull\b", low) else "")
    if re.search(r"(?i)\b(comment|feedback|findings|threads)\b", low):
        return "coderabbit comments"
    if re.search(r"(?i)\b(doctor|status|setup)\b", low):
        return "coderabbit doctor"
    if re.search(r"(?i)\b(review|audit|check)\b", low):
        return "coderabbit review"
    return "coderabbit review"


def coderabbit_payload(action: str = "comments", *, root: Path | str | None = None, pr: int | None = None, full: bool = False) -> dict:
    project = Path(root).expanduser().resolve() if root else git_root()
    if project is None or not project.is_dir():
        return {"ok": False, "error": "not a git repository"}
    act = (action or "comments").strip().lower()
    if act == "trigger":
        return trigger_pr_review(project, pr, full=full)
    if act == "comments":
        return fetch_pr_feedback(project, pr)
    if act == "doctor":
        return {
            "ok": cr_cli_available() or gh_available(),
            "cli_installed": cr_cli_available(),
            "gh_authenticated": gh_available(),
            "path": str(project),
        }
    if act == "review":
        code, text = run_local_review(project)
        return {"ok": code == 0, "exit_code": code, "output": text, "cli_installed": cr_cli_available()}
    return {"ok": False, "error": f"unknown action: {action}"}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka coderabbit", description="CodeRabbit PR + CLI integration")
    sub = parser.add_subparsers(dest="cmd")

    p_review = sub.add_parser("review", help="Run CodeRabbit CLI on local git changes")
    p_review.add_argument("--base", "-b", default="")
    p_review.add_argument("--uncommitted", action="store_true")
    p_review.add_argument("--agent", action="store_true", help="JSON output for agents")
    p_review.add_argument("--light", action="store_true")

    p_trigger = sub.add_parser("trigger", help="Comment @coderabbitai review on the current PR")
    p_trigger.add_argument("--pr", type=int, default=None)
    p_trigger.add_argument("--full", action="store_true")
    p_trigger.add_argument("--json", action="store_true")

    p_comments = sub.add_parser("comments", help="Fetch CodeRabbit PR comments")
    p_comments.add_argument("--pr", type=int, default=None)
    p_comments.add_argument("--json", action="store_true")

    sub.add_parser("doctor", help="Check CLI + gh + PR readiness")

    p_route = sub.add_parser("route")
    p_route.add_argument("text", nargs="+")

    args = parser.parse_args(argv)
    if args.cmd == "review":
        return cmd_review(args)
    if args.cmd == "trigger":
        return cmd_trigger(args)
    if args.cmd == "comments":
        return cmd_comments(args)
    if args.cmd == "doctor":
        return cmd_doctor(args)
    if args.cmd == "route":
        line = route_command(" ".join(args.text))
        print(line)
        return 0 if line else 1
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
