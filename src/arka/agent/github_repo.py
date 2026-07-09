#!/usr/bin/env python3
"""GitHub repo activity — recent commits and modified files via gh API or local git."""

from __future__ import annotations

import argparse
import json
import re
import sys
from collections import OrderedDict
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from arka.agent.pr_check import _run, gh_available, git_root
    from arka.paths import load_env_file

    load_env_file()
except ImportError:

    def load_env_file() -> None:
        pass

    def gh_available() -> bool:
        return False

    def git_root() -> Path | None:
        return None

    def _run(cmd, *, cwd=None, timeout=120):
        return 1, "", "unavailable"


_GITHUB_REPO_RE = re.compile(r"github\.com/([^/\s#?]+)/([^/\s#?]+)", re.I)

_ACTIVITY_RE = re.compile(
    r"(?i)\b("
    r"files?\s+(?:were\s+)?(?:modified|changed|updated|touched)|"
    r"what\s+(?:files?\s+)?(?:changed|modified|updated)|"
    r"recent\s+commits?|"
    r"commits?\s+(?:in|over|during|for)|"
    r"(?:repo(?:sitory)?\s+)?activity|"
    r"modified\s+in|"
    r"changed\s+in|"
    r"updates?\s+(?:in|to|for)\s+(?:the\s+)?(?:repo|repository)|"
    r"what\s+happened"
    r")\b"
)


def parse_github_repo(text: str) -> tuple[str, str] | None:
    match = _GITHUB_REPO_RE.search(text or "")
    if not match:
        return None
    owner = match.group(1).strip(".")
    repo = match.group(2).removesuffix(".git").strip(".")
    if owner.lower() == "orgs" or owner.lower() == "repos":
        return None
    return owner, repo


def parse_since_days(question: str, *, default: int = 7) -> int:
    text = question or ""
    m = re.search(r"(?i)(?:last|past|this)\s+(\d+)\s+(day|days|week|weeks|hour|hours)", text)
    if m:
        n = int(m.group(1))
        unit = m.group(2).lower()
        if unit.startswith("week"):
            return max(1, n * 7)
        if unit.startswith("hour"):
            return max(1, (n + 23) // 24)
        return max(1, n)
    m = re.search(r"(?i)(\d+)\s+(day|days|week|weeks)\b", text)
    if m:
        n = int(m.group(1))
        if m.group(2).lower().startswith("week"):
            return max(1, n * 7)
        return max(1, n)
    if re.search(r"(?i)\b(today|last 24 hours?)\b", text):
        return 1
    if re.search(r"(?i)\b(this week|last week)\b", text):
        return 7
    if re.search(r"(?i)\b(this month|last month)\b", text):
        return 30
    return default


def wants_github_repo_activity(question: str) -> bool:
    if not parse_github_repo(question):
        return False
    return bool(_ACTIVITY_RE.search(question))


def _since_iso(days: int) -> str:
    dt = datetime.now(timezone.utc) - timedelta(days=max(1, days))
    return dt.replace(microsecond=0).isoformat().replace("+00:00", "Z")


def _local_remote_matches(root: Path, owner: str, repo: str) -> bool:
    code, out, _ = _run(["git", "remote", "get-url", "origin"], cwd=root)
    if code != 0:
        return False
    remote = out.strip().lower()
    slug = f"{owner.lower()}/{repo.lower()}"
    return slug in remote


def _fetch_via_local_git(root: Path, *, days: int) -> tuple[list[dict], OrderedDict[str, int]]:
    since_arg = f"{days}.days.ago"
    code, out, err = _run(
        [
            "git",
            "log",
            f"--since={since_arg}",
            "--pretty=format:%H|%h|%s|%an|%aI",
            "--name-only",
        ],
        cwd=root,
    )
    if code != 0:
        raise RuntimeError(err.strip() or "git log failed")

    commits: list[dict] = []
    files: OrderedDict[str, int] = OrderedDict()
    block: list[str] = []
    for line in out.splitlines():
        if not line.strip():
            if block:
                header = block[0]
                parts = header.split("|", 4)
                if len(parts) >= 5:
                    commits.append(
                        {
                            "sha": parts[1],
                            "message": parts[2],
                            "author": parts[3],
                            "date": parts[4],
                        }
                    )
                    for path in block[1:]:
                        if path.strip():
                            files[path.strip()] = files.get(path.strip(), 0) + 1
                block = []
            continue
        block.append(line.strip())
    if block:
        header = block[0]
        parts = header.split("|", 4)
        if len(parts) >= 5:
            commits.append(
                {
                    "sha": parts[1],
                    "message": parts[2],
                    "author": parts[3],
                    "date": parts[4],
                }
            )
            for path in block[1:]:
                if path.strip():
                    files[path.strip()] = files.get(path.strip(), 0) + 1
    return commits, files


def _fetch_via_gh_api(owner: str, repo: str, *, days: int) -> tuple[list[dict], OrderedDict[str, int]]:
    since = _since_iso(days)
    code, out, err = _run(
        [
            "gh",
            "api",
            f"repos/{owner}/{repo}/commits",
            "-f",
            f"since={since}",
            "-f",
            "per_page=100",
        ],
        timeout=180,
    )
    if code != 0:
        raise RuntimeError(err.strip() or out.strip() or "gh api commits failed")
    try:
        rows = json.loads(out)
    except json.JSONDecodeError as exc:
        raise RuntimeError(f"Invalid gh response: {exc}") from exc
    if not isinstance(rows, list):
        raise RuntimeError("Unexpected gh commits response")

    commits: list[dict] = []
    files: OrderedDict[str, int] = OrderedDict()
    for row in rows[:50]:
        if not isinstance(row, dict):
            continue
        sha = str(row.get("sha") or "")[:7]
        commit = row.get("commit") or {}
        message = str((commit.get("message") or "").splitlines()[0] or "commit")
        author = ((commit.get("author") or {}).get("name")) or "unknown"
        date = ((commit.get("author") or {}).get("date")) or ""
        commits.append({"sha": sha, "message": message, "author": author, "date": date})

        full_sha = str(row.get("sha") or "")
        if not full_sha:
            continue
        dcode, detail_out, _ = _run(
            ["gh", "api", f"repos/{owner}/{repo}/commits/{full_sha}"],
            timeout=60,
        )
        if dcode != 0:
            continue
        try:
            detail = json.loads(detail_out)
        except json.JSONDecodeError:
            continue
        for file_row in detail.get("files") or []:
            if isinstance(file_row, dict):
                name = str(file_row.get("filename") or "").strip()
                if name:
                    files[name] = files.get(name, 0) + 1
    return commits, files


def fetch_repo_activity(owner: str, repo: str, *, days: int) -> str:
    commits: list[dict]
    files: OrderedDict[str, int]
    source = "GitHub API"

    root = git_root()
    if root and _local_remote_matches(root, owner, repo):
        try:
            commits, files = _fetch_via_local_git(root, days=days)
            source = "local git"
        except RuntimeError:
            if not gh_available():
                raise
            commits, files = _fetch_via_gh_api(owner, repo, days=days)
            source = "GitHub API"
    elif gh_available():
        commits, files = _fetch_via_gh_api(owner, repo, days=days)
    else:
        return (
            f"Cannot load activity for {owner}/{repo}.\n"
            "Install GitHub CLI and run `gh auth login`, or clone the repo locally."
        )

    lines = [
        f"Repository: {owner}/{repo}",
        f"Period: last {days} day(s) (since {_since_iso(days)})",
        f"Source: {source}",
        "",
    ]
    if not commits:
        lines.append("No commits found in this period.")
        return "\n".join(lines)

    lines.append(f"Commits ({len(commits)}):")
    for row in commits[:20]:
        lines.append(
            f"- {row.get('sha', '?')} {row.get('message', '')[:80]} "
            f"({row.get('author', '?')}, {str(row.get('date', ''))[:10]})"
        )
    if len(commits) > 20:
        lines.append(f"… and {len(commits) - 20} more commit(s)")

    lines.append("")
    if files:
        lines.append(f"Files modified ({len(files)} unique):")
        for path in list(files.keys())[:60]:
            count = files[path]
            suffix = f" ({count} commits)" if count > 1 else ""
            lines.append(f"- {path}{suffix}")
        if len(files) > 60:
            lines.append(f"… and {len(files) - 60} more file(s)")
    else:
        lines.append("No file list available for these commits.")

    return "\n".join(lines)


def fetch_activity_for_question(question: str) -> str | None:
    if not wants_github_repo_activity(question):
        return None
    parsed = parse_github_repo(question)
    if not parsed:
        return None
    owner, repo = parsed
    days = parse_since_days(question, default=7)
    try:
        return fetch_repo_activity(owner, repo, days=days)
    except RuntimeError as exc:
        return f"GitHub activity lookup failed for {owner}/{repo}: {exc}"


def route_command(text: str) -> str:
    if not wants_github_repo_activity(text):
        return ""
    parsed = parse_github_repo(text)
    if not parsed:
        return ""
    owner, repo = parsed
    days = parse_since_days(text, default=7)
    return f"github_repo activity {owner}/{repo} --days {days}"


def cmd_activity(args: argparse.Namespace) -> int:
    target = args.repo.strip()
    if "/" not in target:
        print("Usage: github_repo activity owner/repo [--days N]", file=sys.stderr)
        return 1
    owner, repo = target.split("/", 1)
    text = fetch_repo_activity(owner, repo, days=max(1, int(args.days)))
    print(text)
    return 0


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    parser = argparse.ArgumentParser(description="GitHub repository activity")
    sub = parser.add_subparsers(dest="cmd")

    p_route = sub.add_parser("route", help="Map NL to github_repo command")
    p_route.add_argument("text", nargs="+")

    p_act = sub.add_parser("activity", help="List recent commits and modified files")
    p_act.add_argument("repo", help="owner/repo")
    p_act.add_argument("--days", type=int, default=7)

    args = parser.parse_args(argv)
    if args.cmd == "route":
        route = route_command(" ".join(args.text))
        if route:
            print(route)
            return 0
        return 1
    if args.cmd == "activity":
        return cmd_activity(args)
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
