#!/usr/bin/env python3
"""Autonomous goal agent — Butterfish-style multi-step loop with plan + shell history."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
from pathlib import Path

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


def _parse_step(raw: str) -> dict:
    text = raw.strip()
    text = re.sub(r"^```json\s*", "", text, flags=re.I)
    text = re.sub(r"```$", "", text).strip()
    m = re.search(r"\{.*\}", text, re.S)
    if m:
        text = m.group(0)
    try:
        data = json.loads(text)
        if isinstance(data, dict):
            return data
    except json.JSONDecodeError:
        pass
    return {"status": "continue", "cmd": text, "why": "unparsed LLM output"}


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


def _run_cmd(cmd: str, cwd: Path, *, auto_yes: bool) -> tuple[int, str]:
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
    if project_root is not None:
        os.chdir(project_root)
    tree, listing = _dir_context(cwd, TREE_DEPTH)
    shell_hist = _fish_history()
    skills = _skills_list()
    plat_hint = _platform_hint()

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

    if system_extra:
        system += f"\n{system_extra.strip()}"

    if project_root is not None:
        system += f"\n- CODE PROJECT: all file edits must stay inside {project_root}."

    history = ""
    print(f"Goal agent: {goal}", file=sys.stderr)
    print(f"  cwd: {cwd} | max steps: {max_steps}", file=sys.stderr)

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
                    f"arka.agent.goal.step",
                    attributes={"arka.agent.step": step, "arka.agent.max_steps": max_steps},
                )
                if span is not None
                else _goal_null_context()
            )
            with step_ctx as step_span:
                user = f"""GOAL: {goal}
CWD: {cwd}

DIRECTORY (depth {TREE_DEPTH}):
{tree or '(empty)'}

FILE LISTING:
{listing or '(empty)'}

SHELL_HISTORY (recent commands in this fish session):
{shell_hist}

AGENT_HISTORY:
{history or '(none yet)'}

Step {step}/{max_steps} — return the NEXT action as JSON."""

                print(f"━━━ Goal step {step}/{max_steps} ━━━", file=sys.stderr)
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

                if status == "read" and file_path:
                    content = _read_file(file_path, cwd)
                    print(f"  📄 read {file_path}", file=sys.stderr)
                    history += f"\n--- step {step} (read) ---\nfile: {file_path}\ncontent:\n{content}\n"
                    continue

                if not cmd:
                    print("Empty command from agent; stopping.", file=sys.stderr)
                    if span is not None:
                        mark_error(goal_span, "empty command")
                    return 1

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

                code, out = _run_cmd(cmd, cwd, auto_yes=auto_yes)
                if code == 0:
                    print("  ✓ exit 0", file=sys.stderr)
                elif code == 2:
                    print("  ⊘ skipped", file=sys.stderr)
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
                    for line in out.splitlines()[:30]:
                        print(f"    {line}", file=sys.stderr)
                    if out.count("\n") > 30:
                        print("    ...(more lines)", file=sys.stderr)

                history += f"\n--- step {step} ---\ncmd: {cmd}\nexit: {code}\nwhy: {why}\noutput:\n{out}\n"

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
