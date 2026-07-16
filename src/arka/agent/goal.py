#!/usr/bin/env python3
"""Autonomous goal agent — Butterfish-style multi-step loop with plan + shell history."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path
from typing import Any

OUTPUT_LIMIT = int(os.environ.get("GOAL_OUTPUT_LIMIT", "8000"))
DEFAULT_MAX = int(os.environ.get("GOAL_MAX_STEPS", "25"))
TREE_DEPTH = int(os.environ.get("GOAL_TREE_DEPTH", "3"))
HISTORY_LINES = int(os.environ.get("GOAL_SHELL_HISTORY", "40"))


def _truthy(name: str, default: str = "1") -> bool:
    return os.environ.get(name, default).strip().lower() not in ("0", "false", "no", "off")


def _llm(system: str, user: str, *, temperature: float = 0.15) -> str:
    try:
        from arka.llm.cli import llm_complete

        out = llm_complete(system, user, temperature, task="agent").strip()
        if out:
            return re.sub(r"^```[a-zA-Z0-9]*\n*|\n*```$", "", out)
    except ImportError:
        pass
    from arka.paths import entry_script

    try:
        from arka.telemetry import inject_trace_env
    except ImportError:
        inject_trace_env = None  # type: ignore[assignment,misc]

    env = inject_trace_env() if inject_trace_env else None
    proc = subprocess.run(
        [
            sys.executable,
            str(entry_script("arka_llm.py")),
            "complete",
            "--system",
            system,
            "--user",
            user,
            "--temperature",
            str(temperature),
            "--task",
            "agent",
        ],
        capture_output=True,
        text=True,
        timeout=180,
        env=env,
    )
    if proc.returncode != 0:
        return ""
    return re.sub(r"^```[a-zA-Z0-9]*\n*|\n*```$", "", (proc.stdout or "").strip())


def _truncate(text: str, limit: int = OUTPUT_LIMIT) -> str:
    text = text or ""
    if len(text) <= limit:
        return text
    return text[:limit] + f"\n...(truncated, {len(text)} chars total)"


def _fish_history() -> str:
    try:
        proc = subprocess.run(
            ["fish", "-c", f"history --max={HISTORY_LINES}"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip()
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "(no fish history available)"


def _dir_context(cwd: Path, depth: int) -> tuple[str, str]:
    tree_proc = subprocess.run(
        [
            "find",
            ".",
            "-maxdepth",
            str(depth),
            "-mindepth",
            "1",
            "-not",
            "-path",
            "*/.*",
            "-print",
        ],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=30,
    )
    tree = ""
    if tree_proc.returncode == 0:
        lines = sorted(tree_proc.stdout.splitlines())[:80]
        tree = "\n".join(line.removeprefix("./") for line in lines)

    ls_proc = subprocess.run(
        ["fish", "-c", "command ls -lah | head -35"],
        cwd=cwd,
        capture_output=True,
        text=True,
        timeout=15,
    )
    listing = ls_proc.stdout.strip() if ls_proc.returncode == 0 else ""
    return tree, listing


def _read_file(path: str, cwd: Path) -> str:
    try:
        from arka.telemetry import mark_error, mark_ok, span
    except ImportError:
        span = None  # type: ignore[assignment,misc]

    ctx = (
        span("arka.tool.read_file", attributes={"arka.tool.file": path[:500]})
        if span is not None
        else _goal_null_context()
    )
    with ctx as current:
        target = (cwd / path).resolve()
        try:
            target.relative_to(cwd.resolve())
        except ValueError:
            if span is not None:
                mark_error(current, "path outside cwd")
            return f"Error: path outside cwd: {path}"
        if not target.is_file():
            if span is not None:
                mark_error(current, "not a file")
            return f"Error: not a file: {path}"
        try:
            data = target.read_text(encoding="utf-8", errors="replace")
        except OSError as exc:
            if span is not None:
                mark_error(current, str(exc), exc=exc)
            return f"Error reading {path}: {exc}"
        if span is not None:
            current.set_attribute("arka.tool.file_chars", len(data))
            mark_ok(current)
        return _truncate(data, 12000)


def _goal_null_context():
    from contextlib import nullcontext

    return nullcontext()


_CD_BLOCKED_HINT = (
    "cd is blocked — the working directory is already set to the repository root. "
    "Use ls, read files, pytest, or edit paths relative to CWD without cd."
)

_GIT_BLOCKED_HINT = (
    "Git is blocked unless the user explicitly asked for git in the goal. "
    "Continue with read/edit/test actions in the current working directory."
)

_MAX_INVALID_ACTIONS = 2
_MAX_EMPTY_ACTIONS = 4

_EMPTY_ACTION_RETRY_HINT = (
    "\n\nREMINDER: Return ONLY one complete JSON object with keys status, cmd, why "
    '(and file when status is read). No markdown fences.\n'
    'Example: {"status":"continue","cmd":"pytest -q tests/test_coding_tui.py","why":"run focused tests"}'
)

_FAILURE_OUTPUT_HINTS = (
    "invalid action",
    "unknown arka",
    "unknown skill",
    "skipped unknown",
    "could not",
    "not found",
)


def _strip_leading_cd_chain(cmd: str, cwd: Path) -> str:
    """Remove leading cd prefixes that cannot persist across goal-agent subprocess steps."""
    cmd = (cmd or "").strip()
    patterns = [
        rf"^cd\s+{re.escape(cwd.name)}/?\s*&&\s*",
        rf"^cd\s+{re.escape(str(cwd))}/?\s*&&\s*",
        r"^cd\s+\.\s*&&\s*",
    ]
    for pat in patterns:
        cmd = re.sub(pat, "", cmd, flags=re.IGNORECASE).strip()
    while True:
        match = re.match(r"(?i)^cd\s+([^;&|]+?)\s*&&\s*(.+)$", cmd)
        if not match:
            break
        target = match.group(1).strip().strip("\"'")
        if ".." in target or target.startswith("/"):
            break
        cmd = match.group(2).strip()
    return cmd


def _is_standalone_cd(cmd: str) -> bool:
    cmd = (cmd or "").strip()
    if not cmd:
        return False
    return bool(re.match(r"(?i)^cd(?:\s+[^;&|]+)?\s*$", cmd))


_PROSE_ACTION_PREFIXES = frozenset({
    "according", "analyze", "check", "design", "implement", "inspect", "map",
    "read", "search", "trace", "update", "use", "write", "the", "this",
})


def _looks_like_prose_action(cmd: str) -> bool:
    """Reject model narration accidentally emitted in the shell-action slot."""
    text = " ".join((cmd or "").split()).strip()
    if not text:
        return False
    first = text.split(maxsplit=1)[0].lower().rstrip(":,.;")
    if first not in _PROSE_ACTION_PREFIXES:
        return False
    # These are valid executable commands despite looking like prose.
    if first in {"read", "write", "use"} and len(text.split()) == 1:
        return False
    return True


def _is_testing_goal(goal: str) -> bool:
    text = " ".join((goal or "").lower().split()).strip()
    if re.fullmatch(
        r"(?:tests?|run\s+tests?|ci|lint|ruff|pytest|smoke|verify|validate|repo_health|quality)",
        text,
    ):
        return True
    return bool(
        re.search(
            r"(?i)\b(?:run|execute|rerun|test|testing|verify|validate)\b.*\btests?\b|"
            r"\btests?\b.*\b(?:repo|repository|folder|suite)\b|"
            r"\b(?:pytest|repo_health|lint_project)\b",
            goal,
        )
    )


def _is_test_action(cmd: str) -> bool:
    """Allow only useful inspection/test commands for a testing-focused goal."""
    lowered = (cmd or "").lower()
    if any(
        token in lowered
        for token in (
            "compose_3d",
            "3d model",
            "generate_image",
            "design_from_screenshot",
            "compose_slides",
            "compose_video",
            "model_to_image",
        )
    ):
        return False
    parts = (cmd or "").strip().split()
    if not parts:
        return False
    first = parts[0].lower()
    if first in {"pytest", "ruff", "mypy", "pyright", "coverage", "nosetests", "tox"}:
        return True
    if first in {"ls", "pwd", "cat", "head", "tail", "sed", "awk", "rg", "grep", "find", "file", "stat"}:
        return True
    if first in {"python", "python3", "uv", "poetry", "pipenv"}:
        return any(token in parts for token in ("pytest", "ruff", "mypy", "tox"))
    if first == "arka":
        return len(parts) > 1 and parts[1].lower() in {"ci", "repo_health", "lint_project", "route_audit", "review"}
    return False


_KNOWN_ARKA_ACTIONS = frozenset({
    "ci", "config", "describe", "doctor", "lint_project", "plugin", "plugins",
    "repo_health", "review", "route", "route_audit", "self", "skill", "skills",
    "coding-tui", "coding_tui", "goal", "mcp", "agent_hub", "frontend_loop",
})


def _is_unknown_arka_action(cmd: str) -> bool:
    parts = (cmd or "").strip().split()
    return len(parts) > 1 and parts[0].lower() == "arka" and parts[1].lower() not in _KNOWN_ARKA_ACTIONS


def _command_reported_success(code: int, out: str) -> bool:
    """Treat shell exit 0 as failure when output clearly reports an invalid/skipped action."""
    if code != 0:
        return False
    text = (out or "").lower()
    return not any(hint in text for hint in _FAILURE_OUTPUT_HINTS)


def _extract_json_object(text: str) -> str:
    """Pull a JSON object from raw LLM text, including fenced blocks."""
    text = (text or "").strip()
    fence = re.search(r"```(?:json)?\s*(\{.*?\})\s*```", text, re.S | re.I)
    if fence:
        return fence.group(1).strip()
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        return m.group(0).strip()
    return text


def _parse_step(raw: str) -> dict:
    text = _extract_json_object(raw)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        # The goal protocol is JSON-only. Never reinterpret prose, truncated
        # JSON, or vision descriptions as shell commands.
        return {"status": "invalid", "cmd": "", "why": "unparsed JSON action"}
    return {"status": "invalid", "cmd": "", "why": "invalid action object"}


def _security_gate(cmd: str, *, auto_yes: bool) -> bool:
    if _truthy("GOAL_SAFE_ONLY", "0"):
        try:
            from arka.core.security import check_action

            if check_action(cmd).status == "confirm":
                print(f"⊘ Skipped (safe-only): {cmd}", file=sys.stderr)
                return False
        except ImportError:
            pass
    try:
        from arka.core.security import check_action
    except ImportError:
        return True
    result = check_action(cmd)
    if result.status == "ok":
        return True
    if result.status == "block":
        print(f"🛡 Blocked: {result.reason}", file=sys.stderr)
        return False
    if result.status == "confirm":
        if auto_yes:
            print(f"⚠ Auto-approved ({result.category}): {cmd}", file=sys.stderr)
            return True
        if not sys.stdin.isatty():
            print(f"🛡 Needs confirm (non-interactive): {result.reason}", file=sys.stderr)
            return False
        try:
            answer = input(f"🛡 {result.reason}\n  Action: {cmd}\nProceed? [y/N]: ").strip()
        except EOFError:
            return False
        return answer.lower().startswith("y")
    return True


def _annotate_llm_http(span_obj: Any) -> None:
    """Propagate HTTP attrs from the last LLM call onto a parent span."""
    try:
        from arka.llm.fallback import llm_last_model
        from arka.telemetry import llm_http_span_attributes, set_http_span_attributes

        last = llm_last_model()
        if last:
            set_http_span_attributes(
                span_obj,
                method="POST",
                url=llm_http_span_attributes(last[0])["http.url"],
                status_code=200,
            )
            span_obj.set_attribute("gen_ai.provider.name", last[0])
            span_obj.set_attribute("gen_ai.request.model", last[1])
    except ImportError:
        pass


def _git_authorized(goal: str) -> bool:
    """Require explicit user intent before an agent can mutate/inspect Git."""
    text = goal.lower()
    return bool(re.search(r"\b(?:git|commit|pull|push|branch|merge|rebase|checkout|stash|cherry[- ]pick|diff)\b", text))


def _run_cmd(cmd: str, cwd: Path, *, auto_yes: bool, git_allowed: bool = False) -> tuple[int, str]:
    try:
        from arka.telemetry import mark_error, mark_ok, set_span_attributes, span
    except ImportError:
        span = None  # type: ignore[assignment,misc]
        set_span_attributes = None  # type: ignore[assignment,misc]

    shell_attrs: dict[str, Any] = {
        "arka.tool.command": cmd[:500],
        "arka.tool.kind": "subprocess",
        "process.executable.name": "fish",
        "process.command": cmd[:500],
    }
    ctx = (
        span("arka.tool.shell", attributes=shell_attrs)
        if span is not None
        else _goal_null_context()
    )
    with ctx as current:
        if re.match(r"(?i)^(?:arka\s+)?(?:coding[-_]tui|code_tui|goal)\b", cmd.strip()):
            if span is not None:
                mark_error(current, "recursive agent launch")
            return 2, "[skipped: recursive Arka agent launch; work in the current goal instead]"
        if _is_unknown_arka_action(cmd):
            if span is not None:
                mark_error(current, "unknown Arka action")
            return 2, "[skipped: unknown Arka action; choose a registered skill or shell command]"
        if re.search(r"(?i)(?:^|[;&|])\s*git(?:\s|$)", cmd) and not git_allowed:
            if span is not None:
                mark_error(current, "git authorization gate")
            return 2, "[skipped: Git actions require explicit user authorization]"
        if not _security_gate(cmd, auto_yes=auto_yes):
            if span is not None:
                mark_error(current, "security gate")
            return 2, "[skipped: security gate]"
        try:
            from arka.core.code_project import check_shell_scope, get_active_root

            scope_root = get_active_root()
            if scope_root is not None:
                scope_ok, scope_reason = check_shell_scope(cmd, root=scope_root)
                if not scope_ok:
                    if span is not None:
                        mark_error(current, "scope gate")
                    return 2, scope_reason
        except ImportError:
            pass
        try:
            proc = subprocess.run(
                ["fish", "-c", cmd],
                cwd=cwd,
                capture_output=True,
                text=True,
                timeout=int(os.environ.get("GOAL_CMD_TIMEOUT", "300")),
            )
            out = (proc.stdout or "") + (proc.stderr or "")
            code = proc.returncode
        except subprocess.TimeoutExpired:
            if span is not None:
                mark_error(current, "timeout")
            return 124, "Command timed out"
        except OSError as exc:
            if span is not None:
                mark_error(current, str(exc), exc=exc)
            return 1, str(exc)
        if span is not None:
            current.set_attribute("arka.tool.exit_code", code)
            current.set_attribute("process.exit_code", code)
            if set_span_attributes is not None:
                set_span_attributes(
                    current,
                    {
                        "arka.tool.result": "ok" if code == 0 else "error",
                    },
                )
            if code == 0:
                mark_ok(current)
            else:
                mark_error(current, f"exit {code}")
        return code, _truncate(out.strip())


def _platform_hint() -> str:
    try:
        from arka.platform_info import system

        plat = system()
    except ImportError:
        plat = sys.platform
    if plat == "macos":
        return "Host is macOS — use brew, open, pbcopy; avoid apt-only assumptions."
    if plat == "linux":
        return "Host is Linux — apt/snap/flatpak may apply."
    return f"Host platform: {plat}"


def _skills_list() -> str:
    try:
        proc = subprocess.run(
            ["fish", "-c", "functions -a | string match -r '^[a-z]' | head -80"],
            capture_output=True,
            text=True,
            timeout=15,
        )
        if proc.returncode == 0 and proc.stdout.strip():
            return proc.stdout.strip().replace("\n", ", ")
    except (OSError, subprocess.TimeoutExpired):
        pass
    return "(skills unavailable)"


def run_goal(
    goal: str,
    *,
    max_steps: int = DEFAULT_MAX,
    auto_yes: bool = False,
    auto_continue: bool | None = None,
    verify: bool = False,
    system_extra: str = "",
    cmd_hook: "callable[[str], tuple[int, str] | None] | None" = None,
) -> int:
    goal = " ".join(goal.split()).strip()
    if not goal:
        print("Usage: arka goal <describe what to accomplish>", file=sys.stderr)
        return 1

    if auto_continue is None:
        auto_continue = _truthy("GOAL_AUTO_CONTINUE", "1")

    project_root = None
    try:
        from arka.core.code_project import apply_env, get_active_root, is_scoped

        if is_scoped():
            project_root = get_active_root()
            apply_env()
    except ImportError:
        pass

    cwd = project_root or Path.cwd()
    git_allowed = _git_authorized(goal)
    if project_root is not None:
        os.chdir(project_root)
    tree, listing = _dir_context(cwd, TREE_DEPTH)
    shell_hist = _fish_history()
    skills = _skills_list()
    plat_hint = _platform_hint()
    recent_commands: list[str] = []
    blocked_cd_count = 0
    empty_action_count = 0
    invalid_action_count = 0

    system = f"""You are an autonomous shell agent (Butterfish Goal Mode style) on fish shell.
Each turn return ONLY valid JSON (no markdown fences):
{{"status":"continue"|"done"|"read","cmd":"one shell command or skill","why":"brief reason","file":"relative path when status is read"}}

Rules:
- One shell command OR one read per turn. status "read" loads a file into history (file key required).
- status "done" when the goal is fully achieved (cmd may be empty).
- Learn from HISTORY and SHELL_HISTORY; if a command failed, diagnose and try a fix.
- Prefer read-only inspection before destructive edits.
- Registered skills (invoke by name): {skills}
- {plat_hint}
- Commands run in fish syntax.
- Decompose complex goals across many small steps."""
    system += "\n- Never launch coding-tui, goal, or another interactive Arka agent; operate on the current workspace directly."
    system += f"\n- Working directory is already {cwd}. NEVER emit cd commands (standalone or chained); cd is blocked and wastes steps."
    if re.search(r"(?i)\b(test|tests|testing|verify|smoke|validate|ci|lint|pytest|repo_health)\b", goal):
        system += (
            "\n- This is a testing/verification goal: use repository inspection and actual test/lint commands. "
            "Do not answer with web research or explanatory prose; return an executable command or a read action."
        )
        system += (
            " Only use inspection, lint, or test commands; do not create unrelated artifacts or invoke creative skills."
        )
        system += (
            '\n- Good first actions: {"status":"continue","cmd":"pytest -q","why":"run test suite"} '
            'or {"status":"read","file":"pyproject.toml","why":"find test config"}.'
        )

    if system_extra:
        system += f"\n{system_extra.strip()}"
    try:
        from arka.agent.skill_hints import recommend_skill_hint

        hint = recommend_skill_hint(goal)
        if hint:
            system += f"\n- {hint}"
    except ImportError:
        pass

    if project_root is not None:
        system += f"\n- CODE PROJECT: all file edits must stay inside {project_root}."

    history = ""
    from arka.core.output import debug_hint, debug_msg, summarize_goal, user_msg

    user_msg(f"Goal agent: {summarize_goal(goal)}")
    debug_msg(f"Goal agent (full): {goal}")
    debug_msg(f"  cwd: {cwd} | max steps: {max_steps}")

    try:
        from arka.telemetry import mark_error, mark_ok, span
    except ImportError:
        span = None  # type: ignore[assignment,misc]

    goal_ctx = (
        span(
            "arka.agent.goal",
            attributes={
                "arka.agent.goal_text": goal[:500],
                "arka.agent.max_steps": max_steps,
                "arka.agent.cwd": str(cwd),
            },
        )
        if span is not None
        else _goal_null_context()
    )
    with goal_ctx as goal_span:
        for step in range(1, max_steps + 1):
            step_ctx = (
                span(
                    "arka.agent.goal.step",
                    attributes={"arka.agent.step": step, "arka.agent.max_steps": max_steps},
                )
                if span is not None
                else _goal_null_context()
            )
            with step_ctx as step_span:
                cd_reminder = ""
                if blocked_cd_count:
                    cd_reminder = (
                        f"\nREMINDER: CWD is already {cwd}. Do NOT use cd — pick ls, read, pytest, "
                        "or an edit command instead.\n"
                    )

                user = f"""GOAL: {goal}
CWD: {cwd}
{cd_reminder}
DIRECTORY (depth {TREE_DEPTH}):
{tree or '(empty)'}

FILE LISTING:
{listing or '(empty)'}

SHELL_HISTORY (recent commands in this fish session):
{shell_hist}

AGENT_HISTORY:
{history or '(none yet)'}

Step {step}/{max_steps} — return the NEXT action as JSON."""

                debug_msg(f"━━━ Goal step {step}/{max_steps} ━━━")
                user_msg(f"Step {step}/{max_steps}…")
                raw = _llm(system, user)
                if not raw:
                    print("LLM unavailable.", file=sys.stderr)
                    if span is not None:
                        mark_error(goal_span, "LLM unavailable")
                    return 1

                if span is not None:
                    _annotate_llm_http(step_span)

                parsed = _parse_step(raw)
                status = str(parsed.get("status") or "continue").lower()
                cmd = str(parsed.get("cmd") or "").strip()
                why = str(parsed.get("why") or "").strip()
                file_path = str(parsed.get("file") or "").strip()

                if status == "invalid":
                    from arka.core.mode import is_debug_mode

                    if is_debug_mode():
                        debug_msg(f"  raw LLM (truncated): {_truncate(raw, 500)}")
                    retry_user = (
                        user
                        + "\n\nREMINDER: Return ONLY one complete JSON object with keys "
                        'status, cmd, why (and file when status is read). No markdown fences.'
                    )
                    raw_retry = _llm(system, retry_user)
                    if raw_retry:
                        if is_debug_mode():
                            debug_msg(f"  retry raw (truncated): {_truncate(raw_retry, 500)}")
                        parsed = _parse_step(raw_retry)
                        status = str(parsed.get("status") or "continue").lower()
                        cmd = str(parsed.get("cmd") or "").strip()
                        why = str(parsed.get("why") or "").strip()
                        file_path = str(parsed.get("file") or "").strip()
                if span is not None:
                    step_span.set_attribute("arka.agent.status", status)
                    if why:
                        step_span.set_attribute("arka.agent.why", why[:500])
                    try:
                        from arka.telemetry.metrics import record_goal_step

                        record_goal_step(step=step, status=status)
                    except ImportError:
                        pass

                if status == "done":
                    print("✓ Goal complete.", file=sys.stderr)
                    if why:
                        print(f"  {why}", file=sys.stderr)
                    try:
                        from arka.agent.git_changes import format_changed_files

                        changed_files = format_changed_files(cwd)
                        if changed_files != "○ No changes.":
                            print(changed_files, file=sys.stderr)
                    except ImportError:
                        pass
                    if verify:
                        from arka.agent.core import loop_verify

                        done, summary = loop_verify(goal, history)
                        if done:
                            print(f"✓ Verified: {summary}", file=sys.stderr)
                        else:
                            print(f"⚠ Verify uncertain: {summary}", file=sys.stderr)
                    if span is not None:
                        mark_ok(goal_span)
                    return 0

                if status == "invalid":
                    invalid_action_count += 1
                    print(
                        "Invalid action from agent; requesting a complete JSON action.",
                        file=sys.stderr,
                    )
                    history += (
                        f"\n--- step {step} (invalid) ---\n"
                        "reason: unparsed JSON action — return one complete JSON object only\n"
                    )
                    if invalid_action_count >= _MAX_INVALID_ACTIONS:
                        print(
                            "Repeated invalid actions; stopping. "
                            "Try /plan then /run again, or rephrase the goal.",
                            file=sys.stderr,
                        )
                        if span is not None:
                            mark_error(goal_span, "invalid action")
                        return 1
                    continue

                if status == "read" and file_path:
                    content = _read_file(file_path, cwd)
                    print(f"  📄 read {file_path}", file=sys.stderr)
                    history += f"\n--- step {step} (read) ---\nfile: {file_path}\ncontent:\n{content}\n"
                    continue

                if not cmd:
                    retry_user = user + _EMPTY_ACTION_RETRY_HINT
                    raw_retry = _llm(system, retry_user)
                    if raw_retry:
                        parsed = _parse_step(raw_retry)
                        status = str(parsed.get("status") or "continue").lower()
                        cmd = str(parsed.get("cmd") or "").strip()
                        why = str(parsed.get("why") or "").strip()
                        file_path = str(parsed.get("file") or "").strip()

                if not cmd:
                    empty_action_count += 1
                    print("Empty action from agent; requesting a complete next action.", file=sys.stderr)
                    history += (
                        f"\n--- step {step} (invalid) ---\n"
                        "reason: empty action — return JSON with status and cmd\n"
                        f"{_EMPTY_ACTION_RETRY_HINT.strip()}\n"
                    )
                    if empty_action_count >= _MAX_EMPTY_ACTIONS:
                        print("Repeated empty actions; stopping.", file=sys.stderr)
                        if span is not None:
                            mark_error(goal_span, "empty action")
                        return 1
                    continue

                if _looks_like_prose_action(cmd):
                    invalid_action_count += 1
                    print("Rejected prose from action slot; requesting an executable command.", file=sys.stderr)
                    history += f"\n--- step {step} (invalid) ---\ncmd: {cmd}\nreason: prose action\n"
                    if invalid_action_count >= _MAX_INVALID_ACTIONS:
                        print("Repeated prose actions; stopping.", file=sys.stderr)
                        if span is not None:
                            mark_error(goal_span, "prose action")
                        return 1
                    continue

                if _is_testing_goal(goal) and not _is_test_action(cmd):
                    invalid_action_count += 1
                    print("Rejected non-test action for testing goal; requesting a test or inspection command.", file=sys.stderr)
                    history += f"\n--- step {step} (invalid) ---\ncmd: {cmd}\nreason: non-test action\n"
                    if invalid_action_count >= _MAX_INVALID_ACTIONS:
                        print("Repeated non-test actions; stopping.", file=sys.stderr)
                        if span is not None:
                            mark_error(goal_span, "non-test action")
                        return 1
                    continue

                # Each action runs in a fresh subprocess with cwd already set;
                # standalone directory changes cannot persist between steps.
                cmd = _strip_leading_cd_chain(cmd, cwd)
                if _is_standalone_cd(cmd):
                    blocked_cd_count += 1
                    print("  ⊘ skipped cd (Arka already set the repository working directory)", file=sys.stderr)
                    history += (
                        f"\n--- step {step} (skipped) ---\ncmd: {cmd}\nreason: {_CD_BLOCKED_HINT}\n"
                    )
                    if blocked_cd_count >= 4:
                        print(
                            "Repeated cd actions detected; stopping so the agent can choose a real action.",
                            file=sys.stderr,
                        )
                        if span is not None:
                            mark_error(goal_span, "repeated cd")
                        return 1
                    continue

                if recent_commands.count(cmd) >= 2:
                    print("Repeated action detected; stopping to avoid wasting steps.", file=sys.stderr)
                    if span is not None:
                        mark_error(goal_span, "repeated action")
                    return 1
                recent_commands.append(cmd)

                if cmd_hook is not None:
                    blocked = cmd_hook(cmd)
                    if blocked is not None:
                        code, out = blocked
                        print(f"  ⊘ {out}", file=sys.stderr)
                        history += (
                            f"\n--- step {step} (blocked) ---\ncmd: {cmd}\nexit: {code}\noutput:\n{out}\n"
                        )
                        continue

                print(f"  → {cmd}", file=sys.stderr)
                if why:
                    print(f"    {why}", file=sys.stderr)

                code, out = _run_cmd(cmd, cwd, auto_yes=auto_yes, git_allowed=git_allowed)
                if _command_reported_success(code, out):
                    print("  ✓ exit 0", file=sys.stderr)
                elif code == 2:
                    print("  ⊘ skipped", file=sys.stderr)
                elif code == 0:
                    print("  ⊘ invalid (exit 0 but action failed)", file=sys.stderr)
                else:
                    print(f"  ✗ exit {code}", file=sys.stderr)
                    try:
                        from arka.telemetry import record_span_event

                        record_span_event(
                            "agent.self_heal",
                            {
                                "arka.agent.step": step,
                                "arka.tool.exit_code": code,
                                "arka.agent.note": "agent will diagnose and retry on next step",
                            },
                        )
                        from arka.telemetry.logs import emit_log

                        emit_log(
                            f"self-heal after failed command (exit {code})",
                            level="warn",
                            attributes={
                                "arka.agent.step": step,
                                "arka.tool.exit_code": code,
                                "arka.event": "agent.self_heal",
                            },
                        )
                    except ImportError:
                        pass
                if out:
                    from arka.core.mode import is_debug_mode

                    lines = out.splitlines()
                    if is_debug_mode():
                        for line in lines[:30]:
                            debug_msg(f"    {line}")
                        if len(lines) > 30:
                            debug_msg(f"    ...({len(lines) - 30} more lines)")
                    elif code != 0 and lines:
                        user_msg(f"  {lines[0][:120]}")
                        if len(lines) > 1:
                            user_msg(f"  ({debug_hint()})")

                history_line = f"\n--- step {step} ---\ncmd: {cmd}\nexit: {code}\nwhy: {why}\noutput:\n{out}\n"
                if code == 2 and "Git actions require explicit user authorization" in out:
                    history_line += f"hint: {_GIT_BLOCKED_HINT}\n"
                history += history_line

                if not auto_continue and not auto_yes and sys.stdin.isatty():
                    try:
                        cont = input("  Continue goal? [Y/n/q]: ").strip().lower()
                    except EOFError:
                        cont = "y"
                    if cont in ("q", "quit"):
                        print("Stopped.", file=sys.stderr)
                        return 0
                    if cont in ("n", "no"):
                        print(f"Stopped after step {step}.", file=sys.stderr)
                        return 0

        print(f"Max steps ({max_steps}) reached.", file=sys.stderr)
        if span is not None:
            mark_error(goal_span, "max steps reached")
        return 1


def goal_engine_name() -> str:
    return os.environ.get("GOAL_ENGINE", "auto").strip().lower() or "auto"


def main(argv: list[str] | None = None) -> int:
    from arka.paths import load_env_file

    load_env_file()

    parser = argparse.ArgumentParser(prog="arka goal", description="Arka autonomous goal agent")
    parser.add_argument("goal", nargs="*", help="Goal description")
    parser.add_argument("-n", "--max", type=int, default=DEFAULT_MAX)
    parser.add_argument("-y", "--yes", action="store_true", help="Auto-approve risky actions / installs")
    parser.add_argument("-v", "--verify", action="store_true")
    parser.add_argument("--no-auto-continue", action="store_true")
    parser.add_argument("-b", "--butterfish", action="store_true", help="Butterfish Goal Mode (interactive shell)")
    parser.add_argument("--unsafe", action="store_true", help="Butterfish !! unsafe mode hint")
    args = parser.parse_args(argv[1:] if argv is not None else None)

    goal = " ".join(args.goal).strip()
    engine = goal_engine_name()

    if args.butterfish or engine == "butterfish":
        from arka.integrations.butterfish import launch_shell

        return launch_shell(goal=goal, unsafe=args.unsafe, auto_yes=args.yes)

    if engine == "off" or engine == "legacy":
        print("Goal engine disabled (ARKA_GOAL_ENGINE=off). Use: agent_loop", file=sys.stderr)
        return 1

    return run_goal(
        goal,
        max_steps=args.max,
        auto_yes=args.yes,
        auto_continue=not args.no_auto_continue,
        verify=args.verify,
    )


if __name__ == "__main__":
    raise SystemExit(main())
