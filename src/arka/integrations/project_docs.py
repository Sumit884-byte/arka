#!/usr/bin/env python3
"""First-person README and blog-post.md synced to repo code changes."""

from __future__ import annotations

import argparse
import json
import re
import sys
from pathlib import Path
from typing import Any

README_NAME = "README.md"
BLOG_NAME = "blog-post.md"
MAX_CONTEXT_CHARS = 14000
MAX_DIFF_CHARS = 6000

_PROJECT_DOCS_TRIGGER = re.compile(
    r"(?i)\b("
    r"project docs?|repo docs?|sync (?:project )?docs?|"
    r"first.?person readme|first.?person blog|"
    r"update readme.*(?:code|changes?|git|repo|commit)|"
    r"update blog.*(?:code|changes?|git|repo|commit)|"
    r"write blog|write a blog|blog post|"
    r"write blog.*first.?person|"
    r"sync readme|auto.?sync docs?|"
    r"docs? (?:from|with|to match) (?:code|changes?|git)"
    r")\b"
)

README_SYSTEM = """You write project README.md files in FIRST PERSON voice.
Rules:
- Use "I built…", "I learned…", "I used…" — never "we" unless quoting someone else.
- Output ONLY the markdown file body (no preamble, no outer code fences).
- Required sections when relevant: intro/what it is, demo/live link, stack, how to run locally.
- Optional: journey/learnings, features list, deploy notes, license.
- Preserve accurate URLs, commands, version numbers, and paths from the repo context.
- Sound like a developer wrote it: direct, concrete, no AI filler or hollow intros.
- If an existing README is provided, improve it in place — do not drop real facts.
"""

BLOG_SYSTEM = """You write blog-post.md dev journal entries in FIRST PERSON voice.
Rules:
- Use "I built…", "I learned…", "I'm proud of…" throughout.
- Output ONLY the article body in GitHub-flavored markdown (no YAML frontmatter).
- Typical sections: What I Built, Demo, Stack, technical highlights, What I'm proud of,
  What I learned, What's next — adapt to the project.
- Preserve accurate links, screenshots, and demo URLs from context.
- Tone: practical builder sharing a project — not marketing fluff.
- Scannable ## headings; bullets and tables where they help.
- If an existing blog post is provided, refresh it to reflect recent code changes.
"""


def repo_root(start: Path | None = None) -> Path:
    cur = (start or Path.cwd()).resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / ".git").exists():
            return candidate
    return cur


def _read_text(path: Path, *, limit: int = MAX_CONTEXT_CHARS) -> str:
    if not path.is_file():
        return ""
    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) > limit:
        return text[:limit].rstrip() + "\n…"
    return text


def _strip_code_fence(text: str) -> str:
    stripped = text.strip()
    match = re.match(r"^```(?:markdown|md)?\s*\n([\s\S]*?)\n```$", stripped)
    if match:
        return match.group(1).strip()
    return stripped


def _llm_write(system: str, user: str, *, skill: str = "project_docs") -> str:
    try:
        from arka.llm.complete import llm_complete

        return llm_complete(system, user, temperature=0.5, task="chat", skill=skill).strip()
    except ImportError:
        from arka.agent.core import _llm

        return _llm(system, user, temperature=0.5, task="chat")


def detect_changes(root: Path, *, since: str | None = None) -> list[tuple[str, str]]:
    try:
        from arka.agent.repo_context import git_changed_since

        return git_changed_since(root, since)
    except ImportError:
        return _git_changed_fallback(root)


def _git_changed_fallback(root: Path) -> list[tuple[str, str]]:
    import subprocess

    try:
        proc = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return []
    if proc.returncode != 0:
        return []
    rows: list[tuple[str, str]] = []
    for line in (proc.stdout or "").splitlines():
        if len(line) < 4:
            continue
        status = line[:2].strip() or line[0]
        rel = line[3:].strip()
        if rel:
            rows.append((status, rel))
    return rows


def _git_diff_summary(root: Path, *, since: str | None = None) -> str:
    import subprocess

    args = ["git", "diff", "--stat"]
    if since:
        args.append(f"{since}..HEAD")
    else:
        args.extend(["HEAD"])
    try:
        proc = subprocess.run(args, cwd=root, capture_output=True, text=True, check=False)
    except OSError:
        return ""
    text = (proc.stdout or "").strip()
    if len(text) > MAX_DIFF_CHARS:
        return text[:MAX_DIFF_CHARS].rstrip() + "\n…"
    return text


def _git_log_oneline(root: Path, n: int = 8) -> str:
    import subprocess

    try:
        proc = subprocess.run(
            ["git", "log", f"-{n}", "--oneline"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
    except OSError:
        return ""
    return (proc.stdout or "").strip()


def _project_hints(root: Path) -> str:
    hints: list[str] = []
    for name in ("package.json", "pyproject.toml", "Cargo.toml", "go.mod", "index.html"):
        path = root / name
        if path.is_file():
            hints.append(f"--- {name} ---\n{_read_text(path, limit=4000)}")
    return "\n\n".join(hints)


def _format_changes(rows: list[tuple[str, str]]) -> str:
    if not rows:
        return "(no uncommitted or recent changes detected)"
    lines = [f"  {status}\t{rel}" for status, rel in rows[:60]]
    if len(rows) > 60:
        lines.append(f"  … and {len(rows) - 60} more files")
    return "\n".join(lines)


def collect_context(root: Path, *, since: str | None = None) -> dict[str, Any]:
    readme = root / README_NAME
    blog = root / BLOG_NAME
    changes = detect_changes(root, since=since)
    return {
        "root": str(root),
        "readme_path": str(readme),
        "blog_path": str(blog),
        "readme_exists": readme.is_file(),
        "blog_exists": blog.is_file(),
        "readme_bytes": readme.stat().st_size if readme.is_file() else 0,
        "blog_bytes": blog.stat().st_size if blog.is_file() else 0,
        "changes": changes,
        "changes_text": _format_changes(changes),
        "diff_stat": _git_diff_summary(root, since=since),
        "recent_commits": _git_log_oneline(root),
        "project_hints": _project_hints(root),
        "existing_readme": _read_text(readme) if readme.is_file() else "",
        "existing_blog": _read_text(blog) if blog.is_file() else "",
    }


def status_payload(root: Path | None = None, *, since: str | None = None) -> dict[str, Any]:
    project = repo_root(root)
    ctx = collect_context(project, since=since)
    return {
        "root": ctx["root"],
        "readme": {
            "path": ctx["readme_path"],
            "exists": ctx["readme_exists"],
            "bytes": ctx["readme_bytes"],
        },
        "blog": {
            "path": ctx["blog_path"],
            "exists": ctx["blog_exists"],
            "bytes": ctx["blog_bytes"],
        },
        "changes_count": len(ctx["changes"]),
        "changes_preview": ctx["changes"][:12],
        "needs_sync": bool(ctx["changes"]) and (ctx["readme_exists"] or ctx["blog_exists"]),
        "recent_commits": ctx["recent_commits"].splitlines()[:5] if ctx["recent_commits"] else [],
    }


def _build_user_prompt(ctx: dict[str, Any], *, doc_kind: str, focus: str = "") -> str:
    parts = [
        f"Project root: {ctx['root']}",
        f"Document: {doc_kind}",
    ]
    if focus:
        parts.append(f"Focus: {focus}")
    if ctx.get("recent_commits"):
        parts.append(f"Recent commits:\n{ctx['recent_commits']}")
    if ctx.get("changes_text"):
        parts.append(f"Changed files:\n{ctx['changes_text']}")
    if ctx.get("diff_stat"):
        parts.append(f"Diff summary:\n{ctx['diff_stat']}")
    if ctx.get("project_hints"):
        parts.append(f"Project files:\n{ctx['project_hints']}")
    try:
        from arka.core.screenshot_paths import docs_screenshot_context

        shot_ctx = docs_screenshot_context(limit=5)
        if shot_ctx:
            parts.append(shot_ctx)
    except ImportError:
        pass
    existing = ctx.get("existing_readme") if doc_kind == "README" else ctx.get("existing_blog")
    if existing:
        parts.append(f"Existing {doc_kind} (revise in place, preserve accurate facts):\n{existing}")
    return "\n\n".join(parts)


def generate_readme(
    root: Path | None = None,
    *,
    since: str | None = None,
    focus: str = "",
) -> tuple[str, dict[str, Any]]:
    project = repo_root(root)
    ctx = collect_context(project, since=since)
    user = _build_user_prompt(ctx, doc_kind="README", focus=focus)
    body = _strip_code_fence(_llm_write(README_SYSTEM, user))
    if not body:
        raise ValueError("LLM returned empty README")
    return body, ctx


def _split_blog_frontmatter(raw: str) -> tuple[str, str]:
    match = re.match(r"^(---\n.*?\n---\n)", raw, re.S)
    if match:
        return match.group(1), raw[match.end() :].strip()
    return "", raw.strip()


def generate_blog(
    root: Path | None = None,
    *,
    since: str | None = None,
    focus: str = "",
) -> tuple[str, dict[str, Any]]:
    project = repo_root(root)
    ctx = collect_context(project, since=since)
    user = _build_user_prompt(ctx, doc_kind="blog post", focus=focus)
    body = _strip_code_fence(_llm_write(BLOG_SYSTEM, user, skill="devto_post"))
    if not body:
        raise ValueError("LLM returned empty blog post")
    blog_path = Path(ctx["blog_path"])
    if blog_path.is_file():
        frontmatter, _ = _split_blog_frontmatter(blog_path.read_text(encoding="utf-8"))
        if frontmatter:
            body = frontmatter + body.strip() + "\n"
    return body, ctx


def write_doc(path: Path, body: str) -> dict[str, object]:
    path.parent.mkdir(parents=True, exist_ok=True)
    overwrote = path.is_file()
    normalized = body.rstrip() + "\n"
    path.write_text(normalized, encoding="utf-8")
    return {
        "path": str(path),
        "bytes": len(normalized.encode("utf-8")),
        "applied": True,
        "overwrote": overwrote,
    }


def update_docs(
    root: Path | None = None,
    *,
    since: str | None = None,
    apply: bool = False,
    readme: bool = True,
    blog: bool = True,
    post: bool = False,
    focus: str = "",
    prompt: str = "",
    assume_defaults: bool = False,
) -> dict[str, Any]:
    project = repo_root(root)
    ctx = collect_context(project, since=since)
    result: dict[str, Any] = {"root": str(project), "applied": apply, "docs": {}}

    if readme:
        readme_body, _ = generate_readme(project, since=since, focus=focus)
        readme_path = Path(ctx["readme_path"])
        entry: dict[str, Any] = {"bytes": len(readme_body.encode("utf-8")), "preview_lines": len(readme_body.splitlines())}
        if apply:
            entry.update(write_doc(readme_path, readme_body))
        else:
            entry["body"] = readme_body
        result["docs"]["readme"] = entry

    if blog and (ctx["blog_exists"] or apply):
        blog_args = argparse.Namespace(
            path=str(project),
            since=since,
            focus=focus,
            prompt=prompt,
            yes=assume_defaults,
            non_interactive=assume_defaults,
            apply=False,
            post=post,
            draft=False,
        )
        blog_focus, meta = _resolve_blog_focus(ctx, blog_args)
        blog_body, _ = generate_blog(project, since=since, focus=blog_focus)
        blog_path = Path(ctx["blog_path"])
        entry: dict[str, Any] = {
            "bytes": len(blog_body.encode("utf-8")),
            "preview_lines": len(blog_body.splitlines()),
        }
        if meta:
            entry["brief"] = meta["brief"]
        if apply:
            entry.update(write_doc(blog_path, blog_body))
        else:
            entry["body"] = blog_body
        result["docs"]["blog"] = entry
        if blog_args.post:
            post = True
    elif blog and not ctx["blog_exists"]:
        result["docs"]["blog"] = {"skipped": True, "reason": f"{BLOG_NAME} not found — use blog --apply to create"}

    if post and apply and result.get("docs", {}).get("blog", {}).get("applied"):
        blog_path = Path(ctx["blog_path"])
        if blog_path.is_file():
            try:
                from arka.integrations.devto_post import cmd_post

                ns = argparse.Namespace(
                    file=str(blog_path),
                    title="",
                    tags="",
                    publish=True,
                    draft=False,
                    dry_run=False,
                )
                result["devto_exit"] = cmd_post(ns)
            except Exception as exc:
                result["devto_error"] = str(exc)

    result["changes_count"] = len(ctx["changes"])
    return result


def route_command(text: str) -> str:
    clean = " ".join((text or "").split()).strip()
    if not clean or not _PROJECT_DOCS_TRIGGER.search(clean):
        return ""
    import shlex as _shlex

    post = bool(re.search(r"(?i)\b(?:post|publish)\b.*\bdev\.?to\b|\bdev\.?to\b.*\b(?:post|publish)\b", clean))
    apply = bool(
        re.search(r"(?i)\b(?:apply|write|save|update|sync|refresh)\b", clean)
        or re.search(r"(?i)\bwrite\s+(?:a\s+)?blog", clean)
    )
    blog_only = bool(re.search(r"(?i)\bblog\b", clean)) and not re.search(r"(?i)\breadme\b", clean)
    readme_only = bool(re.search(r"(?i)\breadme\b", clean)) and not re.search(r"(?i)\bblog\b", clean)

    if blog_only:
        cmd = "project_docs blog"
    elif readme_only:
        cmd = "project_docs readme"
    else:
        cmd = "project_docs update"

    if apply:
        cmd += " --apply"
    if post:
        cmd += " --post"
    if re.search(r"(?i)\b(?:from|since)\s+(?:commit\s+)?([0-9a-f]{6,40})\b", clean):
        m = re.search(r"(?i)\b(?:from|since)\s+(?:commit\s+)?([0-9a-f]{6,40})\b", clean)
        if m:
            cmd += f" --since {m.group(1)}"
    cmd += " --prompt " + _shlex.quote(clean)
    return cmd


def cmd_status(args: argparse.Namespace) -> int:
    payload = status_payload(
        Path(args.path).expanduser() if args.path else None,
        since=args.since,
    )
    if args.json:
        print(json.dumps(payload, indent=2))
        return 0
    print(f"root: {payload['root']}")
    print(f"readme: {payload['readme']['path']} ({'yes' if payload['readme']['exists'] else 'missing'})")
    print(f"blog: {payload['blog']['path']} ({'yes' if payload['blog']['exists'] else 'missing'})")
    print(f"changes: {payload['changes_count']}")
    if payload["changes_preview"]:
        for status, rel in payload["changes_preview"]:
            print(f"  {status}\t{rel}")
    if payload["needs_sync"]:
        print("hint: arka project_docs update --apply")
    return 0


def cmd_readme(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser() if args.path else None
    try:
        body, ctx = generate_readme(root, since=args.since, focus=args.focus or "")
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    path = Path(ctx["readme_path"])
    if args.apply:
        result = write_doc(path, body)
        print(f"Wrote {result['path']} ({result['bytes']} bytes)")
        return 0
    print(json.dumps({"path": str(path), "bytes": len(body.encode()), "body": body}, indent=2))
    return 0


def _resolve_blog_focus(
    ctx: dict[str, Any],
    args: argparse.Namespace,
) -> tuple[str, dict[str, Any] | None]:
    from arka.integrations.blog_interview import prepare_blog_brief

    user_text = str(getattr(args, "prompt", None) or "").strip()
    assume = bool(getattr(args, "yes", False) or getattr(args, "non_interactive", False))
    brief, focus = prepare_blog_brief(
        ctx,
        user_text=user_text,
        focus=str(getattr(args, "focus", None) or ""),
        interactive=not assume,
        assume_defaults=assume,
    )
    meta = {"brief": brief.to_dict(), "focus": focus}
    if brief.publish_devto and not getattr(args, "post", False):
        args.post = True
    return focus, meta


def cmd_blog(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser() if args.path else None
    project = repo_root(root)
    ctx = collect_context(project, since=args.since)
    try:
        focus, meta = _resolve_blog_focus(ctx, args)
        body, ctx = generate_blog(project, since=args.since, focus=focus)
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    path = Path(ctx["blog_path"])
    if args.apply:
        result = write_doc(path, body)
        print(f"Wrote {result['path']} ({result['bytes']} bytes)")
        if meta:
            print(f"brief\t{json.dumps(meta['brief'], ensure_ascii=False)}")
        if args.post:
            from arka.integrations.devto_post import cmd_post

            return cmd_post(
                argparse.Namespace(
                    file=str(path),
                    title="",
                    tags="",
                    publish=not args.draft,
                    draft=bool(args.draft),
                    dry_run=False,
                )
            )
        return 0
    payload: dict[str, Any] = {"path": str(path), "bytes": len(body.encode()), "body": body}
    if meta:
        payload["brief"] = meta["brief"]
    print(json.dumps(payload, indent=2))
    return 0


def cmd_update(args: argparse.Namespace) -> int:
    root = Path(args.path).expanduser() if args.path else None
    readme_only = bool(getattr(args, "readme_only", False))
    blog_only = bool(getattr(args, "blog_only", False))
    try:
        result = update_docs(
            root,
            since=args.since,
            apply=args.apply,
            readme=not blog_only,
            blog=not readme_only,
            post=args.post,
            focus=args.focus or "",
            prompt=str(getattr(args, "prompt", None) or ""),
            assume_defaults=bool(getattr(args, "yes", False) or getattr(args, "non_interactive", False)),
        )
    except (OSError, ValueError) as exc:
        print(f"Error: {exc}", file=sys.stderr)
        return 1
    if args.apply:
        for name, doc in result.get("docs", {}).items():
            if doc.get("applied"):
                print(f"Wrote {doc['path']} ({doc['bytes']} bytes)")
        if result.get("devto_error"):
            print(f"dev.to publish failed: {result['devto_error']}", file=sys.stderr)
            return 1
        if result.get("devto_exit") not in (None, 0):
            return int(result["devto_exit"])
        return 0
    print(json.dumps(result, indent=2))
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    route = route_command(" ".join(args.text))
    if not route:
        return 1
    print(route)
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="arka project_docs",
        description="First-person README and blog-post.md synced to repo changes",
    )
    sub = parser.add_subparsers(dest="cmd")

    def add_common_flags(p: argparse.ArgumentParser) -> None:
        p.add_argument("--path", "-C", help="Project root (default: git root / cwd)")
        p.add_argument("--since", help="Git commit to diff from (default: working tree)")
        p.add_argument("--focus", help="Extra instructions for the LLM")

    p_status = sub.add_parser("status", help="Show docs + pending code changes")
    add_common_flags(p_status)
    p_status.add_argument("--json", action="store_true")
    p_status.set_defaults(handler=cmd_status)

    p_readme = sub.add_parser("readme", help="Generate/update README.md in first person")
    add_common_flags(p_readme)
    p_readme.add_argument("--apply", action="store_true", help="Write README.md")
    p_readme.set_defaults(handler=cmd_readme)

    p_blog = sub.add_parser("blog", help="Generate/update blog-post.md in first person")
    add_common_flags(p_blog)
    p_blog.add_argument("--apply", action="store_true", help="Write blog-post.md")
    p_blog.add_argument("--post", action="store_true", help="Publish to dev.to after writing")
    p_blog.add_argument("--draft", action="store_true", help="dev.to draft (with --post)")
    p_blog.add_argument("--prompt", help="Original NL request (used for blog interview)")
    p_blog.add_argument("--yes", "-y", action="store_true", help="Skip interview questions; use defaults")
    p_blog.add_argument("--non-interactive", action="store_true", help="Same as --yes")
    p_blog.set_defaults(handler=cmd_blog)

    p_update = sub.add_parser("update", help="Update README and blog from code changes")
    add_common_flags(p_update)
    p_update.add_argument("--apply", action="store_true", help="Write files")
    p_update.add_argument("--post", action="store_true", help="Publish blog to dev.to after update")
    p_update.add_argument("--draft", action="store_true", help="dev.to draft (with --post)")
    p_update.add_argument("--readme-only", action="store_true")
    p_update.add_argument("--blog-only", action="store_true")
    p_update.add_argument("--prompt", help="Original NL request (used for blog interview)")
    p_update.add_argument("--yes", "-y", action="store_true", help="Skip interview questions; use defaults")
    p_update.add_argument("--non-interactive", action="store_true", help="Same as --yes")
    p_update.set_defaults(handler=cmd_update)

    p_parse = sub.add_parser("parse", help="Parse NL into project_docs command")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(handler=cmd_parse)

    args = parser.parse_args(list(argv if argv is not None else sys.argv[1:]))
    if not args.cmd:
        parser.print_help()
        return 0

    return int(args.handler(args) or 0)


if __name__ == "__main__":
    try:
        from arka.env import load_env

        load_env()
    except ImportError:
        pass
    raise SystemExit(main())
