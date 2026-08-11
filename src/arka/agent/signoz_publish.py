#!/usr/bin/env python3
"""One-shot SigNoz submission publish: git push, Vercel deploy, signoz/BLOG.md update."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import shutil
import subprocess
import sys
from dataclasses import asdict, dataclass, field
from pathlib import Path
from typing import Any, Callable

BLOG_REL_PATH = Path("signoz/BLOG.md")
DEFAULT_VERCEL_DIR = "landing"

_PUBLISH_TRIGGER = re.compile(
    r"(?i)\b(?:signoz[\s_-]*publish|publish[\s_-]*signoz)\b"
    r"|\bpush\b.*\b(?:github|vercel)\b.*\bsignoz\b"
    r"|\bsignoz\b.*\b(?:push|deploy|publish)\b.*\b(?:github|vercel|blog)\b"
    r"|\bone[\s-]shot\b.*\b(?:github|vercel)\b.*\bsignoz\b"
)

BLOG_SYSTEM = """You maintain signoz/BLOG.md for the Arka + SigNoz hackathon submission (Track 01).
Rules:
- Output ONLY the full markdown file body (no YAML frontmatter).
- Preserve the document's overall structure: title, demo links, What is Arka, problem/solution,
  How we use SigNoz, reproduce steps, tech stack, links, AI disclosure.
- Keep existing image URLs and release links when still relevant.
- Integrate the user's topic/update naturally — do not drop major sections unless obsolete.
- Tone: practical, developer-focused, hackathon submission narrative.
- Include markdown tables and code blocks where appropriate.
- Keep the AI disclosure section at the end.
"""


def repo_root(start: Path | None = None) -> Path:
    cur = (start or Path.cwd()).resolve()
    for candidate in (cur, *cur.parents):
        if (candidate / ".git").exists():
            return candidate
    return cur


def blog_path(root: Path | None = None) -> Path:
    return (root or repo_root()) / BLOG_REL_PATH


def _run(
    cmd: list[str],
    *,
    cwd: Path,
    capture: bool = False,
    check: bool = False,
) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        cmd,
        cwd=cwd,
        capture_output=capture,
        text=True,
        check=check,
    )


def git_run(args: list[str], *, cwd: Path, capture: bool = True) -> subprocess.CompletedProcess[str]:
    return _run(["git", *args], cwd=cwd, capture=capture)


def which_bin(name: str) -> str | None:
    return shutil.which(name)


@dataclass
class Preflight:
    root: str
    branch: str
    remote: str
    has_changes: bool
    git: bool
    gh: bool
    vercel: bool
    blog_exists: bool
    blog_path: str
    vercel_dir: str
    errors: list[str] = field(default_factory=list)
    warnings: list[str] = field(default_factory=list)

    def ok_for_run(self) -> bool:
        return self.git and bool(self.remote) and not self.errors


def git_branch(root: Path) -> str:
    proc = git_run(["rev-parse", "--abbrev-ref", "HEAD"], cwd=root)
    return (proc.stdout or "HEAD").strip() if proc.returncode == 0 else "HEAD"


def git_remote(root: Path) -> str:
    proc = git_run(["remote"], cwd=root)
    if proc.returncode != 0:
        return ""
    remotes = [line.strip() for line in (proc.stdout or "").splitlines() if line.strip()]
    if "origin" in remotes:
        return "origin"
    return remotes[0] if remotes else ""


def git_porcelain(root: Path) -> str:
    proc = git_run(["status", "--porcelain"], cwd=root)
    return (proc.stdout or "").strip() if proc.returncode == 0 else ""


def git_diff_stat(root: Path) -> str:
    proc = git_run(["diff", "--stat", "HEAD"], cwd=root)
    if proc.returncode != 0:
        return ""
    staged = git_run(["diff", "--cached", "--stat"], cwd=root)
    parts = []
    if (proc.stdout or "").strip():
        parts.append("Unstaged/staged vs HEAD:\n" + proc.stdout.strip())
    if staged.returncode == 0 and (staged.stdout or "").strip():
        parts.append("Staged:\n" + staged.stdout.strip())
    return "\n\n".join(parts)[:8000]


def git_log_oneline(root: Path, n: int = 5) -> str:
    proc = git_run(["log", f"-{n}", "--oneline"], cwd=root)
    return (proc.stdout or "").strip() if proc.returncode == 0 else ""


def preflight(
    root: Path | None = None,
    *,
    vercel_dir: str = DEFAULT_VERCEL_DIR,
) -> Preflight:
    root = (root or repo_root()).resolve()
    errors: list[str] = []
    warnings: list[str] = []

    git_ok = which_bin("git") is not None and (root / ".git").is_dir()
    if not git_ok:
        errors.append("git not available or .git not found — run from the Arka repo root")

    remote = git_remote(root) if git_ok else ""
    if git_ok and not remote:
        errors.append("no git remote configured — add origin: git remote add origin <url>")

    gh_ok = which_bin("gh") is not None
    if not gh_ok:
        warnings.append("gh CLI not found — push uses git only (install: brew install gh)")

    vercel_ok = which_bin("vercel") is not None
    if not vercel_ok:
        warnings.append(
            "vercel CLI not found — install: npm i -g vercel && vercel login"
        )

    vdir = root / vercel_dir
    if not vdir.is_dir():
        warnings.append(f"vercel deploy dir missing: {vdir}")

    blog = blog_path(root)
    porcelain = git_porcelain(root) if git_ok else ""

    return Preflight(
        root=str(root),
        branch=git_branch(root) if git_ok else "",
        remote=remote,
        has_changes=bool(porcelain),
        git=git_ok,
        gh=gh_ok,
        vercel=vercel_ok,
        blog_exists=blog.is_file(),
        blog_path=str(blog),
        vercel_dir=str(vdir),
        errors=errors,
        warnings=warnings,
    )


def suggest_commit_message(root: Path, *, topic: str = "") -> str:
    if topic.strip():
        clean = topic.strip().rstrip(".")
        return f"Update SigNoz submission: {clean}"
    stat = git_diff_stat(root)
    if stat:
        first = stat.splitlines()[0].strip()
        if first and len(first) < 120:
            return f"Update SigNoz hackathon materials ({first})"
    recent = git_log_oneline(root, 1)
    if recent:
        return f"Publish SigNoz updates (after {recent.split(maxsplit=1)[0]})"
    return "Update SigNoz hackathon submission"


def generate_blog_markdown(
    *,
    topic: str = "",
    content_hint: str = "",
    existing: str = "",
    diff_summary: str = "",
) -> str:
    user_parts = []
    if topic:
        user_parts.append(f"Topic / update focus:\n{topic.strip()}")
    if content_hint:
        user_parts.append(f"Additional content:\n{content_hint.strip()[:12000]}")
    if diff_summary:
        user_parts.append(f"Recent git changes:\n{diff_summary[:6000]}")
    if existing:
        user_parts.append(f"Current BLOG.md (update in place):\n{existing[:20000]}")
    else:
        user_parts.append("No existing BLOG.md — create a full hackathon submission blog.")

    user = "\n\n".join(user_parts)
    body = ""
    try:
        from arka.llm.cli import llm_complete

        body = (
            llm_complete(BLOG_SYSTEM, user, 0.35, task="summarize", skill="signoz_publish") or ""
        ).strip()
    except ImportError:
        pass

    if body and len(body) > 400:
        return body

    # Fallback: append update section to existing blog
    stamp = topic or "Latest submission updates"
    section = [
        "",
        "---",
        "",
        f"## {stamp}",
        "",
        content_hint.strip() if content_hint else "Updated hackathon materials and deployment.",
        "",
    ]
    if diff_summary:
        section.extend(["### Changed files", "", "```", diff_summary[:2000], "```", ""])
    if existing:
        return existing.rstrip() + "\n" + "\n".join(section)
    return "\n".join(
        [
            f"# {stamp}",
            "",
            "Arka + SigNoz hackathon submission update.",
            "",
            *section,
        ]
    ).strip() + "\n"


def write_blog(
    root: Path,
    content: str,
    *,
    dry_run: bool = False,
) -> Path:
    path = blog_path(root)
    if dry_run:
        return path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content if content.endswith("\n") else content + "\n", encoding="utf-8")
    return path


def resolve_commit_message(args: argparse.Namespace, root: Path) -> str:
    explicit = (getattr(args, "message", None) or getattr(args, "m", None) or "").strip()
    if explicit:
        return explicit
    if getattr(args, "yes", False):
        topic = (getattr(args, "topic", None) or "").strip()
        return suggest_commit_message(root, topic=topic)
    raise SystemExit(
        "Commit message required: pass -m/--message or --yes to auto-generate from changes."
    )


def git_stage_commit_push(
    root: Path,
    message: str,
    *,
    dry_run: bool = False,
    remote: str = "origin",
    branch: str | None = None,
    paths: list[str] | None = None,
) -> dict[str, Any]:
    branch = branch or git_branch(root)
    plan: dict[str, Any] = {
        "stage": paths or ["-A"],
        "commit": message,
        "push": [remote, branch],
    }
    if dry_run:
        plan["dry_run"] = True
        return plan

    stage_args = ["add", *(paths or ["-A"])]
    proc = git_run(stage_args, cwd=root)
    if proc.returncode != 0:
        raise SystemExit(f"git add failed: {(proc.stderr or proc.stdout or '').strip()}")

    if not git_porcelain(root):
        plan["commit_skipped"] = "no changes to commit"
    else:
        proc = git_run(
            ["commit", "-m", message],
            cwd=root,
        )
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or "").strip()
            raise SystemExit(f"git commit failed: {detail}")
        plan["committed"] = True

    proc = git_run(["push", remote, branch], cwd=root, capture=False)
    if proc.returncode != 0:
        raise SystemExit(f"git push {remote} {branch} failed (exit {proc.returncode})")
    plan["pushed"] = True
    return plan


def vercel_deploy(
    root: Path,
    *,
    vercel_dir: str = DEFAULT_VERCEL_DIR,
    production: bool = False,
    dry_run: bool = False,
) -> dict[str, Any]:
    if not which_bin("vercel"):
        raise SystemExit(
            "vercel CLI not found.\n"
            "  Install: npm i -g vercel\n"
            "  Auth: vercel login\n"
            "  Link project: cd landing && vercel link"
        )
    deploy_root = root / vercel_dir
    if not deploy_root.is_dir():
        raise SystemExit(f"Vercel deploy directory not found: {deploy_root}")

    cmd = ["vercel"]
    if production:
        cmd.append("--prod")
    cmd.extend(["--yes"])

    plan = {"command": cmd, "cwd": str(deploy_root), "production": production}
    if dry_run:
        plan["dry_run"] = True
        return plan

    proc = _run(cmd, cwd=deploy_root, capture=True)
    plan["exit_code"] = proc.returncode
    plan["stdout"] = (proc.stdout or "").strip()[-4000:]
    plan["stderr"] = (proc.stderr or "").strip()[-2000:]
    if proc.returncode != 0:
        raise SystemExit(
            f"vercel deploy failed (exit {proc.returncode}): "
            f"{(proc.stderr or proc.stdout or '').strip()[:500]}"
        )
    plan["deployed"] = True
    return plan


@dataclass
class PublishPlan:
    preflight: Preflight
    commit_message: str = ""
    blog: dict[str, Any] = field(default_factory=dict)
    git: dict[str, Any] = field(default_factory=dict)
    vercel: dict[str, Any] = field(default_factory=dict)
    dry_run: bool = False

    def to_dict(self) -> dict[str, Any]:
        payload = asdict(self)
        payload["preflight"] = asdict(self.preflight)
        return payload


def build_plan(args: argparse.Namespace, root: Path | None = None) -> PublishPlan:
    root = (root or repo_root()).resolve()
    pf = preflight(root, vercel_dir=getattr(args, "vercel_dir", None) or DEFAULT_VERCEL_DIR)
    dry_run = bool(getattr(args, "dry_run", False))
    skip_git = bool(getattr(args, "skip_git", False))
    skip_deploy = bool(getattr(args, "skip_deploy", False))
    skip_blog = bool(getattr(args, "skip_blog", False))

    plan = PublishPlan(preflight=pf, dry_run=dry_run)

    if not skip_blog:
        blog_file = blog_path(root)
        existing = blog_file.read_text(encoding="utf-8") if blog_file.is_file() else ""
        content_path = (getattr(args, "content", None) or "").strip()
        topic = (getattr(args, "topic", None) or "").strip()
        generate = bool(getattr(args, "generate_blog", False) or topic or getattr(args, "yes", False))

        new_content = ""
        if content_path:
            src = Path(content_path).expanduser()
            if not src.is_file():
                raise SystemExit(f"Blog content file not found: {src}")
            new_content = src.read_text(encoding="utf-8")
            plan.blog = {"mode": "file", "source": str(src), "bytes": len(new_content)}
        elif generate:
            hint = (getattr(args, "content_text", None) or "").strip()
            diff = git_diff_stat(root) if pf.git else ""
            new_content = generate_blog_markdown(
                topic=topic,
                content_hint=hint,
                existing=existing,
                diff_summary=diff,
            )
            plan.blog = {
                "mode": "generate",
                "topic": topic,
                "words": len(new_content.split()),
            }
        else:
            plan.blog = {"mode": "keep", "path": str(blog_file)}

        if new_content and not dry_run:
            written = write_blog(root, new_content, dry_run=False)
            plan.blog["written"] = str(written)
        elif new_content:
            plan.blog["would_write"] = str(blog_file)
            plan.blog["preview_words"] = len(new_content.split())

    if not skip_git:
        if not pf.git:
            raise SystemExit("Git not available — cannot push.")
        if not pf.remote:
            raise SystemExit("No git remote — configure origin before pushing.")
        message = resolve_commit_message(args, root)
        plan.commit_message = message
        paths = [str(BLOG_REL_PATH)] if skip_blog else None
        if getattr(args, "all_files", False):
            paths = None
        plan.git = git_stage_commit_push(
            root,
            message,
            dry_run=True,
            remote=pf.remote,
            branch=pf.branch,
            paths=paths,
        )

    if not skip_deploy:
        plan.vercel = vercel_deploy(
            root,
            vercel_dir=getattr(args, "vercel_dir", None) or DEFAULT_VERCEL_DIR,
            production=bool(getattr(args, "production", False)),
            dry_run=True,
        )

    return plan


def run_publish(args: argparse.Namespace, root: Path | None = None) -> PublishPlan:
    root = (root or repo_root()).resolve()
    dry_run = bool(getattr(args, "dry_run", False))
    yes = bool(getattr(args, "yes", False))

    if not yes and not dry_run:
        plan = build_plan(args, root)
        print("Signoz publish plan (preview — pass --yes to execute, --dry-run to simulate):")
        print(json.dumps(plan.to_dict(), indent=2))
        if plan.preflight.warnings:
            print("\nWarnings:", file=sys.stderr)
            for w in plan.preflight.warnings:
                print(f"  • {w}", file=sys.stderr)
        return plan

    pf = preflight(root, vercel_dir=getattr(args, "vercel_dir", None) or DEFAULT_VERCEL_DIR)
    if pf.errors:
        raise SystemExit("Preflight failed:\n  • " + "\n  • ".join(pf.errors))

    plan = PublishPlan(preflight=pf, dry_run=dry_run)
    skip_git = bool(getattr(args, "skip_git", False))
    skip_deploy = bool(getattr(args, "skip_deploy", False))
    skip_blog = bool(getattr(args, "skip_blog", False))

    # 1. Blog
    if not skip_blog:
        blog_file = blog_path(root)
        existing = blog_file.read_text(encoding="utf-8") if blog_file.is_file() else ""
        content_path = (getattr(args, "content", None) or "").strip()
        topic = (getattr(args, "topic", None) or "").strip()
        generate = bool(getattr(args, "generate_blog", False) or topic or yes)

        new_content = ""
        if content_path:
            src = Path(content_path).expanduser()
            if not src.is_file():
                raise SystemExit(f"Blog content file not found: {src}")
            new_content = src.read_text(encoding="utf-8")
            plan.blog = {"mode": "file", "source": str(src)}
        elif generate:
            new_content = generate_blog_markdown(
                topic=topic,
                content_hint=(getattr(args, "content_text", None) or "").strip(),
                existing=existing,
                diff_summary=git_diff_stat(root),
            )
            plan.blog = {"mode": "generate", "topic": topic, "words": len(new_content.split())}
        else:
            plan.blog = {"mode": "keep"}

        if new_content:
            if dry_run:
                plan.blog["would_write"] = str(blog_file)
            else:
                plan.blog["written"] = str(write_blog(root, new_content))

    # 2. Git
    if not skip_git:
        message = resolve_commit_message(args, root)
        plan.commit_message = message
        paths = None if getattr(args, "all_files", False) else [str(BLOG_REL_PATH)]
        if not skip_blog and paths:
            # include blog + any other changes when blog was updated
            paths = None
        plan.git = git_stage_commit_push(
            root,
            message,
            dry_run=dry_run,
            remote=pf.remote,
            branch=pf.branch,
            paths=paths,
        )

    # 3. Vercel
    if not skip_deploy:
        plan.vercel = vercel_deploy(
            root,
            vercel_dir=getattr(args, "vercel_dir", None) or DEFAULT_VERCEL_DIR,
            production=bool(getattr(args, "production", False)),
            dry_run=dry_run,
        )

    return plan


def build_signoz_publish_argv_from_nl(text: str) -> list[str]:
    t = (text or "").strip()
    if not t or not _PUBLISH_TRIGGER.search(t):
        return []
    argv: list[str] = []
    if re.search(r"(?i)\bdry[- ]?run\b", t):
        argv.append("--dry-run")
    if re.search(r"(?i)\b(?:production|prod)\b", t):
        argv.append("--production")
    if re.search(r"(?i)\bskip\b.*\bblog\b", t):
        argv.append("--skip-blog")
    if re.search(r"(?i)\bskip\b.*\b(?:deploy|vercel)\b", t):
        argv.append("--skip-deploy")
    m = re.search(r"(?i)\b(?:topic|about|update)\s*[:\-]\s*(.+?)(?:\s+and\s+|\s+then\s+|$)", t)
    if not m:
        m = re.search(r"(?i)\b(?:topic|about|update)\s+(?!blog\b)(.+?)(?:\s+and\s+|\s+then\s+|$)", t)
    if m:
        argv.extend(["--topic", m.group(1).strip(" .\"'")])
    m = re.search(r'(?i)\bcommit(?:\s+message)?\s+[:\-]?\s*["\u201c](.+?)["\u201d]', t)
    if m:
        argv.extend(["-m", m.group(1)])
    elif re.search(r"(?i)\b(?:go ahead|do it|publish now|ship it)\b", t):
        argv.append("--yes")
    if re.search(r"(?i)\b(?:generate|write|update)\s+blog\b", t) or re.search(r"(?i)\bblog\b", t):
        if "--topic" not in argv and "--generate-blog" not in argv:
            argv.append("--generate-blog")
    return argv


def nl_to_argv(text: str) -> list[str]:
    return build_signoz_publish_argv_from_nl(text)


def cmd_check(_args: argparse.Namespace) -> int:
    pf = preflight()
    print(json.dumps(asdict(pf), indent=2))
    if pf.errors:
        print("\nFix the errors above before publishing.", file=sys.stderr)
        return 1
    if pf.warnings:
        print("\nWarnings:", file=sys.stderr)
        for w in pf.warnings:
            print(f"  • {w}", file=sys.stderr)
    print("\nPreflight OK — run: arka signoz_publish --yes -m \"your message\"")
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    text = " ".join(args.text)
    argv = nl_to_argv(text)
    print(json.dumps({"argv": argv, "command": "signoz_publish " + " ".join(shlex.quote(a) for a in argv)}, indent=2))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    plan = run_publish(args)
    print(json.dumps(plan.to_dict(), indent=2))
    if plan.preflight.errors:
        return 1
    if not getattr(args, "yes", False) and not getattr(args, "dry_run", False):
        return 0
    if plan.dry_run:
        print("\nDry run complete — no changes made.", file=sys.stderr)
    else:
        print("\nPublish complete.", file=sys.stderr)
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="One-shot SigNoz publish: update signoz/BLOG.md, push to GitHub, deploy to Vercel",
    )
    sub = p.add_subparsers(dest="cmd")

    p_run = sub.add_parser("run", help="Run publish workflow (default)")
    _add_run_flags(p_run)
    p.set_defaults(cmd="run")

    p_check = sub.add_parser("check", help="Preflight: git, gh, vercel, blog path")
    p_check.set_defaults(func=cmd_check)

    p_parse = sub.add_parser("parse", help="Parse natural language into signoz_publish argv")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)

    _add_run_flags(p)
    return p


def _add_run_flags(p: argparse.ArgumentParser) -> None:
    p.add_argument("-m", "--message", help="Git commit message (required unless --yes)")
    p.add_argument("--topic", help="Blog update topic — triggers LLM refresh of signoz/BLOG.md")
    p.add_argument("--content", help="Path to markdown file to write as signoz/BLOG.md")
    p.add_argument("--content-text", help="Extra hint text for blog generation")
    p.add_argument("--generate-blog", action="store_true", help="Generate blog from git diff / topic")
    p.add_argument("--skip-blog", action="store_true")
    p.add_argument("--skip-git", action="store_true")
    p.add_argument("--skip-deploy", action="store_true")
    p.add_argument("--vercel-dir", default=DEFAULT_VERCEL_DIR, help="Directory for vercel deploy (default: landing)")
    p.add_argument("--production", action="store_true", help="vercel --prod")
    p.add_argument("--all-files", action="store_true", help="Stage all repo changes (default: blog + unstaged)")
    p.add_argument("--dry-run", action="store_true", help="Simulate without git commit/push or vercel deploy")
    p.add_argument("--yes", "-y", action="store_true", help="Execute (required for destructive steps)")
    p.add_argument("--json", action="store_true", help="JSON output only")
    p.set_defaults(func=cmd_run)


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if argv and argv[0] not in ("run", "check", "parse", "-h", "--help") and not argv[0].startswith("-"):
        argv = ["run", *argv]
    parser = build_parser()
    args = parser.parse_args(argv)
    func: Callable[[argparse.Namespace], int] | None = getattr(args, "func", None)
    if func is None:
        parser.print_help()
        return 0
    return func(args)


if __name__ == "__main__":
    raise SystemExit(main())
