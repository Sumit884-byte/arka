#!/usr/bin/env python3
"""Developer tools — CI, PR review, routing audit, and skill scaffolding."""

from __future__ import annotations

import argparse
import json
import re
import shutil
import importlib.util
import sys
from dataclasses import dataclass
from pathlib import Path

from arka.agent.pr_check import _run, collect_diff, detect_base, git_root


def _repo_root(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    root = git_root()
    if root:
        return root
    return Path.cwd().resolve()


def _python() -> str:
    return sys.executable


def _preview(text: str, *, limit: int = 3000) -> str:
    text = (text or "").strip()
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n\n… truncated ({len(text) - limit} chars omitted)"


@dataclass(frozen=True)
class Gate:
    name: str
    command: list[str]


def ci_gates(*, full: bool = False, changed: list[str] | None = None) -> list[Gate]:
    py = _python()
    changed = [path for path in (changed or []) if path.endswith(".py")]
    if changed and not full:
        gates = [Gate("ruff-changed", [py, "-m", "ruff", "check", *changed])]
        tests = [path for path in changed if path.startswith("tests/")]
        if tests:
            gates.append(Gate("pytest-changed", [py, "-m", "pytest", "-q", *tests]))
        return gates
    gates = [
        # Run through the active interpreter so local CI uses the same venv as Arka.
        Gate("ruff", [py, "-m", "ruff", "check", "src/", "tests/"]),
        Gate(
            "pytest",
            [
                py,
                "-m",
                "pytest",
                "-q",
                "--tb=line",
                "tests/test_mcp_server.py",
                "tests/test_openclaw_features.py",
                "tests/test_hermes_features.py",
                "tests/test_project_rules.py",
                "tests/test_clipboard_history.py",
                "tests/test_agent_hub.py",
                "tests/test_llm_fallback.py",
                "tests/test_nl_routing_coverage.py",
                "tests/test_router_github_repo.py",
                "tests/test_pr_check_routing.py",
                "tests/test_repo_health.py",
                "tests/test_convert_media.py::test_route_convert_media",
            ],
        ),
    ]
    if full:
        gates.append(Gate("pytest-full", [py, "-m", "pytest", "-q", "--tb=short"]))
    return gates


def run_ci(root: Path, *, full: bool = False, changed_only: bool = False) -> dict:
    results: list[dict] = []
    changed = []
    if changed_only:
        _, diff_listing, _ = _run(["git", "diff", "--name-only", "HEAD"], cwd=root)
        _, status_listing, _ = _run(["git", "status", "--porcelain"], cwd=root)
        changed = [line.strip() for line in diff_listing.splitlines() if line.strip()]
        changed.extend(line[3:].strip() for line in status_listing.splitlines() if len(line) > 3 and line[3:].strip())
        changed = list(dict.fromkeys(changed))
    for gate in ci_gates(full=full, changed=changed):
        code, out, err = _run(gate.command, cwd=root, timeout=900)
        results.append(
            {
                "name": gate.name,
                "command": gate.command,
                "exit_code": code,
                "stdout": out,
                "stderr": err,
                "ok": code == 0,
            }
        )
        if code != 0:
            break
    return {
        "path": str(root),
        "ok": all(row["ok"] for row in results),
        "results": results,
    }


def ci_text(root: Path, *, full: bool = False, changed_only: bool = False) -> str:
    payload = run_ci(root, full=full, changed_only=changed_only)
    lines = [f"CI run: {root.name}", ""]
    for row in payload["results"]:
        mark = "✓" if row["ok"] else "✗"
        lines.append(f"{mark} {row['name']}: {' '.join(row['command'])}")
        chunk = (row["stdout"] + "\n" + row["stderr"]).strip()
        if chunk:
            for line in _preview(chunk, limit=2200).splitlines()[:20]:
                lines.append(f"  {line[:180]}")
        lines.append("")
    if payload["ok"]:
        lines.append("Summary: all CI gates passed")
    else:
        lines.append("Summary: one or more CI gates failed")
        lines.append("Tip: run `arka ci --fix` to hand the first failure to the goal agent.")
    return "\n".join(lines).strip()


def _security_and_test_gap_hints(diff_text: str, files: list[str]) -> list[str]:
    hints: list[str] = []
    lowered = diff_text.lower()
    if any(re.search(r"(?i)(auth|token|secret|password|key|credential)", f) for f in files):
        hints.append("security: touched auth/secret-related files")
    if re.search(r"(?i)\b(eval|shell=True|subprocess\.call\(|os\.system\(|pickle\.loads\()", lowered):
        hints.append("security: inspect shell/eval or unsafe deserialization")
    if re.search(r"(?i)\b(route|routing|parser|cli)\b", lowered) and not re.search(r"(?i)test_", " ".join(files)):
        hints.append("test-gap: routing/CLI changed without a focused regression test")
    if any(f.endswith(".md") for f in files):
        hints.append("docs: verify docs match the new command surface")
    return hints


def security_scan(root: Path) -> list[dict[str, str | int]]:
    """Find high-signal leaked-secret and unsafe-code patterns, including untracked files."""
    _, listing, _ = _run(["git", "ls-files", "-z"], cwd=root)
    paths = {Path(p) for p in listing.split("\0") if p}
    _, status, _ = _run(["git", "status", "--porcelain"], cwd=root)
    paths.update(Path(line[3:].strip()) for line in status.splitlines() if len(line) > 3 and line[3:].strip())
    patterns = {
        "secret": re.compile(r"(?i)(api[_-]?key|secret|token|password)\s*[:=]\s*['\"][^'\"]{8,}['\"]"),
        "private-key": re.compile(r"-----BEGIN (?:RSA |EC |OPENSSH )?PRIVATE KEY-----"),
        "unsafe-shell": re.compile(r"(?i)\b(?:shell\s*=\s*True|os\.system\(|eval\(|pickle\.loads\()"),
    }
    findings: list[dict[str, str | int]] = []
    for path in sorted(paths):
        if any(part in {".git", "node_modules", ".venv", "venv", "dist", "build"} for part in path.parts):
            continue
        full = root / path
        try:
            text = full.read_text(encoding="utf-8")
        except (OSError, UnicodeDecodeError):
            continue
        for lineno, line in enumerate(text.splitlines(), 1):
            for kind, pattern in patterns.items():
                if pattern.search(line):
                    findings.append({"kind": kind, "file": str(path), "line": lineno, "text": line.strip()[:180]})
    return findings


def cmd_security(args: argparse.Namespace) -> int:
    findings = security_scan(_repo_root(args.path))
    if getattr(args, "json", False):
        print(json.dumps({"ok": not findings, "findings": findings}, indent=2))
    elif not findings:
        print("Security scan: no high-signal findings")
    else:
        print(f"Security scan: {len(findings)} finding(s)")
        for item in findings:
            print(f"- {item['kind']}: {item['file']}:{item['line']} — {item['text']}")
    return 1 if findings else 0


def review_text(root: Path, *, base: str | None = None, staged: bool = False) -> str:
    base_ref = base or detect_base(root, None)
    if staged:
        code, out, err = _run(["git", "diff", "--cached", "--stat"], cwd=root)
        stat = (out or err).strip()
        code2, diff, err2 = _run(["git", "diff", "--cached"], cwd=root)
        text = diff if code2 == 0 else err2
        _, names_out, _ = _run(["git", "diff", "--cached", "--name-only"], cwd=root)
        files = [ln.strip() for ln in names_out.splitlines() if ln.strip()]
        scope = "staged"
    else:
        stat, files = collect_diff(root, base_ref, stat_only=True)
        mb = None
        try:
            from arka.agent.pr_check import merge_base

            mb = merge_base(root, base_ref)
        except ImportError:
            mb = None
        if mb:
            code2, diff, err2 = _run(["git", "diff", mb, "HEAD"], cwd=root)
            text = diff if code2 == 0 else err2
        else:
            text = stat
        scope = f"vs {base_ref}"

    hints = _security_and_test_gap_hints(text, files)
    project_rules = ""
    try:
        from arka.core.project_rules import context_for

        project_rules = context_for("review this diff", root=root, limit_chars=1200)
    except ImportError:
        project_rules = ""

    lines = [f"Review scope: {scope}", ""]
    if files:
        lines.append(f"Files ({len(files)}): " + ", ".join(files[:16]) + ("…" if len(files) > 16 else ""))
        lines.append("")
    lines.append("Diff stat:")
    lines.append(stat or "No diff stat available.")
    lines.append("")
    if project_rules:
        lines.append("Project rules:")
        lines.append(_preview(project_rules, limit=1600))
        lines.append("")
    if hints:
        lines.append("Review hints:")
        for hint in hints:
            lines.append(f"- {hint}")
        lines.append("")
    else:
        lines.append("Review hints: no obvious security or test-gap red flags")
    return "\n".join(lines).strip()


def audit_text(root: Path) -> str:
    sym = root / "src" / "arka" / "routing" / "symbolic.py"
    fish = root / "src" / "arka" / "fish" / "config.fish"
    tests = root / "tests" / "test_nl_routing_coverage.py"

    sym_text = sym.read_text(encoding="utf-8", errors="replace") if sym.is_file() else ""
    fish_text = fish.read_text(encoding="utf-8", errors="replace") if fish.is_file() else ""
    test_text = tests.read_text(encoding="utf-8", errors="replace") if tests.is_file() else ""

    route_fns = sorted(set(re.findall(r"def (route_[a-z0-9_]+)\(", sym_text)))
    fish_hooks = sorted(set(re.findall(r"function (_agent_[a-z0-9_]+|_agent_route_[a-z0-9_]+)", fish_text)))
    test_phrases = sorted(set(re.findall(r'\("([^"]+)",\s*"([a-z0-9_]+)"\)', test_text)))
    test_skills = {skill for _, skill in test_phrases}

    route_skill_map = {
        fn.removeprefix("route_"): fn for fn in route_fns
    }
    fish_skills = {
        name.removeprefix("_agent_").removeprefix("route_")
        for name in fish_hooks
    }

    missing_fish = sorted(k for k in route_skill_map if k not in fish_skills)
    missing_tests = sorted(k for k in route_skill_map if k not in test_skills)
    docs_mentions: set[str] = set()
    docs_root = root / "docs"
    for path in docs_root.rglob("*.mdx"):
        txt = path.read_text(encoding="utf-8", errors="replace")
        for skill in route_skill_map:
            if re.search(rf"\b{re.escape(skill)}\b", txt):
                docs_mentions.add(skill)

    lines = [
        "Route audit",
        f"symbolic routes: {len(route_fns)}",
        f"fish hooks: {len(fish_hooks)}",
        f"coverage cases: {len(test_skills)}",
        "",
    ]
    if missing_fish:
        lines.append("Routes without obvious fish parity:")
        lines.extend(f"- {name}" for name in missing_fish[:20])
        lines.append("")
    if missing_tests:
        lines.append("Routes without dedicated NL coverage:")
        lines.extend(f"- {name}" for name in missing_tests[:20])
        lines.append("")
    if docs_mentions:
        lines.append("Docs mention routed skills:")
        lines.extend(f"- {name}" for name in sorted(docs_mentions)[:20])
        lines.append("")
    if not missing_fish and not missing_tests:
        lines.append("Parity looks good for the current symbolic routes.")
    return "\n".join(lines).strip()


def _skill_path(root: Path, name: str, template: str) -> Path:
    if template == "dev":
        return root / "src" / "arka" / "skills" / name
    return root / name


def scaffold_skill(root: Path, *, name: str, template: str = "dev") -> Path:
    if not re.fullmatch(r"[a-z][a-z0-9_]*", name):
        raise ValueError("skill name must be snake_case lowercase")
    target = _skill_path(root, name, template)
    target.mkdir(parents=True, exist_ok=True)
    manifest = {
        "name": name,
        "type": "python",
        "entry": "run.py",
        "version": "0.1.0",
        "description": f"{name.replace('_', ' ').title()} skill",
        "triggers": [name.replace("_", " ")],
    }
    (target / "skill.json").write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
    (target / "run.py").write_text(
        "#!/usr/bin/env python3\n"
        "from __future__ import annotations\n\n"
        "def main() -> int:\n"
        f"    print('{name} scaffolded')\n"
        "    return 0\n\n"
        "if __name__ == '__main__':\n"
        "    raise SystemExit(main())\n",
        encoding="utf-8",
    )
    (target / "README.md").write_text(
        f"# {name}\n\nScaffolded by `arka skill new {name} --template {template}`.\n",
        encoding="utf-8",
    )
    return target


def route_command(text: str) -> str:
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if not raw:
        return ""
    low = raw.lower()
    if re.search(r"(?i)\b(route audit|route_audit)\b", low):
        return "route_audit"
    if re.search(r"(?i)\barka\s+ci\b", low) or re.search(r"(?i)\brun\s+ci\b", low):
        if re.search(r"(?i)\b(full|all)\b", low):
            return "ci --full"
        if re.search(r"(?i)\bfix\b", low):
            return "ci --fix"
        return "ci"
    if re.search(r"(?i)\barka\s+review\b", low) or re.search(r"(?i)\breview\s+(?:staged|vs\s+main|diff)\b", low):
        if re.search(r"(?i)\bstaged\b", low):
            return "review --staged"
        return "review"
    if re.search(r"(?i)\bskill\s+new\b", low):
        m = re.search(r"(?i)\bskill\s+new\s+([a-z][a-z0-9_]*)", raw)
        if m:
            name = m.group(1)
            template = "dev" if re.search(r"(?i)--template\s+dev\b", raw) else "dev"
            return f"skill new {name} --template {template}"
    if re.search(r"(?i)\b(?:security|secrets?)\s+(?:scan|check|audit)\b", low):
        return "security"
    if re.search(r"(?i)\b(?:developer|dev|repo|project)\s+(?:doctor|preflight|setup\s+check)\b|\b(?:check|run)\s+(?:the\s+)?(?:developer|dev)\s+setup\b|\bdoctor\s+(?:this\s+)?repo\b", low):
        return "dev_doctor"
    if re.search(r"(?i)\b(?:install|setup|enable)\b.*\b(?:arka\s+)?(?:pre[- ]commit|git\s+hooks?)\b", low):
        return "hooks install"
    if re.search(r"(?i)\b(?:restore|undo|remove)\b.*\b(?:arka\s+)?(?:pre[- ]commit|git\s+hooks?)\b", low):
        return "hooks restore"
    if re.search(r"(?i)\bagent\s+hub\s+setup\b|\bsetup\s+cursor\b", low):
        return "agent_hub sync --unify"
    return ""


def cmd_ci(args: argparse.Namespace) -> int:
    root = _repo_root(args.path)
    payload = run_ci(root, full=args.full, changed_only=args.changed)
    if getattr(args, "json", False):
        print(json.dumps({"ok": payload["ok"], "results": [{"name": row["name"], "ok": row["ok"], "exit_code": row["exit_code"]} for row in payload["results"]]}, indent=2))
    else:
        print(ci_text(root, full=args.full, changed_only=args.changed))
    if not payload["ok"] and args.fix:
        try:
            from arka.agent.goal import run_goal

            goal = "Fix the first failing developer-tools CI gate and re-run verification."
            run_goal(goal, max_steps=8, auto_yes=True, auto_continue=True)
        except Exception as exc:
            print(f"goal agent unavailable: {exc}", file=sys.stderr)
            return 1
    return 0 if payload["ok"] else 1


def cmd_review(args: argparse.Namespace) -> int:
    root = _repo_root(args.path)
    report = review_text(root, base=args.base or None, staged=args.staged)
    hints = [line.strip() for line in report.splitlines() if any(marker in line.lower() for marker in ("security:", "test-gap:", "docs:"))]
    failed = bool(hints)
    if getattr(args, "json", False):
        print(json.dumps({"path": str(root), "report": report, "hints": hints, "ok": not failed}, indent=2))
    else:
        print(report)
    if args.fail_on_hints and failed:
        return 1
    return 0


def cmd_audit(args: argparse.Namespace) -> int:
    root = _repo_root(args.path)
    print(audit_text(root))
    return 0


def cmd_doctor(args: argparse.Namespace) -> int:
    root = _repo_root(args.path)
    parity = audit_text(root)
    checks = {
        "git_repo": (root / ".git").exists(),
        "pyproject": (root / "pyproject.toml").is_file(),
        "ci_workflow": any((root / ".github" / "workflows").glob("*.y*ml")),
        "ruff": shutil.which("ruff") is not None or importlib.util.find_spec("ruff") is not None,
        "pytest": shutil.which("pytest") is not None or importlib.util.find_spec("pytest") is not None,
        "route_parity": "missing" not in parity.lower() and "gap" not in parity.lower(),
    }
    if args.json:
        print(json.dumps({"path": str(root), "checks": checks, "ok": all(checks.values())}, indent=2))
    else:
        print(f"Arka developer doctor: {root}")
        for name, ok in checks.items():
            print(f"{'✓' if ok else '✗'} {name}")
        if not checks["ci_workflow"]:
            print("Next: arka github-actions new .")
        if checks["ci_workflow"]:
            print("Next: arka ci --full")
        if not checks["route_parity"]:
            print("Next: arka route audit")
    return 0 if all(checks.values()) else 1


def cmd_skill_new(args: argparse.Namespace) -> int:
    root = _repo_root(args.path)
    target = scaffold_skill(root, name=args.name, template=args.template)
    if args.guided:
        description = input("Description (optional): ").strip()
        triggers = input("Natural-language triggers (comma-separated): ").strip()
        manifest_path = target / "skill.json"
        manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
        if description:
            manifest["description"] = description
        if triggers:
            manifest["triggers"] = [item.strip() for item in triggers.split(",") if item.strip()]
        manifest["guided"] = True
        manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        existing: dict[str, str] = {}
        for other in (root / "src" / "arka" / "skills").glob("*/skill.json"):
            if other.parent == target:
                continue
            try:
                data = json.loads(other.read_text(encoding="utf-8"))
            except (OSError, ValueError):
                continue
            for trigger in data.get("triggers", []):
                existing[str(trigger).strip().lower()] = str(data.get("name") or other.parent.name)
        collisions = sorted({(trigger.lower(), existing[trigger.lower()]) for trigger in manifest.get("triggers", []) if trigger.lower() in existing})
        if collisions:
            for trigger, owner in collisions:
                print(f"trigger_collision\t{trigger}\t{owner}")
            suggested = f"ask the AI teammate to use the {manifest['name'].replace('_', ' ')} skill"
            print(f"ai_trigger_suggestion\t{suggested}")
            manifest["suggested_ai_trigger"] = suggested
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        else:
            suggested = f"ask the AI teammate to use the {manifest['name'].replace('_', ' ')} skill"
            print(f"ai_trigger_suggestion\t{suggested}")
            manifest["suggested_ai_trigger"] = suggested
            manifest_path.write_text(json.dumps(manifest, indent=2) + "\n", encoding="utf-8")
        (target / "TEST_PLAN.md").write_text("# Test plan\n\n- Add a symbolic route regression test.\n- Add success and failure execution tests.\n", encoding="utf-8")
        print("guided\tmanifest and TEST_PLAN.md created")
    print(str(target))
    return 0


def cmd_hooks(args: argparse.Namespace) -> int:
    root = _repo_root(args.path)
    hook = root / ".git" / "hooks" / "pre-commit"
    backup = hook.with_name("pre-commit.arka-backup")
    if args.action == "restore":
        if not backup.is_file():
            print(f"No Arka hook backup found: {backup}")
            return 1
        hook.write_bytes(backup.read_bytes())
        hook.chmod(0o755)
        print(f"Restored {hook}")
        return 0
    if args.action == "status":
        installed = hook.is_file() and "arka ci --changed" in hook.read_text(errors="replace")
        print(f"pre-commit: {'installed' if installed else 'not installed'}")
        if backup.is_file():
            print(f"backup: {backup}")
        return 0
    if hook.exists() and not args.force:
        print(f"Hook exists: {hook}; use --force to replace it")
        return 2
    if hook.exists() and args.force:
        hook.with_name("pre-commit.arka-backup").write_bytes(hook.read_bytes())
    hook.parent.mkdir(parents=True, exist_ok=True)
    hook.write_text("#!/bin/sh\nset -eu\nprintf '%s\\n' 'Arka pre-commit: incremental CI'\nif command -v arka >/dev/null 2>&1; then\n  ARKA='arka'\nelse\n  ARKA='python -m arka'\nfi\n$ARKA ci --changed\n$ARKA review --staged --fail-on-hints\n", encoding="utf-8")
    hook.chmod(0o755)
    print(f"Installed {hook}")
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Arka developer-tools commands")
    sub = parser.add_subparsers(dest="cmd")

    p_ci = sub.add_parser("ci", help="Run local CI gates mirrored from GitHub Actions")
    p_ci.add_argument("--full", action="store_true")
    p_ci.add_argument("--fix", action="store_true")
    p_ci.add_argument("--json", action="store_true", help="Emit machine-readable gate results")
    p_ci.add_argument("--changed", action="store_true", help="Lint changed Python files and run changed tests")
    p_ci.add_argument("path", nargs="?", default=None)
    p_ci.set_defaults(func=cmd_ci)

    p_review = sub.add_parser("review", help="Review staged changes or diff vs main")
    p_review.add_argument("--staged", action="store_true")
    p_review.add_argument("--base", default="")
    p_review.add_argument("--fail-on-hints", action="store_true", help="Fail when review reports security, test-gap, or docs hints")
    p_review.add_argument("--json", action="store_true", help="Emit structured review output")
    p_review.add_argument("path", nargs="?", default=None)
    p_review.set_defaults(func=cmd_review)

    p_audit = sub.add_parser("route-audit", help="Audit symbolic, fish, and test parity")
    p_audit.add_argument("path", nargs="?", default=None)
    p_audit.set_defaults(func=cmd_audit)

    p_security = sub.add_parser("security", help="Scan tracked files for secrets and unsafe patterns")
    p_security.add_argument("--json", action="store_true")
    p_security.add_argument("path", nargs="?", default=None)
    p_security.set_defaults(func=cmd_security)

    p_hooks = sub.add_parser("hooks", help="Install or inspect repository Git hooks")
    hooks_sub = p_hooks.add_subparsers(dest="action", required=True)
    p_install = hooks_sub.add_parser("install")
    p_install.add_argument("--force", action="store_true")
    p_install.add_argument("path", nargs="?", default=None)
    p_install.set_defaults(func=cmd_hooks)
    p_status = hooks_sub.add_parser("status")
    p_status.add_argument("path", nargs="?", default=None)
    p_status.add_argument("--force", action="store_true")
    p_status.set_defaults(func=cmd_hooks)
    p_restore = hooks_sub.add_parser("restore")
    p_restore.add_argument("path", nargs="?", default=None)
    p_restore.add_argument("--force", action="store_true")
    p_restore.set_defaults(func=cmd_hooks)

    p_doctor = sub.add_parser("doctor", help="Preflight repository and developer-tool setup")
    p_doctor.add_argument("--json", action="store_true")
    p_doctor.add_argument("path", nargs="?", default=None)
    p_doctor.set_defaults(func=cmd_doctor)

    p_skill = sub.add_parser("skill", help="Skill scaffolding commands")
    skill_sub = p_skill.add_subparsers(dest="skill_cmd")
    p_new = skill_sub.add_parser("new", help="Scaffold a new skill")
    p_new.add_argument("name")
    p_new.add_argument("--template", default="dev")
    p_new.add_argument("--guided", action="store_true", help="ask for description and NL triggers")
    p_new.add_argument("path", nargs="?", default=None)
    p_new.set_defaults(func=cmd_skill_new)

    p_route = sub.add_parser("route", help="Map NL to dev-tools commands")
    p_route.add_argument("text", nargs="+")

    args = parser.parse_args(argv)
    if args.cmd == "route":
        line = route_command(" ".join(args.text))
        if line:
            print(line)
            return 0
        return 1
    if hasattr(args, "func"):
        return int(args.func(args))
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
