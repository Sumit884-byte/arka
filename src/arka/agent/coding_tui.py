"""Small dependency-free terminal UI for the Arka coding agent."""
from __future__ import annotations

import argparse
import atexit
import json
import os
import re
import subprocess
import sys
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
    "/test",
    "/scaffold",
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
    "Commands: /help, /status, /plan <goal>, /run <goal>, /test [path], /scaffold 3d, /history, /clear, "
    "/diff, /files <pattern>, /open <path>, /ci, /review, /quit. "
    "/test runs tests read-only, then one auto-fix pass on failure (--no-fix to skip). "
    "/run tests lets a read-only agent choose repository tests; use --fix to repair failures. "
    "/scaffold 3d writes a React + Three.js space scene and runs npm install (trusted template). "
    "Add --run to start the Vite dev server after install. "
    "Plain text is treated as a plan request; approve with y to execute immediately."
)

WELCOME_TIPS = (
    "Tip: /plan <goal> builds a reviewable plan; approve with y to execute immediately.",
    "Tip: /diff, /files <pattern>, /open <path> inspect the repo without leaving the TUI.",
    "Tip: /test [path] runs tests read-only and auto-fixes once on failure (--no-fix to skip).",
    "Tip: /ci runs fast gates; /review summarizes staged changes.",
    "Tip: plain text is shorthand for /plan — approve with y to execute immediately.",
)

HISTORY_FILE = Path.home() / ".cache" / "arka" / "coding_tui_history"

DETERMINISTIC_SHORT_GOALS = frozenset({"ci", "lint", "review", "ruff"})
FLEXIBLE_TEST_GOALS = frozenset({"tests", "run tests", "test"})


def _normalize_goal_text(text: str) -> str:
    return " ".join((text or "").lower().split()).strip()


def _parse_run_request(text: str) -> tuple[str, bool, bool]:
    """Return (goal, allow_fix, auto_fix) from /run input."""
    raw = (text or "").strip()
    allow_fix = bool(re.search(r"(?:^|\s)--fix(?:\s|$)", raw, re.I))
    auto_fix = not bool(re.search(r"(?:^|\s)--no-fix(?:\s|$)", raw, re.I))
    goal = re.sub(r"(?:^|\s)--fix(?:\s|$)", " ", raw, flags=re.I)
    goal = re.sub(r"(?:^|\s)--no-fix(?:\s|$)", " ", goal, flags=re.I).strip()
    goal = " ".join(goal.split())
    return goal, allow_fix, auto_fix


def _is_deterministic_short_goal(text: str, *, allow_fix: bool = False) -> bool:
    """Short /run goals that should execute directly without the goal agent."""
    if allow_fix:
        return False
    return _normalize_goal_text(text) in DETERMINISTIC_SHORT_GOALS


def _expand_short_goal(goal: str) -> str:
    """Expand underspecified coding-TUI goals into actionable agent prompts."""
    normalized = " ".join((goal or "").lower().split()).strip()
    expansions = {
        "tests": "Run the project test suite (pytest) and report failures",
        "run tests": "Run the project test suite (pytest) and report failures",
        "test": "Run the project test suite (pytest) and report failures",
        "ci": "Run arka ci --changed and fix first failure",
        "lint": "Run ruff on changed Python files",
        "review": "Review staged code changes and summarize issues",
    }
    return expansions.get(normalized, (goal or "").strip())


def _is_strict_test_request(text: str) -> bool:
    """Recognize strict read-only test requests (/test or plain 'test')."""
    raw = (text or "").strip()
    if raw == "/test" or raw.startswith("/test "):
        return True
    normalized = _normalize_goal_text(text)
    if normalized == "run tests":
        return False
    return bool(
        re.fullmatch(
            r"(?:please\s+)?(?:run|execute|rerun)\s+(?:(?:the\s+)?(?:all\s+)?tests?(?:\s+(?:suite|for\s+arka|for\s+this\s+project))?|arka\s+tests)",
            normalized,
        )
        or normalized in {"test arka", "test arka features", "test the project", "tests", "test"}
    )


def _is_flexible_test_request(text: str) -> bool:
    """Recognize flexible test goals handled by the readonly goal agent."""
    normalized = _normalize_goal_text(text)
    if normalized == "run tests":
        return True
    return bool(
        re.fullmatch(r"(?:please\s+)?(?:run\s+)?tests?\s+(?:in|for)\s+.+", normalized)
        or normalized in {"run tests in this repo", "run tests in this repository", "test this repo"}
    )


def _is_flexible_run_test_goal(text: str) -> bool:
    """True for /run tests-style goals (including shorthand `/run tests` -> `tests`)."""
    return _normalize_goal_text(text) in FLEXIBLE_TEST_GOALS or _is_flexible_test_request(text)


def _parse_test_scope(text: str) -> str | None:
    """Return optional test path from `/test` input."""
    raw = (text or "").strip()
    if raw == "/test":
        return None
    if raw.startswith("/test "):
        scope = raw[6:].strip()
        return scope or None
    return None


def _parse_test_command(text: str) -> tuple[str | None, bool]:
    """Return (scope, auto_fix) from `/test` input."""
    raw = (text or "").strip()
    auto_fix = not bool(re.search(r"(?:^|\s)--no-fix(?:\s|$)", raw, re.I))
    cleaned = re.sub(r"(?:^|\s)--no-fix(?:\s|$)", " ", raw, flags=re.I).strip()
    return _parse_test_scope(cleaned), auto_fix


def _parse_pytest_failures(output: str, *, exit_code: int = 0) -> int:
    """Count pytest failures from combined stdout/stderr."""
    if exit_code == 0:
        return 0
    text = output or ""
    match = re.search(r"(\d+)\s+failed", text, re.I)
    if match:
        return int(match.group(1))
    failed_lines = len(re.findall(r"^FAILED\s+", text, re.M))
    if failed_lines:
        return failed_lines
    error_lines = len(re.findall(r"^ERROR\s+", text, re.M))
    if error_lines:
        return error_lines
    return 1


def _resolve_test_command(repo: Path, scope: str | None = None) -> list[str]:
    """Return argv for strict read-only test execution using repo-appropriate runner."""
    try:
        from arka.agent.repo_health import detect_checks

        test_checks = [check for check in detect_checks(repo) if check.category == "test"]
    except ImportError:
        test_checks = []

    if test_checks:
        command = list(test_checks[0].command)
        if len(command) >= 3 and command[0] == "python" and command[1] == "-m":
            command[0] = sys.executable
        if "pytest" in command and "--tb=line" not in command:
            command = [part for part in command if not part.startswith("--tb=")]
            command.append("--tb=line")
    else:
        command = [sys.executable, "-m", "pytest", "-q", "--tb=line"]

    if scope:
        scope = scope.strip()
        joined = " ".join(command).lower()
        if "pytest" in joined:
            command.append(scope)
        elif joined.startswith("cargo test"):
            command.append(scope)
        elif "npm" in joined and "test" in joined:
            if "--" not in command:
                command.extend(["--", scope])
            else:
                command.append(scope)
        else:
            command.append(scope)
    return command


def _auto_fix_once(
    repo: Path,
    failure_summary: str,
    code_agent,
    *,
    goal_context: str = "",
) -> int:
    """Run one writable goal-agent pass to repair test failures."""
    from arka.agent.git_changes import format_changed_files, list_changed_files

    print("○ Fix pass 1/1")
    before = {row.path for row in list_changed_files(repo)}
    fix_goal = (
        "Fix the failing tests reported above. Run pytest to verify. "
        "Only touch files needed for test failures."
    )
    if goal_context.strip():
        fix_goal = f"Original goal: {goal_context.strip()}\n\n{fix_goal}"
    if failure_summary.strip():
        fix_goal += f"\n\nFailure output:\n{failure_summary.strip()[-4000:]}"
    rc = code_agent(
        fix_goal,
        repo=str(repo),
        plan_context="",
        system_extra=coding_tui_system_extra(repo, "fix failing tests"),
        readonly=False,
    )
    after = {row.path for row in list_changed_files(repo)}
    if after != before:
        print(format_changed_files(repo, empty_message=""))
    if rc != 0:
        print(f"✗ Fix pass finished with exit code {rc}.")
    return rc


def _run_direct_tests(
    repo: Path,
    scope: str | None = None,
    *,
    auto_fix: bool = True,
    code_agent=None,
    run_label: str | None = "Test run (read-only)",
    after_fix_attempt: bool = False,
) -> int:
    """Run tests directly without the goal agent (strict read-only /test)."""
    command = _resolve_test_command(repo, scope)
    if run_label:
        print(f"○ {run_label}")
    print(f"Running tests: {' '.join(command)}")
    if scope:
        print(f"Test scope: {scope} (repo {repo})")
    else:
        print(f"Test scope: repository at {repo}")
    try:
        proc = subprocess.run(command, cwd=repo, check=False, capture_output=True, text=True)
    except OSError as exc:
        print(f"Could not start test runner: {exc}")
        return 1
    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.stdout:
        end = "" if proc.stdout.endswith("\n") else "\n"
        print(proc.stdout, end=end)
    if proc.stderr:
        end = "" if proc.stderr.endswith("\n") else "\n"
        print(proc.stderr, end=end, file=sys.stderr)

    failures = _parse_pytest_failures(output, exit_code=proc.returncode)
    if failures == 0:
        if after_fix_attempt:
            print("✓ Tests passed (read-only run, after fix)")
        else:
            print("✓ Tests passed (read-only run)")
        return 0

    if after_fix_attempt:
        print("✗ Still failing after one fix pass. Use /run tests --fix for another attempt.")
        return proc.returncode

    if not auto_fix or code_agent is None:
        print(f"✗ Tests failed ({failures} test failure(s)).")
        if not auto_fix:
            print("○ Auto-fix skipped (--no-fix).")
        else:
            print("For another fix attempt, use: /run tests --fix")
        return proc.returncode

    print(f"○ {failures} test failure(s) detected — attempting one fix pass…")
    _auto_fix_once(repo, output, code_agent)
    return _run_direct_tests(
        repo,
        scope=scope,
        auto_fix=False,
        code_agent=None,
        run_label="Test run (read-only, after fix)",
        after_fix_attempt=True,
    )


def _changed_python_files(repo: Path) -> list[str]:
    from arka.agent.git_changes import list_changed_files

    return [row.path for row in list_changed_files(repo) if row.path.endswith(".py")]


def _run_direct_ci(repo: Path) -> int:
    from arka.agent.dev_tools import ci_text, run_ci

    print(ci_text(repo, changed_only=True))
    ok = run_ci(repo, changed_only=True)["ok"]
    print("○ CI run complete (no files modified)")
    return 0 if ok else 1


def _run_direct_lint(repo: Path) -> int:
    changed = _changed_python_files(repo)
    if not changed:
        print("○ No changed Python files to lint.")
        print("○ Lint run complete (no files modified)")
        return 0
    command = [sys.executable, "-m", "ruff", "check", *changed]
    print(f"Running lint: {' '.join(command)}")
    try:
        proc = subprocess.run(command, cwd=repo, check=False)
    except OSError as exc:
        print(f"Could not start ruff: {exc}")
        return 1
    if proc.returncode == 0:
        print("✓ Lint passed.")
    else:
        print(f"✗ Lint failed (exit {proc.returncode}).")
    print("○ Lint run complete (no files modified)")
    print("For agent-assisted fixes, use: /run lint --fix")
    return proc.returncode


def _run_direct_review(repo: Path) -> int:
    from arka.agent.dev_tools import review_text

    print(review_text(repo, staged=True))
    print("○ Review complete (no files modified)")
    return 0


def _run_deterministic_goal(goal: str, repo: Path) -> int:
    """Run repository workflow goals directly without the goal agent."""
    normalized = _normalize_goal_text(goal)
    if normalized == "ci":
        return _run_direct_ci(repo)
    if normalized in {"lint", "ruff"}:
        return _run_direct_lint(repo)
    if normalized == "review":
        return _run_direct_review(repo)
    return 1


def _expand_flexible_test_goal(goal: str, *, allow_fix: bool) -> str:
    """Expand flexible /run tests goals for the readonly (or fix) goal agent."""
    normalized = _normalize_goal_text(goal)
    if normalized in FLEXIBLE_TEST_GOALS:
        base = (
            "Run tests for this repository. Choose an appropriate read-only strategy: "
            "full pytest suite, focused module tests, `arka ci --changed`, or a "
            "repo_health-detected runner. Report failures clearly."
        )
        if allow_fix:
            return base + " Fix justified failures and re-run the same tests to verify."
        return base + " Do not modify any files."
    scoped = (
        f"{goal}. Use the repository working directory already provided. "
        "Inspect the requested scope, choose an appropriate test command, run it, and report results."
    )
    if allow_fix:
        return scoped + " Make only justified fixes and verify with the same tests."
    return scoped + " Do not modify any files."


def _run_flexible_tests(
    goal: str,
    repo: Path,
    code_agent,
    *,
    allow_fix: bool = False,
    auto_fix: bool = True,
) -> int:
    """Let the coding agent pick and run an appropriate test strategy."""
    if allow_fix:
        test_goal = _expand_flexible_test_goal(goal, allow_fix=True)
        return _execute_goal(
            test_goal,
            repo,
            last_plan=None,
            code_agent=code_agent,
            readonly=False,
            original_goal=goal,
        )

    print("○ Test run (read-only)")
    test_goal = _expand_flexible_test_goal(goal, allow_fix=False)
    rc = _execute_goal(
        test_goal,
        repo,
        last_plan=None,
        code_agent=code_agent,
        readonly=True,
        original_goal=goal,
    )
    if rc == 0:
        return 0
    if not auto_fix:
        print("○ Auto-fix skipped (--no-fix).")
        return rc

    print("○ Test failure(s) detected — attempting one fix pass…")
    _auto_fix_once(
        repo,
        f"Readonly test agent run failed with exit code {rc}.",
        code_agent,
        goal_context=goal,
    )
    return _run_direct_tests(
        repo,
        scope=None,
        auto_fix=False,
        code_agent=None,
        run_label="Test run (read-only, after fix)",
        after_fix_attempt=True,
    )


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


def _repo_file_count(root: Path) -> int:
    return sum(1 for p in root.rglob("*") if p.is_file() and ".git" not in p.parts)


def _is_arka_repo(root: Path) -> bool:
    try:
        from arka.core.code_project import is_arka_repo

        return is_arka_repo(root)
    except ImportError:
        return False


def _goal_mentions_react(goal: str) -> bool:
    lowered = goal.lower()
    return any(
        token in lowered
        for token in (
            "react",
            "vite",
            "jsx",
            "tsx",
            "frontend",
            "next.js",
            "nextjs",
            "create-react-app",
        )
    )


def _goal_mentions_python(goal: str) -> bool:
    lowered = goal.lower()
    return any(token in lowered for token in ("python", "pytest", "django", "flask", "fastapi"))


def _goal_mentions_3d_space(goal: str) -> bool:
    from arka.agent.scaffold_3d import goal_mentions_3d_space

    return goal_mentions_3d_space(goal)


def _is_greenfield_repo(root: Path) -> bool:
    from arka.agent.scaffold_3d import is_greenfield_repo

    return is_greenfield_repo(root)


def _should_scaffold_3d(goal: str, root: Path) -> bool:
    from arka.agent.scaffold_3d import should_scaffold_3d

    return should_scaffold_3d(goal, root, is_arka_repo=_is_arka_repo(root))


def _format_created_files(repo: Path, paths: list[str]) -> str:
    from arka.agent.git_changes import ChangedFile, format_changed_files

    if not paths:
        return "○ No files changed."
    git_report = format_changed_files(repo, empty_message="")
    if git_report and git_report != "○ No changes.":
        return git_report
    rows = [ChangedFile(path=path, status="A") for path in sorted(paths)]
    return format_changed_files(repo, files=rows, title="Created files")


def _parse_scaffold_3d_command(line: str) -> tuple[str, bool]:
    """Return (goal label, run_dev) from `/scaffold 3d` input."""
    rest = line[13:].strip() if line.startswith("/scaffold 3d") else line.strip()
    run_dev = False
    if "--run" in rest:
        run_dev = True
        rest = " ".join(part for part in rest.split() if part != "--run").strip()
    return rest or "beautiful 3D space", run_dev


def _post_scaffold_hook(
    template: str,
    repo: Path,
    *,
    created: list[str],
    run_dev: bool = False,
    prompt_dev: bool = True,
) -> None:
    from arka.agent.post_scaffold import post_scaffold_hook

    post_scaffold_hook(
        template,
        repo,
        created=created,
        run_dev=run_dev,
        prompt_dev=prompt_dev,
        prompt_fn=_prompt_user,
    )


def _run_3d_scaffold(
    repo: Path,
    *,
    goal: str = "",
    run_dev: bool = False,
    prompt_dev: bool = True,
) -> int:
    from arka.agent.post_scaffold import SCAFFOLD_3D_TEMPLATE
    from arka.agent.scaffold_3d import has_meaningful_scaffold, write_scaffold

    ok, message = _ensure_code_project(repo)
    if not ok:
        print(message)
        print(f"Run: arka code init .  (cwd: {repo})")
        return 1
    if message:
        print(message)
    if not _is_greenfield_repo(repo) and has_meaningful_scaffold(repo):
        print("○ 3D scaffold already present — skipping overwrite.")
        print(_format_created_files(repo, ["src/App.jsx", "package.json"]))
        return 0
    label = goal.strip() or "beautiful 3D space"
    print(f"○ Scaffolding {label} (React + Vite + Three.js)…")
    created = write_scaffold(repo)
    if not created:
        print("✗ Scaffold failed — no files written.")
        return 1
    if not has_meaningful_scaffold(repo):
        print("✗ Scaffold incomplete — missing Three.js scene files.")
        return 1
    print("✓ 3D space scaffold created.")
    print(_format_created_files(repo, created))
    _post_scaffold_hook(
        SCAFFOLD_3D_TEMPLATE,
        repo,
        created=created,
        run_dev=run_dev,
        prompt_dev=prompt_dev,
    )
    return 0


def _ensure_code_project(repo: Path, *, auto_init: bool = True) -> tuple[bool, str]:
    """Return (ok, message). Auto-initializes the project root when allowed."""
    try:
        from arka.core.code_project import CodeProjectError, ensure_project

        _, created = ensure_project(repo, auto_init=auto_init)
        if created:
            return True, f"Code project initialized: {repo}"
        return True, ""
    except CodeProjectError as exc:
        return False, str(exc)


def _code_project_initialized(root: Path) -> bool:
    try:
        from arka.core.code_project import get_active_root, is_within_project

        active = get_active_root()
        return active is not None and is_within_project(root, root=active)
    except ImportError:
        return False


def status(root: Path) -> str:
    files = _repo_file_count(root)
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
    if code_project == "no":
        lines.insert(
            -1,
            f"Action required: run `arka code init .` in {root} before writing code.",
        )
    return "\n".join(lines)


def _format_plan_body(
    goal: str,
    root: Path,
    *,
    files: int,
    focus: str,
    relevant: list[str],
    proposals: list[tuple[str, str]],
    changed: int | None = None,
) -> str:
    from arka.agent.git_changes import format_plan_files

    if changed is None:
        changed = _dirty_count(root)
    filtered = [(path, why) for path, why in proposals if not path.startswith("tests/") or (root / path).exists()]
    if not filtered and proposals:
        filtered = proposals
    plan_files = format_plan_files(filtered, title="Proposed files")
    lines = [
        f"Plan for: {goal}",
        f"Repository: {root} ({files} files)",
        f"Focus: {focus}",
        "Relevant paths: " + (", ".join(relevant) if relevant else "project root"),
    ]
    if plan_files:
        lines.extend(["", plan_files])
    lines.extend(
        [
            f"Working tree: {changed} changed path(s)",
            "1. Inspect the listed paths and confirm the project stack matches the goal.",
            f"2. Identify the smallest end-to-end slice for {focus}.",
            "3. Implement the core behavior first, then wire entry points and styling.",
            "4. Add focused verification (tests, dev server, or manual checklist).",
            "5. Run the project test/build command and inspect the diff before follow-ups.",
            "Review this plan — approve with y to execute immediately.",
        ]
    )
    return "\n".join(lines)


def _greenfield_3d_plan(goal: str, root: Path, files: int) -> str:
    from arka.agent.scaffold_3d import scaffold_file_manifest

    proposals = scaffold_file_manifest()
    focus = "greenfield React + Three.js space scene with stars, orbit controls, and animated Earth/Moon"
    relevant = ["package.json", "src/App.jsx", "index.html"]
    return _format_plan_body(goal, root, files=files, focus=focus, relevant=relevant, proposals=proposals)


def _greenfield_react_plan(goal: str, root: Path, files: int) -> str:
    moon = "moon" in goal.lower()
    sim_name = "RocketSimulation"
    proposals = [
        ("package.json", "initialize npm project with React, Vite, and simulation dependencies"),
        ("vite.config.js", "configure Vite dev server and the React plugin"),
        ("index.html", "HTML shell that mounts the React app"),
        ("src/main.jsx", "create the React root and render App"),
        ("src/App.jsx", "app layout, controls, and simulation container"),
        (f"src/components/{sim_name}.jsx", "rocket physics, trajectory, and target visualization"),
        ("src/App.css", "layout and canvas styling for the simulation"),
        ("README.md", "setup steps, npm scripts, and how to run the simulation"),
    ]
    focus = "greenfield React rocket simulation" + (" to the Moon" if moon else "")
    relevant = ["package.json", "src/", "index.html"]
    return _format_plan_body(goal, root, files=files, focus=focus, relevant=relevant, proposals=proposals)


def _greenfield_generic_plan(goal: str, root: Path, files: int) -> str:
    stack = "Python" if _goal_mentions_python(goal) else "project"
    entry = "src/main.py" if _goal_mentions_python(goal) else "src/index.js"
    proposals = [
        ("README.md", "document setup, commands, and project purpose"),
        (entry, "minimal runnable entry point for the requested feature"),
        ("src/", "core modules that implement the goal"),
    ]
    if _goal_mentions_python(goal):
        proposals.append(("pyproject.toml", "declare dependencies and test runner"))
        proposals.append(("tests/test_app.py", "smoke test for the primary behavior"))
    focus = f"greenfield {stack} scaffold for the requested feature"
    return _format_plan_body(goal, root, files=files, focus=focus, relevant=["README.md", "src/"], proposals=proposals)


def _generic_repo_plan(goal: str, root: Path, files: int) -> str:
    lowered = goal.lower()
    relevant: list[str] = []
    for candidate in ("package.json", "pyproject.toml", "Cargo.toml", "src", "app", "lib", "tests"):
        path = root / candidate
        if path.exists():
            relevant.append(str(path.relative_to(root)) + ("/" if path.is_dir() else ""))
    focus = "implement the requested feature in this repository"
    if any(word in lowered for word in ("test", "ci", "quality")):
        focus = "tests and verification for the requested change"
    elif any(word in lowered for word in ("ui", "frontend", "react", "component")):
        focus = "frontend components and user-facing behavior"
    proposals: list[tuple[str, str]] = []
    if (root / "package.json").is_file():
        proposals.extend(
            [
                ("src/", "implement or extend components for the goal"),
                ("package.json", "add scripts or dependencies if needed"),
            ]
        )
    elif (root / "pyproject.toml").is_file():
        proposals.extend(
            [
                ("src/", "implement the core behavior"),
                ("tests/", "add regression coverage for the change"),
            ]
        )
    else:
        proposals.append(("README.md", "document the change and how to verify it"))
        proposals.append(("src/", "implement the requested behavior"))
    return _format_plan_body(
        goal,
        root,
        files=files,
        focus=focus,
        relevant=relevant or ["project root"],
        proposals=proposals,
    )


def _arka_repo_plan(goal: str, root: Path, files: int) -> str:
    lowered = goal.lower()
    relevant: list[str] = []
    for candidate in ("pyproject.toml", "package.json", "Cargo.toml", "src", "tests", "docs"):
        path = root / candidate
        if path.exists():
            relevant.append(str(path.relative_to(root)) + ("/" if path.is_dir() else ""))
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
    proposals = [
        (path, why)
        for path, why in proposals
        if (root / path).exists() or path.startswith("tests/") or path.startswith("docs/")
    ]
    return _format_plan_body(goal, root, files=files, focus=focus, relevant=relevant, proposals=proposals)


def plan_preview(goal: str, root: Path) -> str:
    """Inspect the repository and return a goal-specific local plan."""
    goal = goal.strip()
    files = _repo_file_count(root)
    if not _is_arka_repo(root):
        if files == 0 or (
            files < 5
            and not (root / "package.json").exists()
            and not (root / "pyproject.toml").exists()
        ):
            if _goal_mentions_3d_space(goal):
                return _greenfield_3d_plan(goal, root, files)
            if _goal_mentions_react(goal):
                return _greenfield_react_plan(goal, root, files)
            return _greenfield_generic_plan(goal, root, files)
        return _generic_repo_plan(goal, root, files)
    return _arka_repo_plan(goal, root, files)


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
        from arka.agent.git_changes import format_plan_files

        entries: list[tuple[str, str]] = []
        for item in files:
            if isinstance(item, dict):
                path = str(item.get("path") or item.get("file") or "").strip()
                reason = str(item.get("reason") or item.get("action") or "").strip()
                if path:
                    entries.append((path, reason))
            elif item:
                entries.append((str(item).strip(), ""))
        plan_files = format_plan_files(entries)
        if plan_files:
            lines.extend(["", plan_files])
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
    from arka.agent.git_changes import format_changed_files

    return format_changed_files(
        root,
        empty_message="○ No changes.",
        include_stat=True,
    )


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
    normalized = " ".join(lowered.split()).strip()
    tui_hint = ""
    if re.search(r"(?i)\b(?:coding[-_ ]?tui|code_tui|terminal ui|tui)\b", lowered):
        tui_hint = (
            "- For TUI/interface goals, prefer editing src/arka/agent/coding_tui.py first.\n"
        )
    short_goal_hint = ""
    if normalized in FLEXIBLE_TEST_GOALS or re.search(
        r"(?i)\b(?:run\s+)?tests?\s+(?:in|for)\s+",
        goal,
    ):
        short_goal_hint = (
            "- Flexible test goal: pick the best strategy (pytest, focused module, `arka ci --changed`, repo_health).\n"
            "- Stay read-only unless the user passed --fix (one auto-fix pass runs after readonly failures by default).\n"
            "- Do not invoke creative skills (compose_3d, generate_image, model_to_image).\n"
        )
    elif normalized == "ci":
        short_goal_hint = "- Short goal 'ci' means run `arka ci --changed` (read-only unless --fix).\n"
    elif normalized == "lint":
        short_goal_hint = "- Short goal 'lint' means run ruff on changed Python files (read-only unless --fix).\n"
    elif normalized == "review":
        short_goal_hint = "- Short goal 'review' means inspect staged changes (`arka review` or git diff).\n"
    edit_hint = ""
    if normalized not in DETERMINISTIC_SHORT_GOALS:
        if not _is_arka_repo(root):
            if _goal_mentions_3d_space(lowered):
                edit_hint = (
                    "- Greenfield 3D goal: scaffold React + Vite + Three.js files directly in this directory. "
                    "Do NOT run git init. Create package.json, index.html, src/App.jsx with @react-three/fiber, "
                    "Stars, OrbitControls, and a dark space theme. Verify with npm install && npm run dev."
                )
            elif _goal_mentions_react(lowered):
                edit_hint = (
                    "- Scaffold a React app (package.json, Vite, src/components/) in this directory; "
                    "verify with npm install && npm run dev."
                )
            else:
                edit_hint = (
                    "- Create files under the project root for the goal; "
                    "verify with the project's build or test command."
                )
        else:
            edit_hint = "- Make concrete file edits under src/ and tests/; verify with pytest on changed modules."
    return (
        f"Coding TUI context: working directory is already {root}. Never use cd.\n"
        "- Do not run git init, git pull, git commit, or other git commands unless the user explicitly asked for git.\n"
        "- Prefer read (status read) and file edits over shell navigation.\n"
        "- Prefer existing Arka tools (repo_health, lint_project, review, ci) over raw shell when applicable.\n"
        f"{tui_hint}"
        f"{short_goal_hint}"
        f"{edit_hint}"
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
    readonly: bool = False,
    original_goal: str | None = None,
) -> int:
    ok, message = _ensure_code_project(repo)
    if not ok:
        print(message)
        print(f"Run: arka code init .  (cwd: {repo})")
        return 1
    if message:
        print(message)
    original_goal = (original_goal or goal).strip()
    if not readonly and _should_scaffold_3d(original_goal, repo):
        return _run_3d_scaffold(repo, goal=original_goal)
    goal = _expand_short_goal(goal)
    goal, summary, changed = prepare_prompt(goal)
    if changed:
        print(f"Prompt improved: {summary}")
    rc = code_agent(
        goal,
        repo=str(repo),
        plan_context=last_plan or "",
        system_extra=coding_tui_system_extra(repo, original_goal),
        readonly=readonly,
    )
    from arka.agent.git_changes import format_changed_files
    from arka.agent.scaffold_3d import has_meaningful_scaffold

    changed_files = format_changed_files(repo, empty_message="○ No files changed.")
    needs_scaffold = _goal_mentions_3d_space(original_goal) and _is_greenfield_repo(repo)
    meaningful = has_meaningful_scaffold(repo) or changed_files != "○ No files changed."
    if readonly:
        if rc == 0:
            print("○ Verification run complete (no files modified)")
        else:
            print(f"✗ Run finished with exit code {rc}.")
        print(changed_files)
        return rc
    if rc == 0 and (not needs_scaffold or meaningful):
        print("✓ Done.")
        print(changed_files)
        print("Next: `arka ci --changed` to verify edited files.")
    elif rc == 0 and needs_scaffold and not meaningful:
        print("✗ Run finished without meaningful project files — only navigation or empty steps ran.")
        print(changed_files)
    elif rc == 2:
        print("○ Run finished: no commands executed.")
        print(changed_files)
    else:
        print(f"✗ Run finished with exit code {rc}.")
        print(changed_files)
        print("Inspect output, then try `arka ci --changed`.")
    if rc == 0 and needs_scaffold and not meaningful:
        return 1
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

    ok, message = _ensure_code_project(repo)
    if not ok:
        print(message)
        print(f"Run: arka code init .  (cwd: {repo})")
        return last_plan, pending_goal, plan_approved
    if message:
        print(message)

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

    previous_session = os.environ.get("ARKA_CODING_SESSION")
    os.environ["ARKA_CODING_SESSION"] = "1"

    def finish(code: int = 0) -> int:
        if previous_session is None:
            os.environ.pop("ARKA_CODING_SESSION", None)
        else:
            os.environ["ARKA_CODING_SESSION"] = previous_session
        return code

    ok, message = _ensure_code_project(repo)
    if not ok:
        print(message)
        print(f"Run: arka code init .  (cwd: {repo})")
        return finish(1)

    _setup_readline()
    print_welcome(repo)
    if message:
        print(message)
    history: list[str] = []
    last_plan: str | None = None
    pending_goal: str | None = None
    plan_approved = False
    while True:
        try:
            line = input(f"arka ({repo.name})> ").strip()
        except (EOFError, KeyboardInterrupt):
            print()
            return finish()
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
            return finish()
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
        elif line == "/test" or line.startswith("/test "):
            scope, auto_fix = _parse_test_command(line)
            _run_direct_tests(repo, scope=scope, auto_fix=auto_fix, code_agent=code_agent)
        elif line == "/scaffold 3d" or line.startswith("/scaffold 3d "):
            goal, run_dev = _parse_scaffold_3d_command(line)
            _run_3d_scaffold(repo, goal=goal, run_dev=run_dev)
        elif line == "/run" or line.startswith("/run "):
            requested_goal, allow_fix, auto_fix = _parse_run_request(line[4:].strip() or (pending_goal or ""))
            if requested_goal and _is_flexible_run_test_goal(requested_goal):
                if allow_fix:
                    print(f"Executing tests with --fix: {requested_goal}")
                _run_flexible_tests(
                    requested_goal,
                    repo,
                    code_agent,
                    allow_fix=allow_fix,
                    # Test execution is read-only by default. Fixes require
                    # the explicit --fix opt-in, so failures can be reported
                    # back without mutating the repository unexpectedly.
                    auto_fix=allow_fix and auto_fix,
                )
                continue
            if requested_goal and _is_deterministic_short_goal(requested_goal, allow_fix=allow_fix):
                _run_deterministic_goal(requested_goal, repo)
                continue
            if requested_goal and allow_fix and _normalize_goal_text(requested_goal) in DETERMINISTIC_SHORT_GOALS:
                print(f"Executing with --fix: {requested_goal}")
                _execute_goal(requested_goal, repo, last_plan=last_plan, code_agent=code_agent, readonly=False)
                continue
            if requested_goal and _is_strict_test_request(requested_goal):
                _run_direct_tests(repo, auto_fix=auto_fix, code_agent=code_agent)
                continue
            if last_plan and not plan_approved:
                print("Plan has not been approved. Run /plan <goal> and answer yes before /run.")
                continue
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
        elif _is_strict_test_request(line):
            _run_direct_tests(repo, auto_fix=True, code_agent=code_agent)
        elif _is_flexible_test_request(line):
            _run_flexible_tests(line, repo, code_agent, auto_fix=True)
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
    return finish()


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka coding-tui")
    parser.add_argument("path", nargs="?", default=".")
    return run(parser.parse_args(argv).path)


if __name__ == "__main__":
    raise SystemExit(main())
