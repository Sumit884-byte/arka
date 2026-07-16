from arka.agent.coding_tui import status


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
    assert "1. Read the listed modules" in text
    assert "/run <goal>" not in text
    assert "approve with y" in text


def test_plan_preview_tailors_devtool_focus(tmp_path):
    (tmp_path / "pyproject.toml").write_text("[project]\nname='demo'\n")
    (tmp_path / "src").mkdir()
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


def test_run_tests_is_direct_and_does_not_create_plan(monkeypatch, tmp_path, capsys):
    from arka.agent import coding_tui

    commands = iter(["run tests", "/quit"])
    calls = []
    monkeypatch.setattr("builtins.input", lambda _: next(commands))
    monkeypatch.setattr(coding_tui, "_run_direct_tests", lambda repo: calls.append(repo) or 0)
    monkeypatch.setattr(
        coding_tui,
        "_handle_plan",
        lambda *args, **kwargs: (_ for _ in ()).throw(
            AssertionError("test request must not enter planning")
        ),
    )
    assert coding_tui.run(str(tmp_path)) == 0
    assert calls == [tmp_path.resolve()]
    assert "Plan for:" not in capsys.readouterr().out


def test_arka_tests_request_uses_direct_test_path():
    from arka.agent.coding_tui import _is_direct_test_request

    assert _is_direct_test_request("run Arka tests")
    assert _is_direct_test_request("run tests for Arka")
    assert not _is_direct_test_request("run tests and fix failures")


def test_scoped_tests_request_is_agent_driven(monkeypatch, tmp_path):
    from arka.agent import coding_tui

    assert coding_tui._is_agent_test_request("run tests in tests/")
    assert coding_tui._is_agent_test_request("test this repo")
    assert not coding_tui._is_agent_test_request("run tests")
    calls = []
    monkeypatch.setattr(
        coding_tui,
        "_execute_goal",
        lambda goal, repo, last_plan, code_agent: calls.append((goal, repo, last_plan)) or 0,
    )
    assert coding_tui._run_agent_tests("run tests in tests/", tmp_path, object()) == 0
    assert calls and "diagnose failures" in calls[0][0]


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

    monkeypatch.setattr(
        coding_tui.subprocess,
        "run",
        lambda command, cwd, check: seen.append((command, cwd, check)) or Result(),
    )
    assert coding_tui._run_direct_tests(tmp_path) == 0
    output = capsys.readouterr().out
    assert "Running tests:" in output
    assert "Test scope:" in output
    assert seen[0][0] == [coding_tui.sys.executable, "-m", "pytest", "-q", "--tb=line"]


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


def test_coding_tui_system_extra_maps_short_tests_goal(tmp_path):
    from arka.agent.coding_tui import coding_tui_system_extra

    text = coding_tui_system_extra(tmp_path, "tests")
    assert "pytest" in text
    assert "compose_3d" in text


def test_run_tests_expands_and_proposes_pytest(monkeypatch, tmp_path, capsys):
    from arka.agent import coding_tui

    commands = iter(["/run tests", "/quit"])
    seen: list[tuple[list[str], Path]] = []

    class Result:
        returncode = 0

    def fake_subprocess_run(command, cwd, check=False):
        seen.append((command, cwd))
        return Result()

    monkeypatch.setattr("builtins.input", lambda _: next(commands))
    monkeypatch.setattr(coding_tui.subprocess, "run", fake_subprocess_run)
    monkeypatch.setattr(
        "arka.agent.core.code_agent",
        lambda *args, **kwargs: (_ for _ in ()).throw(AssertionError("/run tests must not use code_agent")),
    )
    assert coding_tui.run(str(tmp_path)) == 0
    output = capsys.readouterr().out
    assert seen
    assert seen[0][0] == [coding_tui.sys.executable, "-m", "pytest", "-q", "--tb=line"]
    assert "✓ Tests passed." in output
    assert "Running tests:" in output
    assert "no files modified" in output.lower()


def test_run_tests_short_goal_is_deterministic(monkeypatch, tmp_path):
    from arka.agent import coding_tui

    assert coding_tui._is_deterministic_short_goal("tests")
    assert coding_tui._is_deterministic_short_goal("run tests")
    assert coding_tui._is_deterministic_short_goal("ci")
    assert not coding_tui._is_deterministic_short_goal("run tests and fix failures")
    assert not coding_tui._is_deterministic_short_goal("tests", allow_fix=True)
    goal, allow_fix = coding_tui._parse_run_request("tests --fix")
    assert goal == "tests"
    assert allow_fix is True


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
