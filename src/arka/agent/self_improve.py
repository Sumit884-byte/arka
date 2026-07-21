#!/usr/bin/env python3
"""Self-improvement loop — Arka analyzes, plans, and optionally improves its own codebase."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

DEFAULT_MAX_ROUNDS = int(os.environ.get("SELF_IMPROVE_MAX_ROUNDS", "3"))
DEFAULT_MAX_STEPS = int(os.environ.get("SELF_IMPROVE_MAX_STEPS", "15"))
CONTEXT_LIMIT = int(os.environ.get("SELF_IMPROVE_CONTEXT_LIMIT", "10000"))
DIAG_TIMEOUT = int(os.environ.get("SELF_IMPROVE_DIAG_TIMEOUT", "120"))
GIT_LOG_LIMIT = int(os.environ.get("SELF_IMPROVE_GIT_LOG_LIMIT", "15"))
MEMORY_MAX_ATTEMPTS = 100


def _run_git(args: list[str], root: Path) -> tuple[int, str, str]:
    proc = subprocess.run(["git", *args], cwd=root, capture_output=True, text=True, check=False)
    return proc.returncode, proc.stdout or "", proc.stderr or ""

_BLOCKED_GIT_RE = re.compile(
    r"(?i)\bgit\s+(?:commit|push|reset\s+--hard|clean\s+-[fdx]|checkout\s+--\s+\.|rebase|merge|cherry-pick|stash\s+(?:drop|clear))\b"
)

_BLOCKED_WRITE_RE = re.compile(
    r"(?i)(?:^|[\s'\"])(?:\.env(?:\.|$)|(?:^|/)secrets(?:/|$)|node_modules/|web/node_modules/)"
)

_PLAN_JSON_RE = re.compile(r"\{[\s\S]*\}")
_TEST_FIX_RE = re.compile(r"(?i)\bfix(?:ing)?\s+(?:failing\s+)?tests?\b")
_DEDUPE_HOURS = 24

_SYSTEM_EXTRA = """SELF-IMPROVEMENT MODE — you are improving the Arka agent codebase.
- Read llm.txt (status read) before editing unfamiliar areas.
- Only edit files inside the active code project root.
- Prefer minimal, focused diffs; match existing style and conventions.
- Before implementing, inspect and reuse preexisting Arka skills, MCP tools, and integration libraries; integrate them instead of recreating equivalent code.
- After code changes run: pytest -q --tb=short (or targeted test file).
- After significant edits run: arka repo index
- NEVER run git commit, git push, git reset --hard, or other destructive git ops.
- NEVER modify .env, secrets/, node_modules/, or web/node_modules/.
- Do not modify bundled/ directly (use sync_bundled.py for bundled/).
- Stop with status done when tests pass and the improvement target is met."""

_PLAN_SYSTEM = """You are Arka's self-improvement planner. Given repo context, diagnostics, and a target focus,
produce ONE concrete, minimal improvement plan scoped to the Arka Python/Fish codebase.

Output ONLY valid JSON (no markdown fences) with keys:
- focus: short topic string (e.g. "routing", "llm fallback", "quiz memory")
- analyzed: array of 1-3 strings — what you inspected and found (file names + brief finding)
- proposal: one sentence describing the concrete fix
- files: array of relative repo paths to edit (max 6)
- tests: array of pytest shell commands to verify (1-3)

Rules:
- Do not propose editing .env, secrets/, node_modules/, or credentials.
- Prefer existing modules under src/arka/ and tests/.
- Avoid repeating fixes listed under "Prior attempts".
- When diagnostics show PASS, do not propose fixing failing tests. Propose a concrete
  enhancement for the target focus (routing sync, edge-case tests, docs) instead.
- Every files[] entry must exist in the repo (no invented paths like router.py)."""


@dataclass
class DiagnosticResult:
    command: str
    exit_code: int
    output: str

    @property
    def passed(self) -> bool:
        return self.exit_code == 0


@dataclass
class ImprovementPlan:
    focus: str
    analyzed: list[str] = field(default_factory=list)
    proposal: str = ""
    files: list[str] = field(default_factory=list)
    tests: list[str] = field(default_factory=list)
    raw_llm: str = ""


def _config_dir() -> Path:
    try:
        from arka.paths import config_dir

        return config_dir()
    except ImportError:
        return Path.home() / ".config" / "arka"


def memory_path() -> Path:
    return _config_dir() / "self-improve-memory.json"


def load_memory() -> dict[str, Any]:
    path = memory_path()
    if not path.is_file():
        return {"attempts": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"attempts": []}
    if not isinstance(data, dict):
        return {"attempts": []}
    data.setdefault("attempts", [])
    return data


def save_memory(data: dict[str, Any]) -> None:
    path = memory_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
    except OSError:
        pass


def _diagnostic_pytest_cmd() -> str:
    """CI gate subset — fast, env-stable checks for self-improve diagnostics."""
    files = (
        "tests/test_mcp_server.py",
        "tests/test_openclaw_features.py",
        "tests/test_hermes_features.py",
        "tests/test_project_rules.py",
        "tests/test_clipboard_history.py",
        "tests/test_agent_hub.py",
        "tests/test_llm_fallback.py",
        "tests/test_context7_mcp.py",
        "tests/test_self_improve.py",
        "tests/test_self_build.py",
        "tests/test_free_credits.py",
        "tests/test_install_app_platform.py",
        "tests/test_router_gift_advice.py",
        "tests/test_convert_media.py::test_route_convert_media",
    )
    return "pytest -q --tb=short -x --no-header " + " ".join(files)


def _normalize_focus(text: str) -> str:
    return " ".join((text or "").split()).strip().lower()


def _validate_plan_files(files: list[str], root: Path) -> list[str]:
    """Drop proposed paths that do not exist in the repo."""
    valid: list[str] = []
    for rel in files:
        rel = rel.strip()
        if not rel or _BLOCKED_WRITE_RE.search(rel):
            continue
        if (root / rel).is_file():
            valid.append(rel)
    return valid[:6]


def _plan_signature(plan: ImprovementPlan) -> str:
    norm_prop = re.sub(r"\s+", " ", plan.proposal.strip().lower())
    return f"{_normalize_focus(plan.focus)}|{norm_prop}|{','.join(sorted(plan.files))}"


def _duplicate_proposal_hint(plan: ImprovementPlan, *, hours: int = _DEDUPE_HOURS) -> str:
    sig = _plan_signature(plan)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=hours)
    count = 0
    for entry in reversed(load_memory().get("attempts") or []):
        entry_sig = "|".join(
            [
                _normalize_focus(str(entry.get("focus") or "")),
                re.sub(r"\s+", " ", str(entry.get("proposal") or "").strip().lower()),
                ",".join(sorted(str(f) for f in (entry.get("files") or []))),
            ]
        )
        if entry_sig != sig:
            continue
        at_raw = str(entry.get("at") or "")
        try:
            at = datetime.fromisoformat(at_raw.replace("Z", "+00:00"))
        except ValueError:
            at = cutoff
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        if at >= cutoff:
            count += 1
    if count >= 2:
        return f"similar plan recorded {count}× in the last {hours}h — try --apply or a new focus"
    return ""


def _extract_failing_test_path(output: str) -> str | None:
    match = re.search(r"FAILED\s+(\S+)", output or "")
    if not match:
        return None
    return match.group(1).split("::")[0]


def _is_environment_only_failure(output: str) -> bool:
    from arka.core.output import summarize_pytest

    return summarize_pytest(output, passed=False) == "environment restriction (not a code bug)"


def _docs_check(root: Path) -> tuple[bool, str]:
    """Read-only llm.txt / index freshness check for plan output."""
    llm_path = root / "llm.txt"
    if not llm_path.is_file():
        return False, "llm.txt missing — run: arka repo index"
    try:
        from arka.agent.repo_context import get_index_state, git_changed_since

        state = get_index_state(root)
        last = state.get("last_commit")
        rows = git_changed_since(root, last if isinstance(last, str) else None)
        if rows:
            return False, f"llm.txt stale ({len(rows)} unindexed file change(s))"
        if isinstance(last, str):
            return True, "llm.txt up to date"
        return True, "llm.txt present (run: arka repo index)"
    except ImportError:
        return True, "llm.txt present"
    except Exception as exc:
        return True, f"llm.txt present (index check skipped: {exc})"


def _plan_proposes_test_fix_when_green(proposal: str, diag: DiagnosticResult | None) -> bool:
    return diag is not None and diag.passed and bool(_TEST_FIX_RE.search(proposal or ""))


def record_attempt(
    plan: ImprovementPlan,
    *,
    outcome: str,
    notes: str = "",
    root: Path | None = None,
) -> None:
    if root is not None:
        plan.files = _validate_plan_files(plan.files, root)
    data = load_memory()
    attempts: list[dict[str, Any]] = list(data.get("attempts") or [])
    sig = _plan_signature(plan)
    cutoff = datetime.now(timezone.utc) - timedelta(hours=_DEDUPE_HOURS)
    for entry in reversed(attempts):
        entry_sig = "|".join(
            [
                _normalize_focus(str(entry.get("focus") or "")),
                re.sub(r"\s+", " ", str(entry.get("proposal") or "").strip().lower()),
                ",".join(sorted(str(f) for f in (entry.get("files") or []))),
            ]
        )
        if entry_sig != sig:
            continue
        at_raw = str(entry.get("at") or "")
        try:
            at = datetime.fromisoformat(at_raw.replace("Z", "+00:00"))
        except ValueError:
            at = cutoff
        if at.tzinfo is None:
            at = at.replace(tzinfo=timezone.utc)
        if at >= cutoff and str(entry.get("outcome") or "") == outcome:
            return
    attempts.append(
        {
            "focus": plan.focus,
            "proposal": plan.proposal,
            "files": plan.files,
            "outcome": outcome,
            "notes": notes,
            "at": datetime.now(timezone.utc).isoformat(),
        }
    )
    data["attempts"] = attempts[-MEMORY_MAX_ATTEMPTS:]
    save_memory(data)


def recent_attempts_context(focus: str = "", *, limit: int = 8) -> str:
    attempts = load_memory().get("attempts") or []
    if not attempts:
        return "(none)"
    norm_focus = _normalize_focus(focus)
    lines: list[str] = []
    for entry in reversed(attempts):
        entry_focus = _normalize_focus(str(entry.get("focus") or ""))
        if norm_focus and entry_focus and norm_focus not in entry_focus and entry_focus not in norm_focus:
            continue
        prop = str(entry.get("proposal") or "").strip()
        outcome = str(entry.get("outcome") or "").strip()
        if prop:
            lines.append(f"- [{outcome}] {prop}")
        if len(lines) >= limit:
            break
    return "\n".join(lines) if lines else "(none matching this focus)"


def arka_repo_root() -> Path | None:
    """Detect the Arka source checkout from the installed package — never a random git cwd."""
    candidates: list[Path] = []

    try:
        from arka.paths import arka_home, checkout_root

        if root := checkout_root():
            candidates.append(root)
        home = arka_home()
        if home.is_dir():
            candidates.append(home)
            if home.name == "bundled" and home.parent.is_dir():
                candidates.append(home.parent)
    except ImportError:
        pass

    seen: set[Path] = set()
    for root in candidates:
        resolved = root.resolve()
        if resolved in seen:
            continue
        seen.add(resolved)
        if _is_arka_repo(resolved):
            return resolved

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
        from arka.core.output import user_msg

        user_msg(f"→ Initialized code project: {root}")

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


def get_git_log(root: Path, *, limit: int = GIT_LOG_LIMIT) -> str:
    try:
        proc = subprocess.run(
            ["git", "log", f"-{limit}", "--oneline", "--no-decorate"],
            cwd=root,
            capture_output=True,
            text=True,
            timeout=30,
        )
        out = (proc.stdout or "").strip()
        return out if out else "(no git history)"
    except (OSError, subprocess.TimeoutExpired) as exc:
        return f"(git log unavailable: {exc})"


def _routing_analysis(root: Path, focus: str) -> list[str]:
    """Heuristic routing-gap notes when focus mentions routing or NL dispatch."""
    notes: list[str] = []
    focus_l = focus.lower()
    if "routing" not in focus_l and "route" not in focus_l and "symbolic" not in focus_l:
        return notes

    sym = root / "src" / "arka" / "routing" / "symbolic.py"
    fish = root / "src" / "arka" / "fish" / "config.fish"
    if sym.is_file():
        text = sym.read_text(encoding="utf-8", errors="replace")
        route_fns = len(re.findall(r"^def route_", text, re.MULTILINE))
        notes.append(f"symbolic.py ({route_fns} route_* handlers)")
    if fish.is_file():
        text = fish.read_text(encoding="utf-8", errors="replace")
        agent_ifs = len(re.findall(r"_agent_is_\w+_request", text))
        notes.append(f"config.fish ({agent_ifs} _agent_is_* NL detectors)")
    if sym.is_file() and fish.is_file():
        notes.append("Check fish vs Python symbolic.py parity when adding NL patterns")
    return notes


def _guess_files(root: Path, focus: str) -> list[str]:
    """Keyword → likely source files (fallback when LLM unavailable)."""
    focus_l = focus.lower()
    candidates: list[str] = []
    mapping = (
        ("routing", ["src/arka/routing/symbolic.py", "src/arka/fish/config.fish", "tests/test_nl_routing_coverage.py"]),
        ("route", ["src/arka/routing/symbolic.py", "src/arka/fish/config.fish"]),
        ("llm", ["src/arka/llm/fallback.py", "src/arka/llm/skill_profiles.py", "tests/test_llm_fallback.py"]),
        ("fallback", ["src/arka/llm/fallback.py"]),
        ("quiz", ["src/arka/agent/quiz.py", "tests/test_quiz.py"]),
        ("memory", ["src/arka/agent/core.py", "src/arka/agent/self_improve.py"]),
        ("data_ask", ["src/arka/agent/data_ask.py", "tests/test_data_ask.py"]),
        ("timezone", ["src/arka/agent/data_ask.py", "tests/test_data_ask.py"]),
        ("dispatch", ["src/arka/dispatch.py", "src/arka/cli.py"]),
        ("cli", ["src/arka/cli.py"]),
    )
    for keyword, paths in mapping:
        if keyword in focus_l:
            for rel in paths:
                if (root / rel).is_file() and rel not in candidates:
                    candidates.append(rel)
    if not candidates:
        candidates = ["src/arka/agent/self_improve.py", "tests/test_self_improve.py"]
    return candidates[:6]


def _heuristic_plan(
    target: str,
    *,
    context: str,
    diag: DiagnosticResult | None,
    routing_notes: list[str],
    root: Path,
) -> ImprovementPlan:
    focus = _normalize_target(target) or "general"
    analyzed: list[str] = []
    if routing_notes:
        analyzed.append(", ".join(routing_notes))
    if diag is not None:
        status = "passing" if diag.passed else "failing"
        analyzed.append(f"diagnostics ({status}: {diag.command})")
    if "RECENT FILE CHANGES" in context:
        analyzed.append("llm.txt recent changes section")
    elif context and not context.startswith("("):
        analyzed.append("llm.txt context")

    if not diag or diag.passed:
        if focus != "general":
            proposal = f"Improve {focus} — add tests, fix edge cases, or sync fish/Python routing."
        else:
            proposal = "Repo healthy — pick a focus (routing, llm fallback, quiz memory) for targeted work."
    else:
        from arka.core.output import summarize_pytest

        summary = summarize_pytest(diag.output, passed=False)
        fail_test = _extract_failing_test_path(diag.output or "")
        if focus != "general":
            proposal = f"Address {focus} — {summary}"
        else:
            proposal = f"Fix failing diagnostics — {summary}"
        if fail_test:
            proposal = f"{proposal} ({fail_test})"

    files = _guess_files(root, focus)
    if diag is not None and not diag.passed:
        fail_test = _extract_failing_test_path(diag.output or "")
        if fail_test and (root / fail_test).is_file() and fail_test not in files:
            files = [fail_test, *files]
    files = _validate_plan_files(files, root)
    tests = [f"pytest -q {' '.join(files[-1:])}" if files else "pytest -q --tb=short -x"]
    if diag is not None and not diag.passed:
        fail_test = _extract_failing_test_path(diag.output or "")
        if fail_test:
            tests = [f"pytest -q {fail_test}"]
    elif focus != "general" and f"tests/test_{focus.split()[0]}.py" not in " ".join(tests):
        guess_test = root / "tests" / f"test_{focus.split()[0]}.py"
        if guess_test.is_file():
            tests = [f"pytest -q {guess_test.relative_to(root)}"]

    return ImprovementPlan(
        focus=focus,
        analyzed=analyzed or ["llm.txt", "git log"],
        proposal=proposal,
        files=files,
        tests=tests,
    )


def _parse_plan_json(raw: str) -> ImprovementPlan | None:
    if not raw:
        return None
    match = _PLAN_JSON_RE.search(raw)
    if not match:
        return None
    try:
        data = json.loads(match.group(0))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None

    def _str_list(key: str) -> list[str]:
        val = data.get(key)
        if isinstance(val, list):
            return [str(x).strip() for x in val if str(x).strip()]
        if isinstance(val, str) and val.strip():
            return [val.strip()]
        return []

    focus = str(data.get("focus") or "").strip() or "general"
    proposal = str(data.get("proposal") or "").strip()
    files = [f for f in _str_list("files") if not _BLOCKED_WRITE_RE.search(f)]
    tests = _str_list("tests") or ["pytest -q --tb=short -x"]
    analyzed = _str_list("analyzed")
    if not proposal:
        return None
    return ImprovementPlan(
        focus=focus,
        analyzed=analyzed,
        proposal=proposal,
        files=files,
        tests=tests,
        raw_llm=raw,
    )


def _finalize_plan(plan: ImprovementPlan, *, root: Path, diag: DiagnosticResult | None) -> ImprovementPlan:
    plan.files = _validate_plan_files(plan.files, root)
    if _plan_proposes_test_fix_when_green(plan.proposal, diag):
        plan.proposal = (
            f"Enhance {plan.focus} — add routing/tests coverage (diagnostics already pass)."
            if plan.focus != "general"
            else "Repo healthy — pick a concrete enhancement (routing, llm fallback, quiz memory)."
        )
        if not plan.files:
            plan.files = _validate_plan_files(_guess_files(root, plan.focus), root)
    return plan


def generate_plan(
    target: str,
    *,
    context: str,
    diag: DiagnosticResult | None,
    routing_notes: list[str],
    root: Path,
) -> ImprovementPlan:
    """LLM plan with heuristic fallback."""
    focus = _normalize_target(target) or "general"
    fallback = _heuristic_plan(
        target,
        context=context,
        diag=diag,
        routing_notes=routing_notes,
        root=root,
    )

    git_log = get_git_log(root)
    diag_text = "(not run)"
    if diag is not None:
        status = "PASS" if diag.passed else "FAIL"
        diag_text = f"{status} {diag.command}\n{(diag.output or '')[:4000]}"

    user = "\n".join(
        [
            f"Target focus: {focus or 'general improvement'}",
            "",
            "=== git log ===",
            git_log,
            "",
            "=== diagnostics ===",
            diag_text,
            "",
            "=== llm.txt excerpt ===",
            context[:6000],
            "",
            "=== routing analysis ===",
            "\n".join(routing_notes) if routing_notes else "(n/a)",
            "",
            "=== prior attempts (do not repeat) ===",
            recent_attempts_context(focus),
        ]
    )

    try:
        from arka.llm.fallback import llm_complete

        raw = llm_complete(_PLAN_SYSTEM, user, 0.1, skill="self_improve", task="agent")
        parsed = _parse_plan_json(raw)
        if parsed:
            if not parsed.files:
                parsed.files = fallback.files
            if not parsed.tests:
                parsed.tests = fallback.tests
            if not parsed.analyzed:
                parsed.analyzed = fallback.analyzed
            parsed.raw_llm = raw
            return _finalize_plan(parsed, root=root, diag=diag)
    except Exception as exc:
        from arka.core.output import user_msg

        user_msg(f"⚠ LLM plan unavailable ({exc}) — using heuristic plan.")

    return _finalize_plan(fallback, root=root, diag=diag)


def format_plan_output(
    plan: ImprovementPlan,
    *,
    apply: bool,
    diag: DiagnosticResult | None = None,
    routing_notes: list[str] | None = None,
    target: str = "",
    docs: tuple[bool, str] | None = None,
) -> str:
    """Clean, scannable status for normal mode (no llm.txt bodies or raw traces)."""
    from arka.core.output import summarize_pytest

    lines = ["━━━ Arka Self-Improve ━━━"]
    focus = plan.focus if plan.focus != "general" else (target or "general")
    if focus and focus != "general":
        lines.append(f"Focus: {focus}")

    checks = ["tests"]
    focus_l = f"{target} {plan.focus}".lower()
    if routing_notes or any(k in focus_l for k in ("routing", "route", "symbolic")):
        checks.append("routing")
    checks.append("docs")
    lines.append(f"Checking: {', '.join(checks)}")
    lines.append("")

    if diag is not None:
        if diag.passed:
            lines.append("✓ Tests: OK")
        elif _is_environment_only_failure(diag.output):
            lines.append(f"○ Tests: {summarize_pytest(diag.output, passed=False)}")
        else:
            lines.append(f"✗ Tests: {summarize_pytest(diag.output, passed=False)}")
    else:
        lines.append("○ Tests: not run")

    if docs is not None:
        docs_ok, docs_note = docs
        mark = "✓" if docs_ok else "○"
        lines.append(f"{mark} Docs: {docs_note}")

    if routing_notes:
        lines.append(f"✓ Routing: {routing_notes[0]}")
    elif any(k in focus_l for k in ("routing", "route", "symbolic")):
        lines.append("○ Routing: no extra notes")
    else:
        lines.append("✓ Routing: OK")

    if plan.proposal:
        lines.append(f"○ Plan: {plan.proposal}")
    elif plan.files:
        lines.append(f"○ Plan: edit {', '.join(plan.files[:3])}")

    dup_hint = _duplicate_proposal_hint(plan)
    if dup_hint:
        lines.append(f"○ Memory: {dup_hint}")

    lines.append("")
    if apply:
        lines.append("Next: applying changes via goal agent")
    else:
        focus_arg = plan.focus if plan.focus != "general" else (target or "")
        focus_arg, _ = _split_improve_flags_from_text(focus_arg)
        cmd = "arka self improve"
        if focus_arg and focus_arg != "general":
            cmd += f" {focus_arg}"
        cmd += " --apply"
        lines.append(f"Next: {cmd}")
    return "\n".join(lines)


def run_diagnostics(root: Path) -> DiagnosticResult:
    """Run CI-gate pytest subset; fall back to a short arka doctor summary."""
    pytest_cmd = _diagnostic_pytest_cmd()
    try:
        proc = subprocess.run(
            [sys.executable, "-m", "pytest", *pytest_cmd.split()[2:]],
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
    plan: ImprovementPlan | None = None,
) -> str:
    lines = [
        "Improve the Arka codebase (self-improvement loop).",
        f"Repository: {root}",
    ]
    if plan is not None:
        lines.append(f"Focus: {plan.focus}")
        lines.append(f"Proposal: {plan.proposal}")
        if plan.files:
            lines.append(f"Target files: {', '.join(plan.files)}")
        if plan.tests:
            lines.append(f"Verify with: {' | '.join(plan.tests)}")
    elif target:
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

    prior = recent_attempts_context(plan.focus if plan else target)
    if prior and prior != "(none)":
        lines.append("=== Prior attempts (avoid repeating) ===")
        lines.append(prior)
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


def _check_mode(*, apply: bool) -> tuple[bool, str]:
    try:
        from arka.core.mode import get_mode

        mode = get_mode()
        if apply and mode != "agent":
            return False, f"self improve --apply requires agent mode (current: {mode}). Run: arka mode agent"
    except ImportError:
        pass
    return True, ""


def _git_blocklist_hook(cmd: str) -> tuple[int, str] | None:
    if _BLOCKED_GIT_RE.search(cmd):
        return 2, "[blocked: destructive git operations not allowed in self-improve]"
    if _BLOCKED_WRITE_RE.search(cmd):
        return 2, "[blocked: cannot modify .env, secrets, or node_modules in self-improve]"
    return None


def _normalize_target(target: str) -> str:
    t = " ".join((target or "").split()).strip()
    if re.match(r"(?i)^arka\s+", t):
        t = re.sub(r"(?i)^arka\s+", "", t).strip()
    if re.match(r"(?i)^improve\s+", t):
        t = re.sub(r"(?i)^improve\s+", "", t).strip()
    return t


def _split_improve_flags_from_text(text: str) -> tuple[str, bool]:
    """Strip --apply (and leading improve) from a focus string."""
    apply = False
    kept: list[str] = []
    for tok in (text or "").split():
        if tok == "--apply":
            apply = True
        else:
            kept.append(tok)
    return _normalize_target(" ".join(kept)), apply


def parse_improve_argv(argv: list[str]) -> tuple[str, bool, dict[str, Any]]:
    """Split target text from --apply / passthrough flags."""
    apply = False
    extras: dict[str, Any] = {}
    tokens: list[str] = []
    flat: list[str] = []
    for raw in argv:
        flat.extend(raw.split())

    it = iter(flat)
    for tok in it:
        if tok == "--apply":
            apply = True
        elif tok in ("-y", "--yes"):
            extras["yes"] = True
        elif tok in ("-n", "--max-rounds") and (nxt := next(it, None)) is not None:
            extras["max_rounds"] = int(nxt)
        elif tok in ("-s", "--max-steps") and (nxt := next(it, None)) is not None:
            extras["max_steps"] = int(nxt)
        elif tok == "--no-auto-init":
            extras["auto_init"] = False
        elif tok == "improve":
            continue
        else:
            tokens.append(tok)
    target, embedded_apply = _split_improve_flags_from_text(" ".join(tokens))
    return target, apply or embedded_apply, extras


def resolve_improve_args(
    argv: list[str],
    *,
    apply: bool = False,
    yes: bool = False,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    max_steps: int = DEFAULT_MAX_STEPS,
    auto_init: bool = True,
) -> tuple[str, bool, int, int, bool, bool]:
    """Unified argv + explicit flags → (target, apply, max_rounds, max_steps, yes, auto_init)."""
    raw = list(argv)
    if apply:
        raw.append("--apply")
    if yes:
        raw.append("-y")
    if not auto_init:
        raw.append("--no-auto-init")
    target, parsed_apply, extras = parse_improve_argv(raw)
    return (
        target,
        parsed_apply,
        max(1, extras.get("max_rounds", max_rounds)),
        max(1, extras.get("max_steps", max_steps)),
        extras.get("yes", yes),
        extras.get("auto_init", auto_init),
    )


def run_self_improve(
    target: str = "",
    *,
    max_rounds: int = DEFAULT_MAX_ROUNDS,
    max_steps: int = DEFAULT_MAX_STEPS,
    auto_init: bool = True,
    yes: bool = False,
    apply: bool = False,
    fast: bool = False,
) -> int:
    """Analyze → plan → (optional --apply) goal agent execute loop."""
    from arka.core.output import debug_msg, summarize_pytest, user_msg

    ok, reason = _check_mode(apply=apply)
    if not ok:
        user_msg(reason)
        return 1

    try:
        root = ensure_arka_project(auto_init=auto_init)
    except Exception as exc:
        user_msg(str(exc))
        return 1

    target, embedded_apply = _split_improve_flags_from_text(_normalize_target(target))
    apply = apply or embedded_apply
    if fast:
        from arka.agent.dev_tools import run_ci
        ci = run_ci(root)
        docs_ok, docs_note = _docs_check(root)
        outcome = "planned" if ci["ok"] else "failed"
        print(f"Self-improve fast: {'planned' if ci['ok'] else 'failed'}")
        print(f"CI: {'passed' if ci['ok'] else 'failed'} ({len(ci['results'])} gates)")
        print(f"llm.txt: {'fresh' if docs_ok else 'stale/missing'}")
        record_attempt(ImprovementPlan(focus=target or "fast diagnostics", proposal="fast diagnostics"), outcome=outcome, notes=docs_note, root=root)
        return 0 if ci["ok"] else 1
    debug_msg(f"Arka self-improve — {root}")
    if target:
        debug_msg(f"  target: {target}")
    debug_msg(f"  mode: {'apply' if apply else 'plan-only'}")

    context = _read_repo_context(root)
    diag = run_diagnostics(root)
    routing_notes = _routing_analysis(root, target)
    docs = _docs_check(root)
    plan = generate_plan(
        target,
        context=context,
        diag=diag,
        routing_notes=routing_notes,
        root=root,
    )

    print(
        format_plan_output(
            plan,
            apply=apply,
            diag=diag,
            routing_notes=routing_notes,
            target=target,
            docs=docs,
        )
    )

    if not apply:
        record_attempt(plan, outcome="planned", root=root)
        if diag.passed and not target:
            debug_msg("✓ Diagnostics passed — plan only (use --apply to implement).")
        return 0

    user_msg("Applying plan…")
    debug_msg(f"  max rounds: {max_rounds} | steps/round: {max_steps}")
    from arka.agent.goal import run_goal

    last_rc = 1
    for round_num in range(1, max_rounds + 1):
        debug_msg(f"\n── Self-improve round {round_num}/{max_rounds} ──")
        user_msg(f"Round {round_num}/{max_rounds}…")
        _, before_stat, _ = _run_git(["diff", "--stat"], root)
        context = _read_repo_context(root)
        diag = run_diagnostics(root)
        goal = build_goal(target, context=context, diag=diag, root=root, plan=plan)
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
        _, after_stat, _ = _run_git(["diff", "--stat"], root)
        changed = bool(after_stat.strip()) and after_stat.strip() != before_stat.strip()
        if diag_after.passed and changed:
            user_msg(f"✓ applied changes after round {round_num}")
            record_attempt(plan, outcome="passed", root=root)
            return 0 if last_rc == 0 else last_rc
        if diag_after.passed and not changed:
            user_msg("○ no code changes")
            record_attempt(plan, outcome="no_changes", root=root)
            return 1

        if last_rc != 0:
            user_msg(f"⚠ Goal agent exited {last_rc} — continuing if rounds remain.")
        elif not diag_after.passed:
            user_msg(f"✗ Tests still failing: {summarize_pytest(diag_after.output, passed=False)}")

    record_attempt(plan, outcome="failed", notes=f"exit {last_rc}", root=root)
    user_msg("Max rounds reached — issues may remain.")
    return last_rc if last_rc != 0 else 1


def route_command(text: str) -> str:
    """NL → self_improve skill line."""
    raw = re.sub(r"\s+", " ", (text or "").strip())
    if not raw:
        return ""

    sub = re.match(r"(?i)^(?:arka\s+)?self\s+(memory|status)\s*$", raw)
    if sub:
        return f"self_improve {sub.group(1).lower()}"

    if not re.search(
        r"(?i)\b(?:self\s+improve|improve\s+(?:arka|yourself|itself)|arka\s+improve(?:\s+itself)?|"
        r"loop\s+to\s+fix\s+arka|fix\s+arka(?:\s+(?:tests|codebase))?|improve\s+the\s+arka\s+codebase|"
        r"loop\s+self|improve\s+arka\s+\w+)\b",
        raw,
    ):
        return ""

    if re.search(r"(?i)\bloop\s+self\b", raw):
        rest = re.sub(r"(?i)^(?:arka\s+)?loop\s+self\s*", "", raw).strip()
        target, apply = _split_improve_flags_from_text(_normalize_target(rest))
        line = "self_improve"
        if target:
            line += f" {target}"
        if apply:
            line += " --apply"
        return line

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

    target = re.sub(r"(?i)\b(?:fast|quick)\b", "", target).strip()
    target, apply = _split_improve_flags_from_text(_normalize_target(target))
    target = re.sub(r"(?i)\b(?:fast|quick)\b", "", target).strip()
    line = "self_improve"
    if re.search(r"(?i)\b(?:fast|quick)\b", raw):
        line += " --fast"
    if target:
        line += f" {target}"
    if apply:
        line += " --apply"
    return line


def main(argv: list[str] | None = None) -> int:
    from arka.paths import load_env_file

    load_env_file()

    parser = argparse.ArgumentParser(
        description="Arka self-improvement — analyze, plan, optionally apply fixes",
    )
    sub = parser.add_subparsers(dest="cmd")

    p_imp = sub.add_parser("improve", help="Analyze and plan improvements (--apply to execute)")
    p_imp.add_argument("target", nargs="*", help="Optional improvement focus")
    p_imp.add_argument("--apply", action="store_true", help="Run goal agent to implement the plan")
    p_imp.add_argument("--fast", action="store_true", help="Run compact diagnostics without LLM planning")
    p_imp.add_argument(
        "--mcp",
        action="store_true",
        help="Use MCP-orchestrated self-build loop (repo health audit via arka MCP tools)",
    )
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

    sub.add_parser("status", help="Show Arka repo + code project status")
    p_mem = sub.add_parser("memory", help="Show recent self-improve attempts")
    p_mem.add_argument("--json", action="store_true")

    args = parser.parse_args(argv)

    if args.cmd == "improve":
        target, apply, max_rounds, max_steps, yes, auto_init = resolve_improve_args(
            list(args.target),
            apply=args.apply,
            yes=args.yes,
            max_rounds=args.max_rounds,
            max_steps=args.max_steps,
            auto_init=not args.no_auto_init,
        )
        if getattr(args, "mcp", False):
            from arka.agent.self_build import run_self_build

            return run_self_build(
                target,
                apply=apply,
                yes=yes,
                max_rounds=max_rounds,
                max_steps=max_steps,
                auto_init=auto_init,
            )
        return run_self_improve(
            target,
            max_rounds=max_rounds,
            max_steps=max_steps,
            auto_init=auto_init,
            yes=yes,
            apply=apply,
            fast=args.fast,
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
        print(f"memory: {memory_path()}")
        return 0

    if args.cmd == "memory":
        data = load_memory()
        if args.json:
            print(json.dumps(data, indent=2))
            return 0
        attempts = list(reversed(data.get("attempts") or []))[:20]
        if not attempts:
            print("No self-improve attempts recorded yet.")
            return 0
        print("Recent self-improve attempts:\n")
        for entry in attempts:
            focus = entry.get("focus", "?")
            outcome = entry.get("outcome", "?")
            prop = entry.get("proposal", "")
            at = entry.get("at", "")
            print(f"  [{outcome}] {focus}: {prop}")
            if at:
                print(f"           {at}")
        return 0

    if argv and argv[0] not in ("-h", "--help") and args.cmd is None:
        target, apply, max_rounds, max_steps, yes, auto_init = resolve_improve_args(argv)
        if target in ("self", ""):
            target = ""
        return run_self_improve(
            target,
            max_rounds=max_rounds,
            max_steps=max_steps,
            auto_init=auto_init,
            yes=yes,
            apply=apply,
        )

    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
