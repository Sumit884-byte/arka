"""Delegate to full Fish-based Arka when available (Linux/mac)."""

from __future__ import annotations

import os
import shlex
import subprocess

from arka.paths import arka_home, bundled_dir, config_dir, fish_config


def _fish_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("ARKA_HOME", str(arka_home()))
    env.setdefault("ARKA_CONFIG_DIR", str(config_dir()))
    bundled = bundled_dir()
    if bundled.is_dir():
        env["ARKA_HOME"] = str(bundled if (bundled / "arka_chat.py").is_file() else arka_home())
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


def _find_fish() -> str | None:
    import shutil

    return shutil.which("fish")


def _agent_call_name() -> str:
    import os

    return os.environ.get("AGENT_NAME", "arka").strip() or "arka"
