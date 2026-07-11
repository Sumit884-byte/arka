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
    from arka.skills import run_chat_ask, run_chat_calc, run_chat_weather, run_password

    apply_env()
    parts = _split_skill_line(skill_line)
    if not parts:
        return 1
    head = parts[0]
    rest = parts[1:]

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
        elif head in ("select_model", "model_select", "best_model", "model_advisor"):
            from arka.llm.model_advisor import main as model_advisor_main

            code = model_advisor_main(rest or None)
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
