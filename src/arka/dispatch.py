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

    if head in ("generate_password", "password", "pass"):
        return run_password(rest)

    if head == "web_answer":
        return run_chat_ask(" ".join(rest))

    if head == "deep_web_answer":
        return run_chat_ask(" ".join(rest), deep=True)

    if head == "calc":
        return run_chat_calc(" ".join(rest))

    if head in ("hyperlocal_weather", "weather"):
        return run_chat_weather(" ".join(rest))

    if head.endswith(".py") and script_path(head).is_file():
        return run_script(head, rest)

    py_name = f"{head}.py"
    if script_path(py_name).is_file():
        return run_script(py_name, rest)

    return run_fish_skill(skill_line)


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
