#!/usr/bin/env python3
"""Quick repo health scan — detect and run lint/test checks for the current project."""

from __future__ import annotations

import argparse
import json
import re
import subprocess
from dataclasses import dataclass
from pathlib import Path

try:
    from arka.agent.pr_check import _run, git_root
    from arka.paths import load_env_file

    load_env_file()
except ImportError:

    def load_env_file() -> None:
        pass

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

    def _run(cmd, *, cwd=None, timeout=120):
        try:
            proc = subprocess.run(
                cmd,
                cwd=str(cwd) if cwd else None,
                capture_output=True,
                text=True,
                timeout=timeout,
            )
            return proc.returncode, proc.stdout or "", proc.stderr or ""
        except Exception as exc:
            return 1, "", str(exc)


_TRIGGER_RE = re.compile(
    r"(?i)\b("
    r"repo\s+health|project\s+health|health\s+check|"
    r"run\s+(?:project\s+)?tests?|quick\s+(?:test|lint|check)|"
    r"check\s+(?:tests?|lint|coverage|repo|project)"
    r")\b"
)
_RUN_RE = re.compile(r"(?i)\b(?:run|execute|start)\b.*\b(?:tests?|lint|checks?)\b")
_SCAN_RE = re.compile(r"(?i)\b(?:scan|detect|what)\b.*\b(?:checks?|tests?|tools?)\b")


@dataclass(frozen=True)
class Check:
    name: str
    command: list[str]
    category: str
    detail: str = ""


def _project_root(explicit: str | None = None) -> Path:
    if explicit:
        return Path(explicit).expanduser().resolve()
    root = git_root()
    if root:
        return root
    return Path.cwd().resolve()


def _has_file(root: Path, name: str) -> bool:
    return (root / name).is_file()


def _has_dir(root: Path, name: str) -> bool:
    return (root / name).is_dir()


def detect_checks(root: Path) -> list[Check]:
    checks: list[Check] = []
    pyproject = _has_file(root, "pyproject.toml")
    package_json = _has_file(root, "package.json")
    makefile = _has_file(root, "Makefile")
    cargo = _has_file(root, "Cargo.toml")
    go_mod = _has_file(root, "go.mod")

    if pyproject or _has_dir(root, "tests") or _has_dir(root, "test"):
        if shutil_which("pytest"):
            checks.append(Check("pytest", ["pytest", "-q", "--tb=no", "-x"], "test"))
        elif _has_file(root, "pyproject.toml"):
            checks.append(Check("python -m pytest", ["python", "-m", "pytest", "-q", "--tb=no", "-x"], "test"))

    if _has_dir(root, "tests") and not any(c.name.startswith("pytest") for c in checks):
        checks.append(Check("unittest discover", ["python", "-m", "unittest", "discover", "-q"], "test"))

    if pyproject or _has_file(root, "setup.cfg") or _has_file(root, ".flake8"):
        if shutil_which("ruff"):
            checks.append(Check("ruff check", ["ruff", "check", "."], "lint"))
        elif shutil_which("flake8"):
            checks.append(Check("flake8", ["flake8", "."], "lint"))

    if package_json:
        pkg = _read_package_json(root / "package.json")
        scripts = (pkg or {}).get("scripts") or {}
        if "test" in scripts:
            checks.append(Check("npm test", ["npm", "test", "--", "--watchAll=false"], "test"))
        if "lint" in scripts:
            checks.append(Check("npm run lint", ["npm", "run", "lint"], "lint"))

    if cargo:
        checks.append(Check("cargo test", ["cargo", "test", "--quiet"], "test"))
        if shutil_which("cargo"):
            checks.append(Check("cargo clippy", ["cargo", "clippy", "-q"], "lint"))

    if go_mod:
        checks.append(Check("go test", ["go", "test", "./..."], "test"))

    if makefile:
        code, out, _ = _run(["make", "-n", "test"], cwd=root, timeout=15)
        if code == 0 and "test" in out.lower():
            checks.append(Check("make test", ["make", "test"], "test"))

    try:
        from arka.agent.script_discovery import discover_script_checks as discover_scripts

        for item in discover_scripts(root):
            detail = "; ".join(item.reasons[:2]) if item.reasons else ""
            checks.append(Check(item.name, list(item.command), item.category, detail))
    except ImportError:
        pass

    return checks


def shutil_which(name: str) -> str | None:
    from shutil import which

    return which(name)


def _read_package_json(path: Path) -> dict | None:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None


def scan_text(root: Path) -> str:
    checks = detect_checks(root)
    lines = [
        f"Repo health scan: {root.name}",
        f"Path: {root}",
        "",
    ]
    if not checks:
        lines.append("No automated checks detected.")
        lines.append("Looked for: pytest, ruff/flake8, npm test/lint, cargo, go test, make test")
        return "\n".join(lines)

    by_cat: dict[str, list[Check]] = {}
    for chk in checks:
        by_cat.setdefault(chk.category, []).append(chk)

    lines.append(f"Detected {len(checks)} check(s):")
    for cat in ("test", "lint"):
        group = by_cat.get(cat) or []
        if not group:
            continue
        lines.append(f"\n{cat.title()}:")
        for chk in group:
            line = f"  - {chk.name}: {' '.join(chk.command)}"
            if chk.detail:
                line += f"  ({chk.detail})"
            lines.append(line)

    lines.append("\nRun checks: repo_health run")
    return "\n".join(lines)


def scan_payload(root: Path | str | None = None) -> dict:
    """Structured repo health scan for MCP / automation clients."""
    path = _project_root(str(root) if root is not None else None)
    checks = detect_checks(path)
    return {
        "path": str(path),
        "name": path.name,
        "count": len(checks),
        "checks": [
            {
                "name": chk.name,
                "command": list(chk.command),
                "category": chk.category,
                **({"detail": chk.detail} if chk.detail else {}),
            }
            for chk in checks
        ],
    }


def run_payload(
    root: Path | str | None = None,
    *,
    categories: set[str] | None = None,
) -> dict:
    """Run detected checks and return structured results."""
    path = _project_root(str(root) if root is not None else None)
    checks = detect_checks(path)
    if categories:
        checks = [c for c in checks if c.category in categories]
    results: list[dict] = []
    passed = failed = skipped = 0
    for chk in checks:
        code, out, err = _run(chk.command, cwd=path, timeout=300)
        combined = (out + err).strip()
        preview = "\n".join(combined.splitlines()[:8])
        if code == 0:
            status = "passed"
            passed += 1
        elif code == 127 or "not found" in err.lower():
            status = "skipped"
            skipped += 1
        else:
            status = "failed"
            failed += 1
        results.append(
            {
                "name": chk.name,
                "category": chk.category,
                "command": list(chk.command),
                "status": status,
                "exit_code": code,
                "preview": preview,
            }
        )
    return {
        "path": str(path),
        "name": path.name,
        "passed": passed,
        "failed": failed,
        "skipped": skipped,
        "results": results,
        "ok": failed == 0,
    }


def run_checks(root: Path, *, categories: set[str] | None = None) -> str:
    payload = run_payload(root, categories=categories)
    if not payload.get("results"):
        return scan_text(root)

    lines = [f"Repo health run: {payload['name']}", ""]
    for row in payload["results"]:
        lines.append(f"▶ {row['name']}")
        status = row["status"]
        if status == "passed":
            lines.append("  ✓ passed")
        elif status == "skipped":
            lines.append("  ⊘ skipped (tool missing)")
        else:
            lines.append(f"  ✗ failed (exit {row['exit_code']})")
        preview = str(row.get("preview") or "")
        if preview:
            for pline in preview.splitlines():
                lines.append(f"    {pline[:160]}")
        lines.append("")

    lines.append(
        f"Summary: {payload['passed']} passed, {payload['failed']} failed, {payload['skipped']} skipped"
    )
    return "\n".join(lines).strip()


def wants_repo_health(text: str) -> bool:
    return bool(_TRIGGER_RE.search(text or ""))


def route_command(text: str) -> str:
    if not wants_repo_health(text):
        return ""
    clean = (text or "").strip()
    if _RUN_RE.search(clean) or re.search(r"(?i)\brun\s+repo\s+health\b", clean):
        if re.search(r"(?i)\b(?:lint|flake8|ruff)\b", clean):
            return "repo_health run --lint"
        if re.search(r"(?i)\btests?\b", clean) and not re.search(r"(?i)\blint\b", clean):
            return "repo_health run --test"
        return "repo_health run"
    return "repo_health scan"


def cmd_scan(args: argparse.Namespace) -> int:
    root = _project_root(args.path)
    print(scan_text(root))
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    root = _project_root(args.path)
    cats: set[str] | None = None
    if args.test and not args.lint:
        cats = {"test"}
    elif args.lint and not args.test:
        cats = {"lint"}
    text = run_checks(root, categories=cats)
    print(text)
    return 0 if " failed" not in text or "0 failed" in text else 1


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    parser = argparse.ArgumentParser(description="Quick repo health scan and checks")
    sub = parser.add_subparsers(dest="cmd")

    p_route = sub.add_parser("route", help="Map NL to repo_health command")
    p_route.add_argument("text", nargs="+")

    p_scan = sub.add_parser("scan", help="Detect available checks")
    p_scan.add_argument("path", nargs="?", default=None)
    p_scan.set_defaults(func=cmd_scan)

    p_run = sub.add_parser("run", help="Run detected checks")
    p_run.add_argument("path", nargs="?", default=None)
    p_run.add_argument("--test", action="store_true")
    p_run.add_argument("--lint", action="store_true")
    p_run.set_defaults(func=cmd_run)

    args = parser.parse_args(argv)
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
