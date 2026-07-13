#!/usr/bin/env python3
"""Self-improvement loop — Arka uses its goal agent to improve its own codebase."""

from __future__ import annotations

import argparse
import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

DEFAULT_MAX_ROUNDS = int(os.environ.get("SELF_IMPROVE_MAX_ROUNDS", "3"))
DEFAULT_MAX_STEPS = int(os.environ.get("SELF_IMPROVE_MAX_STEPS", "15"))
CONTEXT_LIMIT = int(os.environ.get("SELF_IMPROVE_CONTEXT_LIMIT", "10000"))
DIAG_TIMEOUT = int(os.environ.get("SELF_IMPROVE_DIAG_TIMEOUT", "120"))

_BLOCKED_GIT_RE = re.compile(
    r"(?i)\bgit\s+(?:commit|push|reset\s+--hard|clean\s+-[fdx]|checkout\s+--\s+\.|rebase|merge|cherry-pick|stash\s+(?:drop|clear))\b"
)

_SYSTEM_EXTRA = """SELF-IMPROVEMENT MODE — you are improving the Arka agent codebase.
- Read llm.txt (status read) before editing unfamiliar areas.
- Only edit files inside the active code project root.
- Prefer minimal, focused diffs; match existing style and conventions.
- After code changes run: pytest -q --tb=short (or targeted test file).
- After significant edits run: arka repo index
- NEVER run git commit, git push, git reset --hard, or other destructive git ops.
- Do not modify web/node_modules or bundled/ directly (use sync_bundled.py for bundled/).
- Stop with status done when tests pass and the improvement target is met."""


@dataclass
class DiagnosticResult:
    command: str
    exit_code: int
    output: str

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


def arka_repo_root() -> Path | None:
    """Detect the Arka source checkout (dev install or cwd git root)."""
    try:
        from arka.paths import checkout_root

        root = checkout_root()
        if root and _is_arka_repo(root):
            return root
    except ImportError:
        pass

    try:
        from arka.agent.repo_context import git_root

        root = git_root()
        if root and _is_arka_repo(root):
            return root
    except ImportError:
        pass

    cwd = Path.cwd().resolve()
    if _is_arka_repo(cwd):
        return cwd
    return None


def _is_arka_repo(path: Path) -> bool:
    return (
        path.is_dir()
        and (path / "pyproject.toml").is_file()
        and (path / "llm.txt").is_file()
        and (path / "src" / "arka").is_dir()
    )


def ensure_arka_project(*, auto_init: bool = True) -> Path:
    """Ensure code project is scoped to the Arka repo."""
    from arka.core.code_project import (
        CodeProjectError,
        apply_env,
        get_active_root,
        init_project,
        is_scoped,
    )

    root = arka_repo_root()
    if root is None:
        raise CodeProjectError(
            "Could not detect Arka repo. Run from the arka checkout or: arka code init /path/to/arka"
        )

    active = get_active_root()
    if not is_scoped() or active != root.resolve():
        if not auto_init:
            raise CodeProjectError(
                f"Code project not initialized for Arka repo. Run: arka code init {root}"
            )
        init_project(root)
        print(f"→ Initialized code project: {root}", file=sys.stderr)

    apply_env()
    return root.resolve()


def _read_repo_context(root: Path, *, limit: int = CONTEXT_LIMIT) -> str:
    try:
        from arka.agent.repo_context import llm_txt_path

        path = llm_txt_path(root)
    except ImportError:
        path = root / "llm.txt"

    if not path.is_file():
        return "(llm.txt not found — run: arka repo index)"

    text = path.read_text(encoding="utf-8", errors="replace")
    if len(text) <= limit:
        return text

    # Prefer agent rules + recent changes + architecture headers.
    parts: list[str] = []
    for marker in ("AGENT RULES", "RECENT FILE CHANGES", "ARCHITECTURE", "PROJECT SUMMARY"):
        idx = text.find(marker)
        if idx >= 0:
            chunk = text[idx : idx + limit // 3]
            parts.append(chunk)
    if parts:
        merged = "\n\n".join(parts)
        return merged[:limit] + ("\n...(truncated)" if len(merged) > limit else "")

    return text[:limit] + f"\n...(truncated, {len(text)} chars total)"


def run_diagnostics(root: Path) -> DiagnosticResult:
    """Run pytest; fall back to a short arka doctor summary."""
    pytest_cmd = "pytest -q --tb=short -x --no-header"
    try:
        proc = subprocess.run(
            ["fish", "-c", pytest_cmd],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=DIAG_TIMEOUT,
        )
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        if proc.returncode != 0 or out:
            return DiagnosticResult(pytest_cmd, proc.returncode, out[:8000])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return DiagnosticResult(pytest_cmd, 1, f"pytest failed to run: {exc}")

    doctor_cmd = "python3 -m arka.cli doctor"
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "arka.cli", "doctor"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=60,
        )
        out = ((proc.stdout or "") + (proc.stderr or "")).strip()
        return DiagnosticResult(doctor_cmd, proc.returncode, out[:4000])
    except (OSError, subprocess.TimeoutExpired) as exc:
        return DiagnosticResult(doctor_cmd, 1, f"doctor failed: {exc}")


def build_goal(
    target: str,
    *,
    context: str,
    diag: DiagnosticResult | None,
    root: Path,
) -> str:
    lines = [
        "Improve the Arka codebase (self-improvement loop).",
        f"Repository: {root}",
    ]
    if target:
        lines.append(f"Target: {target}")
    else:
        lines.append(
            "Target: fix failing tests, linter issues, missing docs in llm.txt, or routing gaps."
        )

    lines.append("")
    lines.append("=== llm.txt context (read full file for details) ===")
    lines.append(context)
    lines.append("")

    if diag is not None:
        status = "PASS" if diag.passed else "FAIL"
        lines.append(f"=== Diagnostics ({status}: {diag.command}) ===")
        lines.append(diag.output or "(no output)")
        lines.append("")

    lines.append(
        "Workflow: inspect failures → read relevant source → apply minimal fix → "
        "run pytest → arka repo index if docs/llm.txt changed → done when green."
    )
    return "\n".join(lines)


def _sync_changelog(root: Path) -> None:
    try:
        from arka.agent.repo_context import sync_index

        result = sync_index(root)
        if isinstance(result, dict) and result.get("changed"):
            print(f"→ llm.txt changelog: {result.get('changed')} file(s)", file=sys.stderr)
    except ImportError:
        pass
    except Exception as exc:
        print(f"⚠ repo index skipped: {exc}", file=sys.stderr)


def _check_mode() -> tuple[bool, str]:
    try:
        from arka.core.mode import get_mode

        mode = get_mode()
        if mode != "agent":
            return False, f"self improve requires agent mode (current: {mode}). Run: arka mode agent"
    except ImportError:
        pass
    return True, ""


def _git_blocklist_hook(cmd: str) -> tuple[int, str] | None:
    if _BLOCKED_GIT_RE.search(cmd):
        return 2, "[blocked: destructive git operations not allowed in self-improve]"
    return None


def run_self_improve(
    target: str = "",
    *,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    max_steps: int = DEFAULT_MAX_STEPS,
    auto_init: bool = True,
    yes: bool = False,
) -> int:
    """Run the self-improvement loop: diagnose → goal agent → re-check."""
    ok, reason = _check_mode()
    if not ok:
        print(reason, file=sys.stderr)
        return 1

    try:
        root = ensure_arka_project(auto_init=auto_init)
    except Exception as exc:
        print(str(exc), file=sys.stderr)
        return 1

    os.chdir(root)
    target = " ".join(target.split()).strip()
    print(f"Arka self-improve — {root}", file=sys.stderr)
    if target:
        print(f"  target: {target}", file=sys.stderr)
    print(f"  max rounds: {max_rounds} | steps/round: {max_steps}", file=sys.stderr)

    from arka.agent.goal import run_goal

    last_rc = 1
    for round_num in range(1, max_rounds + 1):
        print(f"\n── Self-improve round {round_num}/{max_rounds} ──", file=sys.stderr)
        context = _read_repo_context(root)
        diag = run_diagnostics(root)

        if diag.passed and not target and round_num == 1:
            print("✓ Diagnostics passed — nothing to fix.", file=sys.stderr)
            return 0

        goal = build_goal(target, context=context, diag=diag, root=root)
        last_rc = run_goal(
            goal,
            max_steps=max_steps,
            auto_yes=yes,
            auto_continue=True,
            system_extra=_SYSTEM_EXTRA,
            cmd_hook=_git_blocklist_hook,
        )
        _sync_changelog(root)

        diag_after = run_diagnostics(root)
        if diag_after.passed:
            print("✓ Tests/diagnostics passed after round.", file=sys.stderr)
            return 0 if last_rc == 0 else last_rc

        if last_rc != 0:
            print(f"⚠ Goal agent exited {last_rc} — continuing if rounds remain.", file=sys.stderr)

    print("Max rounds reached — issues may remain.", file=sys.stderr)
    return last_rc if last_rc != 0 else 1


def route_command(text: str) -> str:
    """NL → self_improve skill line."""
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if not raw:
        return ""

    if not re.search(
        r"(?i)\b(?:self\s+improve|improve\s+(?:arka|yourself|itself)|arka\s+improve(?:\s+itself)?|"
        r"loop\s+to\s+fix\s+arka|fix\s+arka(?:\s+(?:tests|codebase))?|improve\s+the\s+arka\s+codebase|loop\s+self)\b",
        raw,
    ):
        return ""

    if re.search(r"(?i)\bloop\s+self\b", raw):
        rest = re.sub(r"(?i)^(?:arka\s+)?loop\s+self\s*", "", raw).strip()
        return f"self_improve {rest}".strip() if rest else "self_improve"

    target = raw
    for pattern in (
        r"(?i)^(?:arka\s+)?self\s+improve\s*",
        r"(?i)^(?:arka\s+)?improve\s+arka\s*",
        r"(?i)^(?:arka\s+)?improve\s+(?:yourself|itself)\s*",
        r"(?i)^(?:arka\s+)?arka\s+improve(?:\s+itself)?\s*",
        r"(?i)^(?:arka\s+)?loop\s+to\s+fix\s+arka\s*",
        r"(?i)^(?:arka\s+)?fix\s+arka(?:\s+(?:tests|codebase))?\s*",
        r"(?i)^(?:arka\s+)?improve\s+the\s+arka\s+codebase\s*",
        r"(?i)^(?:arka\s+)?improve\s*",
    ):
        stripped = re.sub(pattern, "", target).strip()
        if stripped != target:
            target = stripped
            break

    return f"self_improve {target}".strip() if target else "self_improve"


def main(argv: list[str] | None = None) -> int:
    from arka.paths import load_env_file

    load_env_file()

    parser = argparse.ArgumentParser(
        description="Arka self-improvement loop — goal agent scoped to the Arka repo",
    )
    sub = parser.add_subparsers(dest="cmd")

    p_imp = sub.add_parser("improve", help="Run self-improvement loop")
    p_imp.add_argument("target", nargs="*", help="Optional improvement target")
    p_imp.add_argument("-n", "--max-rounds", type=int, default=DEFAULT_MAX_ROUNDS)
    p_imp.add_argument("-s", "--max-steps", type=int, default=DEFAULT_MAX_STEPS)
    p_imp.add_argument("-y", "--yes", action="store_true", help="Auto-approve risky actions")
    p_imp.add_argument(
        "--no-auto-init",
        action="store_true",
        help="Require arka code init instead of auto-initializing",
    )

    p_route = sub.add_parser("route", help="NL routing helper")
    p_route.add_argument("text", nargs="+")

    p_status = sub.add_parser("status", help="Show Arka repo + code project status")

    args = parser.parse_args(argv)

    if args.cmd == "improve":
        target = " ".join(args.target).strip()
        return run_self_improve(
            target,
            max_rounds=max(1, args.max_rounds),
            max_steps=max(1, args.max_steps),
            auto_init=not args.no_auto_init,
            yes=args.yes,
        )

    if args.cmd == "route":
        line = route_command(" ".join(args.text))
        if line:
            print(line)
            return 0
        return 1

    if args.cmd == "status":
        root = arka_repo_root()
        try:
            from arka.core.code_project import get_active_root, is_scoped

            active = get_active_root()
            scoped = is_scoped()
        except ImportError:
            active = None
            scoped = False
        print(f"arka repo:  {root or '(not detected)'}")
        print(f"code project: {'yes' if scoped else 'no'}")
        if active:
            print(f"  root: {active}")
        return 0

    # Default: improve with no subcommand (arka self [target])
    if argv and argv[0] not in ("-h", "--help") and args.cmd is None:
        target = " ".join(argv).strip()
        if target in ("improve", "self"):
            return run_self_improve()
        if target.startswith("improve "):
            return run_self_improve(target.removeprefix("improve ").strip())
        return run_self_improve(target)

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
