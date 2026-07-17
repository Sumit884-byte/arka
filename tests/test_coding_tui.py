from arka.agent.coding_tui import status


import pytest


@pytest.fixture(autouse=True)
def _isolated_code_project_config(tmp_path, monkeypatch):
    from arka.core import code_project

    config = tmp_path / "arka-config"
    config.mkdir()
    monkeypatch.setattr(code_project, "config_dir", lambda: config)
    code_project.clear_project()
    yield
    code_project.clear_project()


def test_coding_tui_route_command():
    from arka.agent.coding_tui import route_command

    assert route_command("coding-tui .") == "coding-tui ."
    assert route_command("coding-tui /tmp/repo") == "coding-tui /tmp/repo"
    assert route_command("open coding tui") == "coding-tui ."
    assert route_command("start coding workspace") == "coding-tui ."
    assert route_command("what is python") == ""


def test_coding_tui_status(tmp_path):
    (tmp_path / "app.py").write_text("print('ok')")
    text = status(tmp_path)
    assert "files: 1" in text
    assert "branch:" in text
    assert "dirty files:" in text
    assert "code project initialized:" in text
    assert "/plan" in text


def test_coding_tui_plan_is_visible(tmp_path):
    from arka.agent.coding_tui import plan_preview

    text = plan_preview("improve arka", tmp_path)
    assert "Plan for: improve arka" in text
    assert "1. Inspect the listed paths" in text
    assert "/run <goal>" not in text
    assert "approve with y" in text


def test_plan_preview_greenfield_react_goal(tmp_path):
    from arka.agent.coding_tui import plan_preview

    text = plan_preview("create a rocket simulation in react that goes to moon", tmp_path)
    assert "React" in text or "react" in text
    assert "RocketSimulation" in text
    assert "package.json" in text
    assert "test_dev_tools.py" not in text


def test_plan_preview_generic_repo_avoids_arka_paths(tmp_path):
    (tmp_path / "package.json").write_text('{"name":"demo"}\n')
    (tmp_path / "src").mkdir()
    from arka.agent.coding_tui import plan_preview

    text = plan_preview("add a settings page", tmp_path)
    assert "src/arka/" not in text
    assert "test_dev_tools.py" not in text
    assert "package.json" in text or "src/" in text


def test_plan_preview_tailors_devtool_focus(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
    (tmp_path / "llm.txt").write_text("PROJECT SUMMARY\n")
    (tmp_path / "src" / "arka").mkdir(parents=True)
    (tmp_path / "src").mkdir(exist_ok=True)
    (tmp_path / "tests").mkdir()
    from arka.agent.coding_tui import plan_preview

    text = plan_preview("improve NL routing as a devtool", tmp_path)
    assert "routing/dispatch code" in text
    assert "tests/test_nl_routing_coverage.py" in text
    assert "pyproject.toml" in text


def test_format_llm_plan_structured(tmp_path):
    from arka.agent.coding_tui import _format_llm_plan

    text = _format_llm_plan(
        "add settings page",
        tmp_path,
        {
            "summary": "Add a settings route and page component",
            "files": [{"path": "src/settings.tsx", "reason": "new page"}],
            "steps": ["Add route", "Add tests"],
        },
    )
    assert "Source: LLM plan-only" in text
    assert "Summary: Add a settings route" in text
    assert "━━━ Files to touch (1) ━━━" in text
    assert "1. src/settings.tsx — new page" in text
    assert "1. Add route" in text


def test_generate_plan_prefers_llm(monkeypatch, tmp_path):
    from arka.agent.coding_tui import generate_plan

    monkeypatch.setattr(
        "arka.agent.coding_tui.llm_plan",
        lambda goal, root: f"Plan for: {goal}\nSource: LLM plan-only (no execution)",
    )
    text, source = generate_plan("improve tests", tmp_path)
    assert source == "llm"
    assert "Source: LLM plan-only" in text


def test_generate_plan_falls_back_local(monkeypatch, tmp_path):
    from arka.agent.coding_tui import generate_plan

    monkeypatch.setattr("arka.agent.coding_tui.llm_plan", lambda goal, root: None)
    text, source = generate_plan("improve arka", tmp_path)
    assert source == "local"
    assert "Plan for: improve arka" in text


def test_coding_tui_prompt_is_optimized_when_enabled(monkeypatch):
    from arka.agent.coding_tui import prepare_prompt

    monkeypatch.setenv("ARKA_PROMPT_OPTIMIZE", "1")
    optimized, summary, changed = prepare_prompt("improve the login flow")
    assert changed is True
    assert "Preserve the user's stated intent" in optimized
    assert summary


def test_coding_tui_prompt_opt_out(monkeypatch):
    from arka.agent.coding_tui import prepare_prompt

    monkeypatch.setenv("ARKA_PROMPT_OPTIMIZE", "0")
    optimized, _, changed = prepare_prompt("improve the login flow")
    assert optimized == "improve the login flow"
    assert changed is False


def test_coding_agent_unwraps_skill_prefix(monkeypatch):
    from arka.agent import core

    calls = []

    def fake_run_skill(command):
        calls.append(command)
        return 0

    monkeypatch.setattr("arka.dispatch.run_skill", fake_run_skill)
    assert core._run_arka_tool_step("skill self_improve") == 0
    assert calls == ["self_improve"]


def test_coding_agent_skips_image_skill_without_input(capsys):
    from arka.agent.core import _run_arka_tool_step

    assert _run_arka_tool_step("skill design_from_screenshot") == 0
    assert "image path or URL is required" in capsys.readouterr().out


def test_coding_agent_rejects_unknown_skill_without_routing(monkeypatch, capsys):
    from arka.agent import core

    monkeypatch.setattr("arka.router.route", lambda _: (_ for _ in ()).throw(AssertionError("must not route")))
    assert core._run_arka_tool_step("skill scaffolding") == 1
    assert "unknown skill" in capsys.readouterr().out


def test_coding_agent_skips_planner_placeholder(capsys):
    from arka.agent.core import _run_arka_tool_step

    assert _run_arka_tool_step("shell command or skill") == 0
    assert capsys.readouterr().out == ""


def test_planner_placeholder_detection_is_silent_in_step_filter():
    from arka.agent.core import _is_planner_placeholder

    assert _is_planner_placeholder("shell command or skill: python -m arka repo_health")
    assert _is_planner_placeholder("shell command or skill")
    assert not _is_planner_placeholder("python -m pytest tests/test_app.py")


def test_code_plan_sanitizes_invalid_steps():
    from arka.agent.core import _sanitize_code_steps

    assert _sanitize_code_steps([
        "shell command or skill: python -m arka repo_health",
        "The image shows a directory listing",
        "python -m pytest tests/test_app.py",
    ]) == ["python -m pytest tests/test_app.py"]


def test_coding_agent_skips_placeholder_shell_and_incomplete_pr_check(capsys):
    from arka.agent.core import _run_arka_tool_step

    assert _run_arka_tool_step("shell command or skill: git checkout <branch-name>") == 0
    assert _run_arka_tool_step("pr_check") == 0
    output = capsys.readouterr().out
    assert "planner placeholder" not in output
    assert "choose an action" in output


def test_goal_rejects_prose_in_shell_action_slot():
    from arka.agent.goal import _looks_like_prose_action

    assert _looks_like_prose_action("Read the listed modules and project rules")
    assert _looks_like_prose_action("Search web for the answer")
    assert not _looks_like_prose_action("pytest tests/test_coding_tui.py -q")
    assert not _looks_like_prose_action("python -m pytest -q")


def test_coding_tui_auto_inits_code_project(monkeypatch, tmp_path, capsys):
    from arka.agent import coding_tui
    from arka.core import code_project

    config = tmp_path / "config"
    config.mkdir()
    monkeypatch.setattr(code_project, "config_dir", lambda: config)
    code_project.clear_project()

    commands = iter(["/status", "/quit"])
    monkeypatch.setattr("builtins.input", lambda _: next(commands))
    assert coding_tui.run(str(tmp_path)) == 0
    output = capsys.readouterr().out
    assert "Code project initialized:" in output
    assert "code project initialized: yes" in output
    assert code_project.get_active_root() == tmp_path.resolve()


def test_coding_tui_blocks_plan_without_code_project(monkeypatch, tmp_path, capsys):
    from arka.agent import coding_tui

    monkeypatch.setattr(
        coding_tui,
        "_ensure_code_project",
        lambda repo, auto_init=True: (False, f"No code project initialized. Run: arka code init .  (cwd: {repo})"),
    )
    commands = iter(["/plan add logging", "/quit"])
    monkeypatch.setattr("builtins.input", lambda _: next(commands))
    monkeypatch.setattr(
        "arka.agent.coding_tui.generate_plan",
        lambda goal, root: (_ for _ in ()).throw(AssertionError("must not plan")),
    )
    assert coding_tui.run(str(tmp_path)) == 1
    output = capsys.readouterr().out
    assert "No code project initialized" in output
    assert "Plan for:" not in output


def test_coding_tui_history_and_clear(monkeypatch, tmp_path, capsys):
    from arka.agent import coding_tui

    commands = iter(["/status", "/history", "/clear", "/history", "/quit"])
    monkeypatch.setattr("builtins.input", lambda _: next(commands))
    assert coding_tui.run(str(tmp_path)) == 0
    output = capsys.readouterr().out
    assert "history: 1 command(s)" in output
    assert "Session history and pending plan cleared." in output
    assert "Tip: /plan <goal>" in output
    assert output.rstrip().endswith("1  /history")


def test_coding_tui_approve_auto_executes(monkeypatch, tmp_path, capsys):
    from arka.agent import coding_tui

    commands = iter(["/plan improve tests", "yes", "/quit"])
    called = []
    monkeypatch.setattr("builtins.input", lambda _: next(commands))
    monkeypatch.setattr("arka.agent.coding_tui.generate_plan", lambda goal, root: (f"Plan for: {goal}", "local"))
    monkeypatch.setattr(
        "arka.agent.coding_tui.prepare_prompt",
        lambda prompt: (prompt, prompt, False),
    )
    monkeypatch.setattr(
        "arka.agent.core.code_agent",
        lambda goal, repo, plan_context, system_extra="", readonly=False: called.append(
            (goal, repo, plan_context, system_extra)
        )
        or 0,
    )
    assert coding_tui.run(str(tmp_path)) == 0
    output = capsys.readouterr().out
    assert "Plan approved — executing…" in output
    assert "✓ Done." in output
    assert "Next: `arka ci --changed`" in output
    assert len(called) == 1
    assert called[0][0] == "improve tests"
    assert "Plan for: improve tests" in called[0][2]


def test_coding_tui_decline_does_not_execute(monkeypatch, tmp_path, capsys):
    from arka.agent import coding_tui

    commands = iter(["/plan improve tests", "n", "/quit"])
    called = []
    monkeypatch.setattr("builtins.input", lambda _: next(commands))
    monkeypatch.setattr("arka.agent.coding_tui.generate_plan", lambda goal, root: (f"Plan for: {goal}", "local"))
    monkeypatch.setattr(
        "arka.agent.core.code_agent",
        lambda goal, repo, plan_context, system_extra="", readonly=False: called.append(goal) or 0,
    )
    assert coding_tui.run(str(tmp_path)) == 0
    output = capsys.readouterr().out
    assert "Plan not approved. Use /run when ready." in output
    assert called == []


def test_coding_tui_run_without_prior_plan(monkeypatch, tmp_path, capsys):
    from arka.agent import coding_tui

    commands = iter(["/run add logging", "/quit"])
    called = []
    monkeypatch.setattr("builtins.input", lambda _: next(commands))
    monkeypatch.setattr(
        "arka.agent.coding_tui.prepare_prompt",
        lambda prompt: (prompt, prompt, False),
    )
    monkeypatch.setattr(
        "arka.agent.core.code_agent",
        lambda goal, repo, plan_context, system_extra="", readonly=False: called.append(goal) or 0,
    )
    assert coding_tui.run(str(tmp_path)) == 0
    output = capsys.readouterr().out
    assert "✓ Done." in output
    assert "Next: `arka ci --changed`" in output
    assert called == ["add logging"]


def test_coding_tui_plain_text_triggers_plan(monkeypatch, tmp_path, capsys):
    from arka.agent import coding_tui

    commands = iter(["improve login flow", "n", "/quit"])
    monkeypatch.setattr("builtins.input", lambda _: next(commands))
    monkeypatch.setattr("arka.agent.coding_tui.generate_plan", lambda goal, root: (f"Plan for: {goal}", "llm"))
    assert coding_tui.run(str(tmp_path)) == 0
    output = capsys.readouterr().out
    assert "Plan for: improve login flow" in output
    assert "Plan not approved. Use /run when ready." in output


def test_coding_tui_ci_and_review(monkeypatch, tmp_path, capsys):
    from arka.agent import coding_tui

    commands = iter(["/ci", "/review", "/quit"])
    monkeypatch.setattr("builtins.input", lambda _: next(commands))
    monkeypatch.setattr("arka.agent.dev_tools.ci_text", lambda root, changed_only=False: "CI run: demo")
    monkeypatch.setattr("arka.agent.dev_tools.review_text", lambda root, staged=False: "Review scope: staged")
    assert coding_tui.run(str(tmp_path)) == 0
    output = capsys.readouterr().out
    assert "CI run: demo" in output
    assert "Review scope: staged" in output


def test_run_tests_is_flexible_and_uses_agent(monkeypatch, tmp_path, capsys):
    from arka.agent import coding_tui

    commands = iter(["run tests", "/quit"])
    calls = []
    monkeypatch.setattr("builtins.input", lambda _: next(commands))
    monkeypatch.setattr(
        coding_tui,
        "_run_flexible_tests",
        lambda goal, repo, code_agent, allow_fix=False, auto_fix=True: calls.append((goal, repo, allow_fix, auto_fix)) or 0,
    )
    monkeypatch.setattr(
        coding_tui,
        "_handle_plan",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("flexible test request must not enter planning")
        ),
    )
    assert coding_tui.run(str(tmp_path)) == 0
    assert calls == [("run tests", tmp_path.resolve(), False, True)]
    assert "Plan for:" not in capsys.readouterr().out


def test_strict_test_plain_text_runs_direct(monkeypatch, tmp_path, capsys):
    from arka.agent import coding_tui

    commands = iter(["test", "/quit"])
    calls = []
    monkeypatch.setattr("builtins.input", lambda _: next(commands))
    monkeypatch.setattr(
        coding_tui,
        "_run_direct_tests",
        lambda repo, scope=None, auto_fix=True, code_agent=None, **kwargs: calls.append((repo, scope, auto_fix)) or 0,
    )
    assert coding_tui.run(str(tmp_path)) == 0
    assert calls == [(tmp_path.resolve(), None, True)]


def test_arka_tests_request_uses_strict_test_path():
    from arka.agent.coding_tui import _is_strict_test_request

    assert _is_strict_test_request("run Arka tests")
    assert _is_strict_test_request("run tests for Arka")
    assert _is_strict_test_request("/test")
    assert _is_strict_test_request("/test tests/test_foo.py")
    assert _is_strict_test_request("test")
    assert not _is_strict_test_request("run tests")


def test_scoped_tests_request_is_flexible(monkeypatch, tmp_path):
    from arka.agent import coding_tui

    assert coding_tui._is_flexible_test_request("run tests in tests/")
    assert coding_tui._is_flexible_test_request("test this repo")
    assert coding_tui._is_flexible_test_request("run tests")
    assert not coding_tui._is_flexible_test_request("test")
    assert not coding_tui._is_flexible_test_request("tests")
    calls = []
    monkeypatch.setattr(
        coding_tui,
        "_run_flexible_tests",
        lambda goal, repo, code_agent, allow_fix=False, auto_fix=True: calls.append((goal, allow_fix, auto_fix)) or 0,
    )
    assert coding_tui._run_flexible_tests("run tests in tests/", tmp_path, object()) == 0
    assert calls and calls[0][0] == "run tests in tests/"
    assert calls[0][1] is False
    assert calls[0][2] is True


def test_browser_open_is_off_by_default_in_coding_session(monkeypatch, capsys):
    from arka import dispatch

    monkeypatch.setenv("ARKA_CODING_SESSION", "1")
    monkeypatch.delenv("ARKA_CODING_AUTO_BROWSER", raising=False)
    opened = []
    monkeypatch.setattr(dispatch, "run_script", lambda *args: opened.append(args) or 0)
    assert dispatch.run_skill("open_url https://arkatest.com") == 0
    assert opened == []
    assert "Browser opening disabled" in capsys.readouterr().out


def test_direct_tests_report_scope_and_verbose_command(monkeypatch, tmp_path, capsys):
    from arka.agent import coding_tui

    seen = []

    class Result:
        returncode = 0
        stdout = "12 passed in 1.2s\n"
        stderr = ""

    monkeypatch.setattr(
        coding_tui.subprocess,
        "run",
        lambda command, cwd, check, capture_output=True, text=True: seen.append((command, cwd, check)) or Result(),
    )
    assert coding_tui._run_direct_tests(tmp_path, auto_fix=False) == 0
    output = capsys.readouterr().out
    assert "Test run (read-only)" in output
    assert "Running tests:" in output
    assert "Test scope:" in output
    assert "Tests passed (read-only run)" in output
    assert seen[0][0][0] in {coding_tui.sys.executable, "pytest"}


def test_parse_pytest_failures():
    from arka.agent.coding_tui import _parse_pytest_failures

    assert _parse_pytest_failures("12 passed in 1.2s", exit_code=0) == 0
    assert _parse_pytest_failures("2 failed, 10 passed", exit_code=1) == 2
    assert _parse_pytest_failures("FAILED tests/test_x.py\nFAILED tests/test_y.py", exit_code=1) == 2
    assert _parse_pytest_failures("", exit_code=1) == 1


def test_direct_tests_auto_fix_on_failure(monkeypatch, tmp_path, capsys):
    from arka.agent import coding_tui

    calls: list[str] = []

    class FailResult:
        returncode = 1
        stdout = "1 failed, 11 passed\nFAILED tests/test_x.py\n"
        stderr = ""

    class PassResult:
        returncode = 0
        stdout = "12 passed in 1.2s\n"
        stderr = ""

    outcomes = iter([FailResult(), PassResult()])

    monkeypatch.setattr(
        coding_tui.subprocess,
        "run",
        lambda *args, **kwargs: next(outcomes),
    )
    monkeypatch.setattr(
        coding_tui,
        "_auto_fix_once",
        lambda repo, summary, agent, **kwargs: calls.append("fix") or 0,
    )
    fake_agent = object()
    assert coding_tui._run_direct_tests(tmp_path, auto_fix=True, code_agent=fake_agent) == 0
    output = capsys.readouterr().out
    assert calls == ["fix"]
    assert "1 test failure(s) detected — attempting one fix pass" in output
    assert "Tests passed (read-only run, after fix)" in output


def test_direct_tests_no_fix_on_pass(monkeypatch, tmp_path, capsys):
    from arka.agent import coding_tui

    fix_calls: list[str] = []

    class PassResult:
        returncode = 0
        stdout = "12 passed in 1.2s\n"
        stderr = ""

    monkeypatch.setattr(
        coding_tui.subprocess,
        "run",
        lambda *args, **kwargs: PassResult(),
    )
    monkeypatch.setattr(
        coding_tui,
        "_auto_fix_once",
        lambda *args, **kwargs: fix_calls.append("fix") or 0,
    )
    assert coding_tui._run_direct_tests(tmp_path, auto_fix=True, code_agent=object()) == 0
    assert fix_calls == []
    assert "Tests passed (read-only run)" in capsys.readouterr().out


def test_test_no_fix_flag_skips_auto_fix(monkeypatch, tmp_path, capsys):
    from arka.agent import coding_tui

    fix_calls: list[str] = []

    class FailResult:
        returncode = 1
        stdout = "1 failed, 11 passed\nFAILED tests/test_x.py\n"
        stderr = ""

    monkeypatch.setattr(
        coding_tui.subprocess,
        "run",
        lambda *args, **kwargs: FailResult(),
    )
    monkeypatch.setattr(
        coding_tui,
        "_auto_fix_once",
        lambda *args, **kwargs: fix_calls.append("fix") or 0,
    )
    scope, auto_fix = coding_tui._parse_test_command("/test --no-fix")
    assert scope is None
    assert auto_fix is False
    assert coding_tui._run_direct_tests(tmp_path, auto_fix=auto_fix, code_agent=object()) == 1
    assert fix_calls == []
    output = capsys.readouterr().out
    assert "Auto-fix skipped (--no-fix)" in output


def test_flexible_tests_auto_fix_on_failure(monkeypatch, tmp_path, capsys):
    from arka.agent import coding_tui

    fix_calls: list[str] = []
    direct_calls: list[bool] = []

    monkeypatch.setattr(
        coding_tui,
        "_execute_goal",
        lambda *args, **kwargs: 1,
    )
    monkeypatch.setattr(
        coding_tui,
        "_auto_fix_once",
        lambda *args, **kwargs: fix_calls.append("fix") or 0,
    )
    monkeypatch.setattr(
        coding_tui,
        "_run_direct_tests",
        lambda repo, **kwargs: direct_calls.append(kwargs.get("after_fix_attempt", False)) or 0,
    )
    assert coding_tui._run_flexible_tests("run tests", tmp_path, object(), auto_fix=True) == 0
    assert fix_calls == ["fix"]
    assert direct_calls == [True]
    output = capsys.readouterr().out
    assert "Test run (read-only)" in output
    assert "attempting one fix pass" in output


def test_coding_tui_diff_files_open(monkeypatch, tmp_path, capsys):
    from arka.agent import coding_tui

    (tmp_path / "src").mkdir()
    sample = tmp_path / "src" / "coding_tui.py"
    sample.write_text("print('hello')\nprint('world')\n")
    commands = iter(["/diff", "/files coding_tui", "/open src/coding_tui.py", "/quit"])
    monkeypatch.setattr("builtins.input", lambda _: next(commands))
    monkeypatch.setattr("arka.agent.coding_tui._git_diff_stat", lambda root: "━━━ Changed files (1) ━━━\n\n  M  src/coding_tui.py\n\n src/coding_tui.py | 2 ++")
    assert coding_tui.run(str(tmp_path)) == 0
    output = capsys.readouterr().out
    assert "━━━ Changed files (1) ━━━" in output
    assert "  M  src/coding_tui.py" in output
    assert "src/coding_tui.py | 2 ++" in output
    assert "src/coding_tui.py" in output
    assert "print('hello')" in output


def test_coding_tui_system_extra_targets_tui_file(tmp_path):
    from arka.agent.coding_tui import coding_tui_system_extra

    text = coding_tui_system_extra(tmp_path, "improve tui of arka")
    assert "coding_tui.py" in text
    assert "Never use cd" in text
    assert "git pull" in text


def test_expand_short_goal_tests():
    from arka.agent.coding_tui import _expand_short_goal

    assert _expand_short_goal("tests") == "Run the project test suite (pytest) and report failures"
    assert _expand_short_goal("run tests") == "Run the project test suite (pytest) and report failures"
    assert _expand_short_goal("ci") == "Run arka ci --changed and fix first failure"
    assert _expand_short_goal("lint") == "Run ruff on changed Python files"
    assert _expand_short_goal("add logging") == "add logging"


def test_coding_tui_system_extra_maps_flexible_tests_goal(tmp_path):
    from arka.agent.coding_tui import coding_tui_system_extra

    text = coding_tui_system_extra(tmp_path, "run tests")
    assert "Flexible test goal" in text
    assert "repo_health" in text
    assert "compose_3d" in text


def test_run_tests_uses_flexible_readonly_agent(monkeypatch, tmp_path, capsys):
    from arka.agent import coding_tui

    commands = iter(["/run tests", "/quit"])
    calls: list[tuple] = []

    monkeypatch.setattr("builtins.input", lambda _: next(commands))
    monkeypatch.setattr(
        coding_tui,
        "_run_flexible_tests",
        lambda goal, repo, code_agent, allow_fix=False, auto_fix=True: calls.append((goal, allow_fix, auto_fix)) or 0,
    )
    monkeypatch.setattr(
        coding_tui.subprocess,
        "run",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("/run tests must not subprocess")),
    )
    monkeypatch.setattr(
        "arka.agent.core.code_agent",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must use _run_flexible_tests")),
    )
    assert coding_tui.run(str(tmp_path)) == 0
    assert calls == [("tests", False, False)]


def test_test_command_strict_with_scope(monkeypatch, tmp_path, capsys):
    from arka.agent import coding_tui

    commands = iter(["/test tests/test_foo.py", "/quit"])
    calls = []
    monkeypatch.setattr("builtins.input", lambda _: next(commands))
    monkeypatch.setattr(
        coding_tui,
        "_run_direct_tests",
        lambda repo, scope=None, auto_fix=True, code_agent=None, **kwargs: calls.append((repo, scope, auto_fix)) or 0,
    )
    assert coding_tui.run(str(tmp_path)) == 0
    assert calls == [(tmp_path.resolve(), "tests/test_foo.py", True)]


def test_resolve_test_command_uses_repo_detection(monkeypatch, tmp_path):
    from arka.agent.coding_tui import _resolve_test_command
    from arka.agent.repo_health import Check

    monkeypatch.setattr(
        "arka.agent.repo_health.detect_checks",
        lambda root: [Check("pytest", ["pytest", "-q"], "test")],
    )
    command = _resolve_test_command(tmp_path, "tests/test_x.py")
    assert command == ["pytest", "-q", "--tb=line", "tests/test_x.py"]


def test_run_tests_short_goal_is_not_deterministic(monkeypatch, tmp_path):
    from arka.agent import coding_tui

    assert not coding_tui._is_deterministic_short_goal("tests")
    assert not coding_tui._is_deterministic_short_goal("run tests")
    assert coding_tui._is_flexible_test_request("run tests")
    assert coding_tui._is_deterministic_short_goal("ci")
    assert not coding_tui._is_deterministic_short_goal("run tests and fix failures")
    assert not coding_tui._is_deterministic_short_goal("tests", allow_fix=True)
    goal, allow_fix, auto_fix = coding_tui._parse_run_request("tests --fix")
    assert goal == "tests"
    assert allow_fix is True
    assert auto_fix is True
    goal, allow_fix, auto_fix = coding_tui._parse_run_request("tests --no-fix")
    assert goal == "tests"
    assert allow_fix is False
    assert auto_fix is False


def test_run_ci_and_lint_are_deterministic(monkeypatch, tmp_path):
    from arka.agent import coding_tui

    calls: list[str] = []
    monkeypatch.setattr(
        coding_tui,
        "_run_deterministic_goal",
        lambda goal, repo: calls.append(goal) or 0,
    )
    monkeypatch.setattr(
        "arka.agent.core.code_agent",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not use code_agent")),
    )
    commands = iter(["/run ci", "/run lint", "/run review", "/quit"])
    monkeypatch.setattr("builtins.input", lambda _: next(commands))
    assert coding_tui.run(str(tmp_path)) == 0
    assert calls == ["ci", "lint", "review"]


def test_plan_preview_greenfield_3d_goal(tmp_path):
    from arka.agent.coding_tui import plan_preview

    text = plan_preview("create a beautiful 3d space", tmp_path)
    assert "Three.js" in text or "Three" in text
    assert "src/App.jsx" in text
    assert "OrbitControls" in text or "orbit controls" in text.lower()
    assert "RocketSimulation" not in text


def test_scaffold_3d_writes_project_files(tmp_path):
    from arka.agent.scaffold_3d import has_meaningful_scaffold, write_scaffold

    created = write_scaffold(tmp_path)
    assert "package.json" in created
    assert "src/App.jsx" in created
    assert has_meaningful_scaffold(tmp_path)
    app = (tmp_path / "src/App.jsx").read_text(encoding="utf-8")
    assert "@react-three/fiber" in app
    assert "Stars" in app
    assert "OrbitControls" in app


def test_execute_goal_uses_deterministic_3d_scaffold(monkeypatch, tmp_path, capsys):
    from arka.agent import coding_tui

    monkeypatch.setattr("arka.agent.coding_tui._post_scaffold_hook", lambda *args, **kwargs: None)
    monkeypatch.setattr(
        "arka.agent.core.code_agent",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not use code_agent")),
    )
    rc = coding_tui._execute_goal(
        "create a beautiful 3d space",
        tmp_path,
        last_plan="Plan for: create a beautiful 3d space",
        code_agent=lambda *args, **kwargs: 0,
    )
    output = capsys.readouterr().out
    assert rc == 0
    assert "3D space scaffold created" in output
    assert (tmp_path / "package.json").is_file()
    assert (tmp_path / "src/App.jsx").is_file()


def test_coding_tui_scaffold_command(monkeypatch, tmp_path, capsys):
    from arka.agent import coding_tui

    monkeypatch.setattr("arka.agent.coding_tui._post_scaffold_hook", lambda *args, **kwargs: None)
    commands = iter(["/scaffold 3d", "/quit"])
    monkeypatch.setattr("builtins.input", lambda _: next(commands))
    assert coding_tui.run(str(tmp_path)) == 0
    output = capsys.readouterr().out
    assert "3D space scaffold created" in output
    assert (tmp_path / "src/App.jsx").is_file()


def test_coding_tui_approve_3d_plan_scaffolds_without_agent(monkeypatch, tmp_path, capsys):
    from arka.agent import coding_tui

    monkeypatch.setattr("arka.agent.coding_tui._post_scaffold_hook", lambda *args, **kwargs: None)
    commands = iter(["create a beautiful 3d space", "y", "/quit"])
    monkeypatch.setattr("builtins.input", lambda _: next(commands))
    monkeypatch.setattr(
        "arka.agent.coding_tui.generate_plan",
        lambda goal, root: (coding_tui.plan_preview(goal, root), "local"),
    )
    monkeypatch.setattr(
        "arka.agent.core.code_agent",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("must not use code_agent")),
    )
    assert coding_tui.run(str(tmp_path)) == 0
    output = capsys.readouterr().out
    assert "Plan approved — executing…" in output
    assert "3D space scaffold created" in output
    assert (tmp_path / "src/App.jsx").is_file()
