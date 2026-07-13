#!/usr/bin/env python3
"""Optimized repo context — read llm.txt instead of full repo scans."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from arka.agent.pr_check import git_root
    from arka.paths import config_dir, load_env_file

    load_env_file()
except ImportError:

    def load_env_file() -> None:
        pass

    def config_dir() -> Path:
        return Path.home() / ".config" / "arka"

    def git_root() -> Path | None:
        try:
            proc = subprocess.run(
                ["git", "rev-parse", "--show-toplevel"],
                capture_output=True,
                text=True,
            )
        except OSError:
            return None
        if proc.returncode != 0:
            return None
        root = Path((proc.stdout or "").strip())
        return root if root.is_dir() else None


LLM_TXT = "llm.txt"
LOCAL_INDEX = ".arka-index"
MAX_CHANGELOG_ENTRIES = 80
MAX_QUERY_CHARS = 12000

_SECTION_RE = re.compile(
    r"^={3,}\s*\n(.+?)\n={3,}",
    re.MULTILINE,
)

# Broad repo/architecture questions → llm.txt (symbolic barrier).
_CONTEXT_RE = re.compile(
    r"(?i)\b("
    r"how\s+(?:does|is)\s+(?:arka\s+)?(?:routing|dispatch|the\s+router)\s+work|"
    r"where\s+is\s+.+\s+in\s+(?:the\s+)?(?:codebase|repo|project)|"
    r"(?:explain|describe|show)\s+(?:the\s+)?(?:repo|project|codebase)\s+structure|"
    r"how\s+is\s+arka\s+organized|"
    r"what\s+files?\s+changed|"
    r"recent\s+(?:file\s+)?changes?|"
    r"(?:repo|project|codebase)\s+(?:structure|layout|organization|overview)|"
    r"(?:explore|understand|read)\s+(?:the\s+)?(?:repo|project|codebase)|"
    r"(?:what(?:'s|\s+is)\s+in|tell\s+me\s+about)\s+(?:this\s+)?(?:repo|project|codebase)|"
    r"llm\.txt|"
    r"(?:architecture|module)\s+(?:map|overview)|"
    r"how\s+(?:does|do)\s+.+\s+work\s+in\s+(?:arka|this\s+repo)"
    r")\b"
)

# Explicit full-tree scan → repo_map (narrow escape hatch).
_EXPLICIT_MAP_RE = re.compile(
    r"(?i)\b("
    r"repo\s+map|map\s+(?:this\s+)?repo|"
    r"(?:deep|detailed|full)\s+(?:repo|project|codebase)\s+(?:map|structure|layout)|"
    r"show\s+(?:me\s+)?(?:the\s+)?(?:repo|project|codebase)\s+(?:tree|map|layout)"
    r")\b"
)

_BARRIER_RE = re.compile(
    r"(?i)\b("
    r"explore\s+(?:the\s+)?codebase|"
    r"read\s+(?:the\s+)?(?:entire\s+)?repo|"
    r"understand\s+(?:the\s+)?project|"
    r"scan\s+(?:the\s+)?(?:whole\s+)?repo|"
    r"browse\s+(?:the\s+)?codebase"
    r")\b"
)

_CHANGE_KEYWORDS = re.compile(
    r"(?i)\b(changed?|changelog|recent\s+changes?|what\s+files?|delta|diff)\b"
)
_ARCH_KEYWORDS = re.compile(
    r"(?i)\b(routing|router|dispatch|architecture|module|skill|pipeline|structure|layout|organized)\b"
)


def _project_root(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    root = git_root()
    if root:
        return root
    return Path.cwd().resolve()


def llm_txt_path(root: Path | None = None) -> Path:
    return (_project_root(str(root) if root else None) if root is not None else _project_root()) / LLM_TXT


def _run_git(args: list[str], *, cwd: Path) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            ["git", *args],
            cwd=str(cwd),
            capture_output=True,
            text=True,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except OSError as exc:
        return 1, "", str(exc)


def _head_commit(root: Path) -> str | None:
    code, out, _ = _run_git(["rev-parse", "HEAD"], cwd=root)
    if code != 0:
        return None
    commit = out.strip()
    return commit or None


def _index_file() -> Path:
    return config_dir() / "repo-index.json"


def _repo_key(root: Path) -> str:
    return str(root.resolve())


def _load_global_index() -> dict[str, object]:
    path = _index_file()
    if not path.is_file():
        return {"repos": {}}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"repos": {}}
    if not isinstance(data, dict):
        return {"repos": {}}
    repos = data.get("repos")
    if not isinstance(repos, dict):
        data["repos"] = {}
    return data


def _save_global_index(data: dict[str, object]) -> None:
    path = _index_file()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _load_local_index(root: Path) -> dict[str, object]:
    path = root / LOCAL_INDEX
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _save_local_index(root: Path, data: dict[str, object]) -> None:
    path = root / LOCAL_INDEX
    path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def get_index_state(root: Path | None = None) -> dict[str, object]:
    project = _project_root(str(root) if root else None) if root is not None else _project_root()
    global_data = _load_global_index()
    repos = global_data.setdefault("repos", {})
    assert isinstance(repos, dict)
    entry = repos.get(_repo_key(project))
    if not isinstance(entry, dict):
        entry = {}
    local = _load_local_index(project)
    merged = {**entry, **local}
    return {
        "root": str(project),
        "last_commit": merged.get("last_commit"),
        "last_sync": merged.get("last_sync"),
        "llm_txt": str(llm_txt_path(project)),
    }


def save_index_state(root: Path, *, commit: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    payload = {"last_commit": commit, "last_sync": now}
    global_data = _load_global_index()
    repos = global_data.setdefault("repos", {})
    assert isinstance(repos, dict)
    repos[_repo_key(root)] = payload
    _save_global_index(global_data)
    _save_local_index(root, payload)


def read_llm_txt(root: Path | None = None) -> str:
    path = llm_txt_path(root)
    if not path.is_file():
        return ""
    return path.read_text(encoding="utf-8", errors="replace")


def parse_sections(text: str) -> dict[str, str]:
    sections: dict[str, str] = {}
    matches = list(_SECTION_RE.finditer(text))
    for i, match in enumerate(matches):
        title = match.group(1).strip().upper()
        start = match.end()
        end = matches[i + 1].start() if i + 1 < len(matches) else len(text)
        body = text[start:end].strip()
        sections[title] = body
    return sections


def _section_aliases(name: str) -> list[str]:
    upper = name.strip().upper()
    if upper in {"CHANGELOG", "RECENT FILE CHANGES", "RECENT FILE CHANGES (CHANGELOG)"}:
        return ["RECENT FILE CHANGES (CHANGELOG)", "RECENT FILE CHANGES", "CHANGELOG"]
    if upper == "AGENT RULES":
        return ["AGENT RULES"]
    if upper in {"ARCHITECTURE", "PROJECT SUMMARY"}:
        return [upper]
    return [upper]


def get_section(text: str, name: str) -> str:
    sections = parse_sections(text)
    for alias in _section_aliases(name):
        if alias in sections:
            return sections[alias]
    return ""


def _ensure_llm_sections(root: Path) -> None:
    path = llm_txt_path(root)
    if not path.is_file():
        return
    text = path.read_text(encoding="utf-8", errors="replace")
    changed = False
    if "AGENT RULES" not in text:
        rules = (
            "\n================================================================================\n"
            "AGENT RULES\n"
            "================================================================================\n\n"
            "  - Read ONLY llm.txt for repo/architecture questions.\n"
            "  - Do NOT glob/grep the entire repo unless llm.txt is insufficient.\n"
            "  - For deltas, read RECENT FILE CHANGES then open only those paths.\n"
            "  - Use repo_map --depth 3 only when the user explicitly requests a full tree scan.\n"
            "  - Refresh changelog after pulls: arka repo index  (or arka llm sync)\n"
        )
        marker = "================================================================================\nPROJECT SUMMARY"
        if marker in text:
            text = text.replace(marker, rules + marker, 1)
            changed = True
    if "RECENT FILE CHANGES" not in text and "CHANGELOG" not in text:
        changelog = (
            "\n================================================================================\n"
            "RECENT FILE CHANGES (CHANGELOG)\n"
            "================================================================================\n\n"
            "  (no indexed changes yet — run: arka repo index)\n"
        )
        end_marker = "================================================================================\nEND"
        if end_marker in text:
            text = text.replace(end_marker, changelog + end_marker, 1)
            changed = True
    if changed:
        path.write_text(text, encoding="utf-8")


def _summarize_path(status: str, path: str) -> str:
    if status.startswith("A"):
        verb = "added"
    elif status.startswith("D"):
        verb = "deleted"
    elif status.startswith("R"):
        verb = "renamed"
    else:
        verb = "modified"
    hints: list[str] = []
    if "/routing/" in path or path.startswith("routing/"):
        hints.append("routing")
    elif "/agent/" in path or path.startswith("agent/"):
        hints.append("agent skill")
    elif "/fish/" in path or "config.fish" in path:
        hints.append("fish router")
    elif path.endswith(".py"):
        hints.append("python")
    elif path.endswith((".md", ".mdx")):
        hints.append("docs")
    hint = f" ({', '.join(hints)})" if hints else ""
    return f"{verb} {path}{hint}"


def git_changed_since(root: Path, since_commit: str | None) -> list[tuple[str, str]]:
    if since_commit:
        code, out, _ = _run_git(
            ["diff", "--name-status", f"{since_commit}..HEAD"],
            cwd=root,
        )
        if code == 0 and out.strip():
            rows: list[tuple[str, str]] = []
            for line in out.splitlines():
                parts = line.split("\t")
                if len(parts) >= 2:
                    status, rel = parts[0], parts[-1]
                    rows.append((status, rel))
            return rows
    code, out, _ = _run_git(["status", "--porcelain"], cwd=root)
    if code != 0:
        return []
    rows = []
    for line in out.splitlines():
        if len(line) < 4:
            continue
        status = line[:2].strip() or line[0]
        rel = line[3:].strip()
        if rel:
            rows.append((status, rel))
    return rows


def _format_changelog_entries(
    root: Path,
    rows: list[tuple[str, str]],
    *,
    from_commit: str | None,
    to_commit: str,
) -> list[str]:
    if not rows:
        return [f"  [{to_commit[:8]}] no file changes since last index"]
    stamp = datetime.now(timezone.utc).strftime("%Y-%m-%d %H:%M UTC")
    header = f"  --- sync {stamp}"
    if from_commit:
        header += f" ({from_commit[:8]}..{to_commit[:8]})"
    else:
        header += f" (initial → {to_commit[:8]})"
    lines = [header]
    for status, rel in rows[:MAX_CHANGELOG_ENTRIES]:
        lines.append(f"  - {_summarize_path(status, rel)}")
    if len(rows) > MAX_CHANGELOG_ENTRIES:
        lines.append(f"  - … and {len(rows) - MAX_CHANGELOG_ENTRIES} more files")
    return lines


def _upsert_changelog(text: str, new_entries: list[str]) -> str:
    block = "\n".join(new_entries).rstrip() + "\n"
    section_names = ["RECENT FILE CHANGES (CHANGELOG)", "RECENT FILE CHANGES", "CHANGELOG"]
    eq = r"={3,}"
    for section in section_names:
        pattern = (
            rf"({eq}\s*\n{re.escape(section)}\s*\n{eq}\s*\n)"
            rf"(.*?)"
            rf"(?=\n{eq}\s*\n|\Z)"
        )
        match = re.search(pattern, text, flags=re.DOTALL)
        if match:
            prefix, body = match.group(1), match.group(2)
            body = body.strip()
            if body.startswith("(no indexed changes"):
                body = ""
            merged = (body + "\n\n" + block).strip() + "\n"
            return text[: match.start()] + prefix + merged + text[match.end() :]
    return text


def sync_index(root: Path | None = None, *, quiet: bool = False) -> dict[str, object]:
    project = _project_root(str(root) if root else None) if root is not None else _project_root()
    _ensure_llm_sections(project)
    llm_path = llm_txt_path(project)
    if not llm_path.is_file():
        return {"ok": False, "error": f"missing {LLM_TXT}", "root": str(project)}

    head = _head_commit(project)
    if not head:
        return {"ok": False, "error": "not a git repository", "root": str(project)}

    state = get_index_state(project)
    last = state.get("last_commit")
    if isinstance(last, str) and last == head:
        result = {"ok": True, "root": str(project), "commit": head, "changed": 0, "skipped": True}
        if not quiet:
            print(f"llm.txt index up to date ({head[:8]})")
        return result

    rows = git_changed_since(project, last if isinstance(last, str) else None)
    entries = _format_changelog_entries(
        project,
        rows,
        from_commit=last if isinstance(last, str) else None,
        to_commit=head,
    )
    text = read_llm_txt(project)
    updated = _upsert_changelog(text, entries)
    llm_path.write_text(updated, encoding="utf-8")
    save_index_state(project, commit=head)
    result = {
        "ok": True,
        "root": str(project),
        "commit": head,
        "changed": len(rows),
        "skipped": False,
    }
    if not quiet:
        print(f"Updated {LLM_TXT}: {len(rows)} file(s) since last index → {head[:8]}")
    return result


def _grep_llm_for_query(text: str, query: str, *, limit: int = 12) -> list[str]:
    tokens = [t.lower() for t in re.findall(r"[a-zA-Z0-9_.-]{3,}", query) if t.lower() not in {
        "the", "and", "for", "how", "does", "what", "where", "arka", "this", "that", "with", "from",
    }]
    if not tokens:
        return []
    hits: list[str] = []
    for line in text.splitlines():
        low = line.lower()
        if any(tok in low for tok in tokens):
            stripped = line.strip()
            if stripped and stripped not in hits:
                hits.append(stripped)
        if len(hits) >= limit:
            break
    return hits


def query_context(query: str, root: Path | None = None, *, limit_chars: int = MAX_QUERY_CHARS) -> str:
    project = _project_root(str(root) if root else None) if root is not None else _project_root()
    text = read_llm_txt(project)
    if not text:
        return (
            f"No {LLM_TXT} at {llm_txt_path(project)}.\n"
            "Run repo_map for a live tree scan, or add llm.txt to the repo root."
        )

    sections = parse_sections(text)
    parts: list[str] = [f"Repo context ({project.name}) — sourced from {LLM_TXT}"]

    rules = get_section(text, "AGENT RULES")
    if rules:
        parts.append("### AGENT RULES\n" + rules)

    if _CHANGE_KEYWORDS.search(query):
        changelog = (
            get_section(text, "RECENT FILE CHANGES (CHANGELOG)")
            or get_section(text, "CHANGELOG")
        )
        if changelog:
            parts.append("### RECENT FILE CHANGES\n" + changelog)

    if _ARCH_KEYWORDS.search(query) or _CONTEXT_RE.search(query):
        for key in ("ARCHITECTURE", "PROJECT SUMMARY", "QUICK REFERENCE: TOP-LEVEL MODULES"):
            body = sections.get(key, "")
            if body:
                parts.append(f"### {key}\n{body}")

    matches = _grep_llm_for_query(text, query)
    if matches:
        parts.append("### Matching lines\n" + "\n".join(matches))

    out = "\n\n".join(parts).strip()
    if len(out) > limit_chars:
        out = out[:limit_chars].rstrip() + "\n…"
    return out


def wants_repo_context(text: str) -> bool:
    clean = (text or "").strip()
    if not clean:
        return False
    if _EXPLICIT_MAP_RE.search(clean):
        return False
    return bool(_CONTEXT_RE.search(clean) or _BARRIER_RE.search(clean))


def route_command(text: str) -> str:
    if not wants_repo_context(text):
        return ""
    clean = (text or "").strip()
    parts = ["repo_context", "show"]
    if clean:
        parts.append(clean)
    return " ".join(parts)


def cmd_show(args: argparse.Namespace) -> int:
    query = " ".join(args.query).strip() if args.query else ""
    if not query:
        query = "project structure and architecture"
    root = Path(args.path).expanduser().resolve() if args.path else None
    print(query_context(query, root=root))
    return 0


def cmd_index(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser().resolve() if args.path else None
    result = sync_index(root, quiet=bool(args.quiet))
    if not result.get("ok"):
        print(result.get("error", "index failed"), file=sys.stderr)
        return 1
    if args.json:
        print(json.dumps(result, indent=2))
    return 0


def cmd_status(args: argparse.Namespace) -> int:
    state = get_index_state(Path(args.path).expanduser().resolve() if args.path else None)
    if args.json:
        print(json.dumps(state, indent=2))
        return 0
    print(f"root: {state.get('root')}")
    print(f"llm.txt: {state.get('llm_txt')}")
    print(f"last_commit: {state.get('last_commit') or '(none)'}")
    print(f"last_sync: {state.get('last_sync') or '(never)'}")
    return 0


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    raw = list(argv or sys.argv[1:])

    # CLI aliases: arka repo index | arka llm sync
    if raw and raw[0] in ("repo", "llm"):
        group = raw[0]
        rest = raw[1:]
        if group == "repo" and rest[:1] == ["index"]:
            return cmd_index(argparse.Namespace(path=None, quiet="--quiet" in rest, json="--json" in rest))
        if group == "llm" and rest[:1] in (["sync"], ["index"]):
            return cmd_index(argparse.Namespace(path=None, quiet="--quiet" in rest, json="--json" in rest))
        if group == "repo" and rest[:1] in (["status"],):
            return cmd_status(argparse.Namespace(path=None, json="--json" in rest))
        if group == "llm" and not rest:
            rest = ["show"]

    parser = argparse.ArgumentParser(description="Read llm.txt repo context (optimized repo Q&A)")
    sub = parser.add_subparsers(dest="cmd")

    p_route = sub.add_parser("route", help="Map NL to repo_context command")
    p_route.add_argument("text", nargs="+")

    p_show = sub.add_parser("show", help="Return relevant llm.txt sections for a question")
    p_show.add_argument("query", nargs="*", help="Natural language question")
    p_show.add_argument("--path", default=None)
    p_show.set_defaults(func=cmd_show)

    p_index = sub.add_parser("index", help="Append git file deltas to llm.txt changelog")
    p_index.add_argument("--path", default=None)
    p_index.add_argument("--quiet", action="store_true")
    p_index.add_argument("--json", action="store_true")
    p_index.set_defaults(func=cmd_index)

    p_sync = sub.add_parser("sync", help="Alias for index")
    p_sync.add_argument("--path", default=None)
    p_sync.add_argument("--quiet", action="store_true")
    p_sync.add_argument("--json", action="store_true")
    p_sync.set_defaults(func=cmd_index)

    p_status = sub.add_parser("status", help="Show last indexed commit")
    p_status.add_argument("--path", default=None)
    p_status.add_argument("--json", action="store_true")
    p_status.set_defaults(func=cmd_status)

    args = parser.parse_args(raw)
    if args.cmd == "route":
        route = route_command(" ".join(args.text))
        if route:
            print(route)
            return 0
        return 1
    if hasattr(args, "func"):
        return int(args.func(args))
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
