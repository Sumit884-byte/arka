"""Run arka_*.py scripts with correct paths."""

from __future__ import annotations

import os
import subprocess
import sys

from arka.paths import arka_home, bundled_dir, cache_dir, config_dir, python_executable, script_path


def apply_env() -> None:
    bundled = bundled_dir()
    home = bundled if (bundled / "config.fish").is_file() else arka_home()
    os.environ["INSTALL_HOME"] = str(home)
    os.environ.setdefault("CONFIG_DIR", str(config_dir()))
    os.environ.setdefault("CACHE_DIR", str(cache_dir()))


def run_script(script: str, args: list[str] | None = None) -> int:
    apply_env()
    path = script_path(script)
    if not path.is_file():
        print(f"Missing script: {path}", file=sys.stderr)
        print("Reinstall arka-agent or run: python scripts/sync_bundled.py", file=sys.stderr)
        return 1
    cmd = [python_executable(), str(path), *(args or [])]
    return subprocess.call(cmd)


def run_skill(skill_line: str) -> int:
    """Execute a skill command line like 'generate_password set wifi secret'."""
    from arka.core.mode import get_mode, mode_allows_execution
    from arka.skills import run_chat_ask, run_chat_calc, run_chat_weather, run_password

    apply_env()
    parts = _split_skill_line(skill_line)
    if not parts:
        return 1
    head = parts[0]
    rest = parts[1:]

    if head == "mode":
        from arka.core.mode import cmd_show, main as mode_main

        if not rest:
            return cmd_show()
        return mode_main(["mode", *rest])

    allowed, reason = mode_allows_execution(skill_line)
    if not allowed:
        if get_mode() == "plan":
            from arka.core.mode import print_plan
            from arka.router import route

            print_plan(skill_line, route(skill_line))
            return 0
        print(reason, file=sys.stderr)
        return 1

    head = parts[0]
    try:
        from arka.core.code_project import (
            CODE_WRITE_SKILLS,
            apply_env as apply_code_env,
            gate_code_write,
            gate_write_script_args,
        )

        code_ok, code_reason = gate_code_write(skill_line)
        if not code_ok:
            print(code_reason, file=sys.stderr)
            return 1
        if head == "write_script":
            ws_ok, ws_reason = gate_write_script_args(rest)
            if not ws_ok:
                print(ws_reason, file=sys.stderr)
                return 1
        if head in CODE_WRITE_SKILLS:
            apply_code_env()
    except ImportError:
        pass

    try:
        from arka.telemetry import mark_error, mark_ok, span
    except ImportError:
        span = None  # type: ignore[assignment,misc]
    from contextlib import nullcontext

    skill_ctx = (
        span(
            f"arka.skill.{head}",
            attributes={"arka.skill.name": head, "arka.skill.line": skill_line[:500]},
        )
        if span is not None
        else nullcontext()
    )
    with skill_ctx as current:
        if head in ("generate_password", "password", "pass"):
            code = run_password(rest)
        elif head == "platform_howto":
            from arka.agent.platform_howto import answer_platform_howto

            answer = answer_platform_howto(" ".join(rest))
            if answer:
                print(answer)
                code = 0
            else:
                print("Could not get an answer (check LLM API keys)", file=sys.stderr)
                code = 1
        elif head in ("interesting_fact", "trivia", "fun_fact"):
            from arka.agent.interesting_fact import answer_interesting_fact

            answer = answer_interesting_fact(" ".join(rest))
            if answer:
                print(answer)
                code = 0
            else:
                print("Could not get a fact (check LLM API keys)", file=sys.stderr)
                code = 1
        elif head == "web_answer":
            code = run_chat_ask(" ".join(rest))
        elif head == "deep_web_answer":
            code = run_chat_ask(" ".join(rest), deep=True)
        elif head == "calc":
            code = run_chat_calc(" ".join(rest))
        elif head in ("hyperlocal_weather", "weather"):
            code = run_chat_weather(" ".join(rest))
        elif head == "price_check":
            from arka.agent.core import price_check

            price_check(" ".join(rest))
            code = 0
        elif head in ("fact_check", "fact-check", "factcheck", "factchecker"):
            from arka.agent.fact_check import fact_check

            code = fact_check(" ".join(rest))
        elif head in ("quiz_practice", "quiz-practice", "quiz"):
            code = run_script("arka_quiz_practice.py", rest)
        elif head == "council":
            code = run_script("arka_council.py", rest)
        elif head == "convert":
            from arka.routing.symbolic import is_timezone_convert_request

            text = " ".join(rest).strip()
            if text and is_timezone_convert_request(text):
                code = run_script("arka_timezone_convert.py", ["convert", *rest])
            else:
                code = run_script("arka_currency.py", ["convert", *rest])
        elif head in ("currency_convert", "currency"):
            code = run_script("arka_currency.py", ["convert", *rest])
        elif head in ("timezone_convert", "tz_convert", "timezone"):
            code = run_script("arka_timezone_convert.py", ["convert", *rest])
        elif head in ("open_url", "open", "browse"):
            code = run_script("arka_open_url.py", rest)
        elif head in ("select_model", "model_select", "best_model", "model_advisor"):
            from arka.llm.model_advisor import main as model_advisor_main

            code = model_advisor_main(rest or None)
        elif head in ("free_credits", "free-credits", "max_credits", "ai_credits"):
            from arka.agent.free_credits import run_guide

            code = run_guide()
        elif head == "provider":
            from arka.llm.provider_select import main as provider_main

            code = provider_main(rest or None)
        elif head == "personalize":
            from arka.core.personalize import main as personalize_main

            code = personalize_main(rest)
        elif head == "persona":
            from arka.agent.personas.cli import main as persona_main

            code = persona_main(rest)
        elif head in ("elon", "talk_to_elon", "elon_chat", "talk_elon"):
            from arka.agent.personas.elon import main as elon_main

            code = elon_main(rest)
        elif head == "google":
            code = run_script("arka_google.py", rest)
        elif head == "code":
            from arka.core.code_project import main as code_main

            code = code_main(["code", *rest])
        elif head == "agent_code":
            from arka.agent.core import code_agent

            code = code_agent(" ".join(rest))
        elif head in ("self_improve", "self"):
            from arka.agent.self_improve import main as self_main, resolve_improve_args, run_self_improve

            argv = list(rest)
            if head == "self" and argv and argv[0] == "improve":
                argv = argv[1:]
            if len(argv) == 1 and argv[0] in ("memory", "status"):
                code = self_main([argv[0]])
            else:
                target, apply, max_rounds, max_steps, yes, auto_init = resolve_improve_args(argv)
                code = run_self_improve(
                    target,
                    max_rounds=max_rounds,
                    max_steps=max_steps,
                    auto_init=auto_init,
                    yes=yes,
                    apply=apply,
                )
        elif head in ("ci", "review", "route_audit", "route-audit", "skill"):
            from arka.agent.dev_tools import main as dev_tools_main

            sub_argv = [head, *rest]
            if head == "route-audit":
                sub_argv[0] = "route-audit"
            code = dev_tools_main(sub_argv)
        elif head in ("design_from_screenshot", "design-screenshot", "designshot"):
            from arka.agent.design_from_screenshot import main as design_main

            code = design_main([head.replace("-", "_"), *rest])
        elif head in ("urlkit", "url-kit"):
            from arka.core.urlkit import main as urlkit_main

            code = urlkit_main(rest)
        elif head in ("lint_project", "lint-project", "lint_all"):
            from arka.agent.lint_project import main as lint_main

            code = lint_main([head.replace("-", "_"), *rest])
        elif head.endswith(".py") and script_path(head).is_file():
            code = run_script(head, rest)
        else:
            py_name = f"{head}.py"
            if script_path(py_name).is_file():
                code = run_script(py_name, rest)
            else:
                code = run_fish_skill(skill_line)

        if span is not None:
            current.set_attribute("arka.skill.exit_code", code)
            if code == 0:
                mark_ok(current)
            else:
                mark_error(current, f"exit {code}")
        return code


def run_fish_skill(skill_line: str) -> int:
    from arka.fish_bridge import delegate_to_fish

    code = delegate_to_fish([skill_line])
    if code is not None:
        return code
    print(f"Unknown skill: {skill_line}", file=sys.stderr)
    print("Try: arka help  |  arka doctor  |  install fish for full 70+ skills", file=sys.stderr)
    return 1


def run_shell(cmd: str) -> int:
    apply_env()
    return subprocess.call(cmd, shell=True)


def _split_skill_line(line: str) -> list[str]:
    import shlex

    line = line.strip()
    if not line:
        return []
    try:
        return shlex.split(line)
    except ValueError:
        return line.split()
