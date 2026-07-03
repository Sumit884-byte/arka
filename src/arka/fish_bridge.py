"""Delegate to bundled config.fish on any platform where fish is installed."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
from dataclasses import dataclass

from arka.paths import arka_home, bundled_dir, config_dir, fish_config


@dataclass
class FishRoute:
    kind: str
    action: str
    why: str = ""


def _fish_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("INSTALL_HOME", str(arka_home()))
    env.setdefault("CONFIG_DIR", str(config_dir()))
    bundled = bundled_dir()
    if bundled.is_dir():
        env["INSTALL_HOME"] = str(bundled if (bundled / "config.fish").is_file() else arka_home())
    return env


def delegate_to_fish(argv: list[str]) -> int | None:
    """Run `arka <request>` via fish config.fish. Returns exit code, or None if unavailable."""
    cfg = fish_config()
    if cfg is None:
        return None

    fish = _find_fish()
    if not fish:
        return None

    request = " ".join(shlex.quote(a) for a in argv).strip()
    if not request:
        return None

    call = _agent_call_name()
    cfg_q = shlex.quote(str(cfg))
    inner = f"source {cfg_q}; {call} {request}"
    try:
        result = subprocess.run([fish, "-c", inner], check=False, env=_fish_env())
        return result.returncode
    except OSError:
        return None


def delegate_subcommand(sub: str, rest: list[str]) -> int | None:
    cfg = fish_config()
    if cfg is None:
        return None
    fish = _find_fish()
    if not fish:
        return None

    call = _agent_call_name()
    args = " ".join(shlex.quote(a) for a in rest)
    cfg_q = shlex.quote(str(cfg))
    inner = f"source {cfg_q}; {call} {sub} {args}".strip()
    try:
        result = subprocess.run([fish, "-c", inner], check=False, env=_fish_env())
        return result.returncode
    except OSError:
        return None


def delegate_fish_function(func: str, rest: list[str]) -> int | None:
    """Run a fish skill/function directly (e.g. goal), not via the arka NL router."""
    cfg = fish_config()
    if cfg is None:
        return None
    fish = _find_fish()
    if not fish:
        return None

    args = " ".join(shlex.quote(a) for a in rest)
    cfg_q = shlex.quote(str(cfg))
    inner = f"source {cfg_q}; {func} {args}".strip()
    try:
        result = subprocess.run([fish, "-c", inner], check=False, env=_fish_env())
        return result.returncode
    except OSError:
        return None


def _find_fish() -> str | None:
    import shutil

    return shutil.which("fish")


def _agent_call_name() -> str:
    import os

    return os.environ.get("AGENT_NAME", "arka").strip() or "arka"


def fish_route_preview(text: str) -> FishRoute | None:
    """Run agent_route via bundled config.fish (70+ skills). Returns None if fish/config missing."""
    cmd = text.strip()
    if not cmd:
        return None

    cfg = fish_config()
    fish = _find_fish()
    if cfg is None or not fish:
        return None

    cfg_q = shlex.quote(str(cfg))
    cmd_q = shlex.quote(cmd)
    inner = f"source {cfg_q}; agent_route {cmd_q}"
    try:
        proc = subprocess.run(
            [fish, "-c", inner],
            capture_output=True,
            text=True,
            timeout=90,
            env=_fish_env(),
        )
    except (OSError, subprocess.TimeoutExpired):
        return None

    kind = action = why = ""
    for line in proc.stdout.splitlines():
        line = re.sub(r"\x1b\[[0-9;]*m", "", line.strip())
        if line.startswith("Kind:"):
            kind = line.split(":", 1)[1].strip().lower()
        elif line.startswith("Action:"):
            action = line.split(":", 1)[1].strip()
        elif line.startswith("Why:"):
            why = line.split(":", 1)[1].strip()

    if not action:
        return None
    return FishRoute(kind=kind or "skill", action=action, why=why)
