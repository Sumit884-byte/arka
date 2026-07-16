"""Small dependency-free terminal UI for the Arka coding agent."""
from __future__ import annotations

import argparse
import atexit
import json
import re
import subprocess
from pathlib import Path

_CODING_TUI_CLI_RE = re.compile(
    r"(?i)^(?:arka\s+)?(?:coding[-_ ]?tui|code_tui)\b(?:\s+(.*))?$"
)
_CODING_TUI_NL_RE = re.compile(
    r"(?i)\b(?:open|start|launch)\s+(?:the\s+)?coding\s+tui\b|"
    r"^coding\s+tui\b|"
    r"\bstart\s+coding\s+workspace\b"
)

SLASH_COMMANDS = (
    "/help",
    "/status",
    "/plan",
    "/run",
    "/history",
    "/clear",
    "/diff",
    "/files",
    "/open",
    "/ci",
    "/review",
    "/quit",
    "/exit",
)

HELP = (
    "Commands: /help, /status, /plan <goal>, /run <goal>, /history, /clear, "
    "/diff, /files <pattern>, /open <path>, /ci, /review, /quit. "
    "Plain text is treated as a plan request; approve with y to execute immediately."
)

WELCOME_TIPS = (
    "Tip: /plan <goal> builds a reviewable plan; approve with y to execute immediately.",
    "Tip: /diff, /files <pattern>, /open <path> inspect the repo without leaving the TUI.",
    "Tip: /ci runs fast gates; /review summarizes staged changes.",
    "Tip: plain text is shorthand for /plan — approve with y to execute immediately.",
)

HISTORY_FILE = Path.home() / ".cache" / "arka" / "coding_tui_history"


def route_command(text: str) -> str:
    raw = (text or "").strip()
    if not raw:
        return ""
    match = _CODING_TUI_CLI_RE.match(raw)
    if match:
        rest = (match.group(1) or "").strip() or "."
        return f"coding-tui {rest}"
    if _CODING_TUI_NL_RE.search(raw):
        return "coding-tui ."
    return ""


def _git_value(root: Path, *args: str) -> str:
    try:
        proc = subprocess.run(
            ["git", "-C", str(root), *args],
            capture_output=True,
            text=True,
            timeout=3,
            check=False,
        )
    except (OSError, subprocess.SubprocessError):
        return ""
    return (proc.stdout or "").strip()


def _dirty_count(root: Path) -> int:
    return len(_git_value(root, "status", "--short").splitlines())


def _code_project_initialized(root: Path) -> bool:
    try:
        from arka.core.code_project import get_active_root, is_within_project

        active = get_active_root()
        return active is not None and is_within_project(root, root=active)
    except ImportError:
        return False


def status(root: Path) -> str:
    files = sum(1 for p in root.rglob("*") if p.is_file() and ".git" not in p.parts)
    branch = _git_value(root, "rev-parse", "--abbrev-ref", "HEAD") or "unknown"
    dirty = _dirty_count(root)
    code_project = "yes" if _code_project_initialized(root) else "no"
    lines = [
        f"repo: {root}",
        f"branch: {branch}",
        f"dirty files: {dirty}",
        f"files: {files}",
        f"code project initialized: {code_project}",
        "Tip: /plan builds a reviewable plan; approve with y to execute immediately.",
    ]
    return "\n".join(lines)


def plan_preview(goal: str, root: Path) -> str:
    """Inspect the repository and return a goal-specific local plan."""
    goal = goal.strip()
    files = sum(1 for p in root.rglob("*") if p.is_file() and ".git" not in p.parts)
    lowered = goal.lower()
    relevant: list[str] = []
    for candidate in ("pyproject.toml", "package.json", "Cargo.toml", "src", "tests", "docs"):
        path = root / candidate
        if path.exists():
            relevant.append(str(path.relative_to(root)) + ("/" if path.is_dir() else ""))
    changed = _dirty_count(root)
    focus = "source modules and their tests"
    if any(word in lowered for word in ("route", "routing", "nl", "command")):
        focus = "routing/dispatch code and NL routing coverage"
        relevant += ["src/arka/routing/", "tests/test_nl_routing_coverage.py"]
    elif any(word in lowered for word in ("test", "ci", "quality")):
        focus = "CI/dev-tool gates and focused regression tests"
        relevant += ["src/arka/agent/dev_tools.py", "tests/"]
    elif any(word in lowered for word in ("model", "llm", "inference")):
        focus = "model selection/fallback code and provider tests"
        relevant += ["src/arka/llm/", "tests/test_llm_fallback.py"]
    elif any(word in lowered for word in ("improve", "devtool", "developer", "arka")):
        focus = "core dispatch, symbolic routing, developer tools, and their regression coverage"
        relevant += [
            "src/arka/dispatch.py",
            "src/arka/router.py",
            "src/arka/agent/dev_tools.py",
            "tests/test_nl_routing_coverage.py",
        ]
    relevant = list(dict.fromkeys(relevant))
    proposals: list[tuple[str, str]] = []
    if "routing" in focus:
        proposals = [
            ("src/arka/router.py", "adjust route precedence and offline fallback behavior"),
            ("src/arka/dispatch.py", "ensure the selected route reaches the correct skill"),
            ("src/arka/agent/dev_tools.py", "extend the developer-tool gate or command behavior"),
            ("tests/test_nl_routing_coverage.py", "lock in natural-language route parity"),
            ("docs/guides/repo-health.mdx", "document the user-facing command and verification"),
        ]
    elif "model" in focus:
        proposals = [
            ("src/arka/llm/fallback.py", "update provider/model fallback selection"),
            ("src/arka/core/model_optimizer.py", "apply hardware and capability-aware choice"),
            ("tests/test_llm_fallback.py", "cover fallback order and unavailable providers"),
            ("docs/guides/models.mdx", "document configuration and fallback behavior"),
        ]
    else:
        proposals = [
            ("src/arka/agent/dev_tools.py", "implement the concrete developer-tool improvement"),
            ("src/arka/router.py", "expose it through symbolic/NL routing when applicable"),
            ("src/arka/dispatch.py", "wire the route to execution and safety checks"),
            ("tests/test_dev_tools.py", "add focused behavior and failure-mode coverage"),
            ("docs/guides/repo-health.mdx", "document the command, prerequisites, and verification"),
        ]
    proposals = [(path, why) for path, why in proposals if (root / path).exists() or path.startswith("tests/")]
    lines = [
        f"Plan for: {goal}",
        f"Repository: {root} ({files} files)",
        f"Focus: {focus}",
        "Relevant paths: " + (", ".join(relevant) if relevant else "repository source and tests"),
        "Proposed files:",
        *[f"  - {path} — {why}" for path, why in proposals],
        f"Working tree: {changed} changed path(s)",
        "1. Read the listed modules and project rules; map the current call path and existing extension points.",
        f"2. Trace {focus}; identify one measurable gap (missing route, unsafe dispatch, weak gate, or test hole) before editing.",
        "3. Implement the smallest end-to-end change across routing, dispatch, and user-facing output where applicable.",
        "4. Add a table-driven regression test for the request and preserve unrelated behavior/configuration.",
        "5. Run the focused suite, Ruff/lint, and inspect git diff for unrelated changes before proposing follow-ups.",
        "Review this plan — approve with y to execute immediately.",
    ]
    return "\n".join(lines)


def _format_llm_plan(goal: str, root: Path, data: dict) -> str:
    summary = str(data.get("summary") or "").strip()
    steps = [str(step).strip() for step in (data.get("steps") or []) if str(step).strip()]
    files = data.get("files") or []
    lines = [
        f"Plan for: {goal}",
        f"Repository: {root}",
        "Source: LLM plan-only (no execution)",
    ]
    if summary:
        lines.extend(["", f"Summary: {summary}"])
    if files:
        lines.extend(["", "Files to touch:"])
        for item in files:
            if isinstance(item, dict):
                path = str(item.get("path") or item.get("file") or "").strip()
                reason = str(item.get("reason") or item.get("action") or "").strip()
                if path:
                    lines.append(f"  - {path}" + (f" — {reason}" if reason else ""))
            elif item:
                lines.append(f"  - {item}")
    if steps:
        lines.extend(["", "Steps:"])
        lines.extend(f"  {index}. {step}" for index, step in enumerate(steps, 1))
    lines.extend(
        [
            "",
            f"Working tree: {_dirty_count(root)} changed path(s)",
            "Review this plan — approve with y to execute immediately.",
        ]
    )
    return "\n".join(lines)


def llm_plan(goal: str, root: Path) -> str | None:
    """Return a formatted plan from the LLM, or None when unavailable."""
    from arka.agent.core import _llm, memory_context_for

    goal = goal.strip()
    if not goal:
        return None

    arka_tool_hint = (
        "Prefer existing Arka tools when they fit the task. "
        "Examples include repo_health, lint_project, pr_check, review, route_audit, "
        "self_improve, design_from_screenshot, compose_slides, urlkit, mcp, agent_hub, "
        "frontend_loop, and skill scaffolding."
    )
    plan_system = (
        "You are a repo-scoped coding planner. Return JSON only. "
        "Do not execute commands; produce a reviewable plan only. "
        '{"summary":"one-line plan", "steps":["human-readable step", ...], '
        '"files":[{"path":"relative/path", "reason":"why touch it"}]}'
    )
    plan_user = f"Repo: {root}\nGoal: {goal}\nBranch: {_git_value(root, 'rev-parse', '--abbrev-ref', 'HEAD')}\n"
    plan_user += f"Dirty files: {_dirty_count(root)}\n"
    plan_user += arka_tool_hint + "\n"
    mem = memory_context_for(goal)
    if mem:
        plan_user += mem + "\n"
    try:
        from arka.agent.design_memory import context as design_context

        design_mem = design_context()
        if design_mem:
            plan_user += design_mem + "\n"
    except ImportError:
        pass
    local_hint = plan_preview(goal, root)
    plan_user += "\nLocal repository hints (use when helpful, do not copy verbatim):\n" + local_hint[:4000] + "\n"

    plan_raw = _llm(plan_system, plan_user, task="agent")
    if not plan_raw:
        return None
    try:
        data = json.loads(re.sub(r"^```[a-zA-Z0-9]*\n*|\n*```$", "", plan_raw.strip()))
    except json.JSONDecodeError:
        return None
    if not isinstance(data, dict):
        return None
    if not (data.get("summary") or data.get("steps") or data.get("files")):
        return None
    return _format_llm_plan(goal, root, data)


def generate_plan(goal: str, root: Path) -> tuple[str, str]:
    """Return (plan_text, source) where source is 'llm' or 'local'."""
    llm_text = llm_plan(goal, root)
    if llm_text:
        return llm_text, "llm"
    return plan_preview(goal, root), "local"


def _git_diff_stat(root: Path) -> str:
    diff = _git_value(root, "diff", "--stat")
    if not diff:
        return "No changes (git diff --stat is empty)."
    return diff


def _list_files(root: Path, pattern: str) -> str:
    pattern = (pattern or "").strip()
    if not pattern:
        return "Usage: /files <pattern>  (e.g. /files '*.py' or /files coding_tui)"
    matches: list[str] = []
    glob_pattern = pattern if any(ch in pattern for ch in "*?[]") else f"*{pattern}*"
    for path in sorted(root.rglob(glob_pattern.lstrip("./"))):
        if ".git" in path.parts:
            continue
        if path.is_file():
            matches.append(str(path.relative_to(root)))
        if len(matches) >= 40:
            break
    if not matches:
        return f"No files match: {pattern}"
    suffix = f"\n…({len(matches)} shown, limit 40)" if len(matches) >= 40 else ""
    return "\n".join(matches) + suffix


def _open_file_head(root: Path, rel_path: str, *, lines: int = 40) -> str:
    rel_path = (rel_path or "").strip()
    if not rel_path:
        return "Usage: /open <path>"
    target = (root / rel_path).resolve()
    try:
        target.relative_to(root.resolve())
    except ValueError:
        return f"Path outside repo: {rel_path}"
    if not target.is_file():
        return f"Not a file: {rel_path}"
    try:
        content = target.read_text(encoding="utf-8", errors="replace").splitlines()
    except OSError as exc:
        return f"Error reading {rel_path}: {exc}"
    head = content[:lines]
    body = "\n".join(head)
    if len(content) > lines:
        body += f"\n…({len(content) - lines} more lines)"
    return f"{rel_path} ({len(content)} lines)\n{body}"


def coding_tui_system_extra(root: Path, goal: str) -> str:
    """Goal-agent hints when /run is launched from the coding TUI."""
    lowered = goal.lower()
    tui_hint = ""
    if any(word in lowered for word in ("tui", "terminal", "coding-tui", "coding tui", "interface", "ui")):
        tui_hint = (
            "- For TUI/interface goals, prefer editing src/arka/agent/coding_tui.py first.\n"
        )
    return (
        f"Coding TUI context: working directory is already {root}. Never use cd.\n"
        "- Do not run git pull, git commit, or other git commands unless the user explicitly asked for git.\n"
        "- Prefer read (status read) and file edits over shell navigation.\n"
        "- Prefer existing Arka tools (repo_health, lint_project, review, ci) over raw shell when applicable.\n"
        f"{tui_hint}"
        "- Make concrete file edits under src/ and tests/; verify with pytest on changed modules."
    )


def prepare_prompt(prompt: str) -> tuple[str, str, bool]:
    """Optimize once and return the model prompt, summary, and changed flag."""
    from arka.agent.prompt_optimize import optimize_user_prompt
    from arka.core.output import summarize_goal

    result = optimize_user_prompt(prompt)
    return result.optimized, summarize_goal(result.optimized, max_len=120), result.changed


def clear_screen() -> None:
    print("\033[2J\033[H", end="")


def print_welcome(repo: Path) -> None:
    print(f"Arka coding TUI — {repo}")
    for tip in WELCOME_TIPS:
        print(tip)
    print(HELP)


def _setup_readline() -> None:
    try:
        import readline
    except ImportError:
        return

    def completer(text: str, state: int) -> str | None:
        buffer = readline.get_line_buffer()
        if buffer.startswith("/"):
            options = [command for command in SLASH_COMMANDS if command.startswith(text)]
        else:
            options = []
        return options[state] if state < len(options) else None

    readline.set_completer(completer)
    readline.parse_and_bind("tab: complete")
    try:
        HISTORY_FILE.parent.mkdir(parents=True, exist_ok=True)
        readline.read_history_file(str(HISTORY_FILE))
    except OSError:
        return

    def _save_history() -> None:
        try:
            readline.write_history_file(str(HISTORY_FILE))
        except OSError:
            pass

    atexit.register(_save_history)


def _prompt_user(question: str) -> str:
    try:
        return input(question).strip().lower()
    except (EOFError, KeyboardInterrupt):
        return ""


def _execute_goal(
    goal: str,
    repo: Path,
    *,
    last_plan: str | None,
    code_agent,
) -> int:
    goal, summary, changed = prepare_prompt(goal)
    if changed:
        print(f"Prompt improved: {summary}")
    rc = code_agent(
        goal,
        repo=str(repo),
        plan_context=last_plan or "",
        system_extra=coding_tui_system_extra(repo, goal),
    )
    if rc == 0:
        print("Done. Next: `arka ci --changed` to verify edited files.")
    else:
        print(f"Run finished with exit code {rc}. Inspect output, then try `arka ci --changed`.")
    return rc


def _handle_plan(
    original_goal: str,
    repo: Path,
    *,
    last_plan: str | None,
    pending_goal: str | None,
    plan_approved: bool,
    code_agent,
) -> tuple[str | None, str | None, bool]:
    goal = original_goal.strip()
    if not goal:
        print("Usage: /plan <goal>")
        return last_plan, pending_goal, plan_approved

    _, summary, changed = prepare_prompt(goal)
    if changed:
        print(f"Prompt improved: {summary}")

    plan_text, source = generate_plan(goal, repo)
    if source == "local":
        print("LLM unavailable — using local repository plan.")
    print(plan_text)
    answer = _prompt_user("Approve this plan? [y/N]: ")
    approved = answer in {"y", "yes", "approve"}
    if approved:
        print("Plan approved — executing…")
        _execute_goal(goal, repo, last_plan=plan_text, code_agent=code_agent)
    else:
        print("Plan not approved. Use /run when ready.")
    return plan_text, goal, approved


def run(root: str = ".") -> int:
    repo = Path(root).expanduser().resolve()
    from arka.agent.core import code_agent

    _setup_readline()
    print_welcome(repo)
    history: list[str] = []
    last_plan: str | None = None
    pending_goal: str | None = None
    plan_approved = False
    while True:
        try:
            line = input(f"arka ({repo.name})> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return 0
        if not line:
            continue
        if line == "/clear":
            clear_screen()
            history.clear()
            last_plan = None
            pending_goal = None
            plan_approved = False
            print_welcome(repo)
            print("Session history and pending plan cleared.")
            continue
        history.append(line)
        if line in {"/quit", "/exit", "quit", "exit"}:
            return 0
        if line == "/help":
            print(HELP)
        elif line == "/status":
            print(status(repo))
            print(f"history: {len(history)} command(s)")
        elif line.startswith("/plan "):
            last_plan, pending_goal, plan_approved = _handle_plan(
                line[6:].strip(),
                repo,
                last_plan=last_plan,
                pending_goal=pending_goal,
                plan_approved=plan_approved,
                code_agent=code_agent,
            )
        elif line == "/run" or line.startswith("/run "):
            if last_plan and not plan_approved:
                print("Plan has not been approved. Run /plan <goal> and answer yes before /run.")
                continue
            requested_goal = line[4:].strip() or pending_goal
            if not requested_goal:
                print("Usage: /run <goal>, or approve a plan first and use /run.")
                continue
            if last_plan:
                print("Executing the last reviewed plan…")
            _execute_goal(requested_goal, repo, last_plan=last_plan, code_agent=code_agent)
        elif line == "/history":
            if not history:
                print("No commands yet.")
            else:
                for index, command in enumerate(history, 1):
                    print(f"{index:>3}  {command}")
        elif line == "/diff":
            print(_git_diff_stat(repo))
        elif line.startswith("/files "):
            print(_list_files(repo, line[7:].strip()))
        elif line.startswith("/open "):
            print(_open_file_head(repo, line[6:].strip()))
        elif line == "/ci":
            from arka.agent.dev_tools import ci_text

            print(ci_text(repo, changed_only=True))
        elif line == "/review":
            from arka.agent.dev_tools import review_text

            print(review_text(repo, staged=True))
        elif line.startswith("/"):
            print(f"Unknown command. {HELP}")
        else:
            last_plan, pending_goal, plan_approved = _handle_plan(
                line,
                repo,
                last_plan=last_plan,
                pending_goal=pending_goal,
                plan_approved=plan_approved,
                code_agent=code_agent,
            )
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka coding-tui")
    parser.add_argument("path", nargs="?", default=".")
    return run(parser.parse_args(argv).path)


if __name__ == "__main__":
    raise SystemExit(main())
