"""Delegate to bundled config.fish on any platform where fish is installed."""

from __future__ import annotations

import os
import re
import shlex
import subprocess
import sys
from dataclasses import dataclass

from arka.paths import arka_home, bundled_dir, config_dir, env_file, fish_config


@dataclass
class FishRoute:
    kind: str
    action: str
    why: str = ""


_route_preview_cache: dict[tuple[str, str], FishRoute | None] = {}
_route_preview_stamp: str | None = None


def _fish_config_stamp() -> str:
    cfg = fish_config()
    if cfg is None:
        return ""
    parts: list[str] = []
    try:
        parts.append(f"cfg:{cfg.stat().st_mtime_ns}")
    except OSError:
        return ""
    env = env_file()
    if env.is_file():
        try:
            parts.append(f"env:{env.stat().st_mtime_ns}")
        except OSError:
            pass
    return "|".join(parts)


def _clear_route_preview_cache_if_stale() -> None:
    global _route_preview_stamp
    stamp = _fish_config_stamp()
    if stamp != _route_preview_stamp:
        _route_preview_cache.clear()
        _route_preview_stamp = stamp


def _fish_env() -> dict[str, str]:
    env = os.environ.copy()
    env.setdefault("INSTALL_HOME", str(arka_home()))
    env.setdefault("CONFIG_DIR", str(config_dir()))
    bundled = bundled_dir()
    if bundled.is_dir():
        env["INSTALL_HOME"] = str(bundled if (bundled / "config.fish").is_file() else arka_home())
    return env


def _capture_stdio_enabled() -> bool:
    return os.environ.get("ARKA_CAPTURE_STDIO", "").lower() in ("1", "true", "yes", "on")


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
    env = _fish_env()
    capture = _capture_stdio_enabled()
    if capture:
        env["NO_COLOR"] = "1"
        env["CLICOLOR"] = "0"
        env["TERM"] = "dumb"
    try:
        if capture:
            result = subprocess.run(
                [fish, "-c", inner],
                check=False,
                env=env,
                capture_output=True,
                text=True,
            )
            if result.stdout:
                print(result.stdout, end="")
            if result.stderr:
                print(result.stderr, end="", file=sys.stderr)
            return result.returncode
        result = subprocess.run([fish, "-c", inner], check=False, env=env)
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

    _clear_route_preview_cache_if_stale()
    stamp = _route_preview_stamp or ""
    cache_key = (stamp, cmd.casefold())
    if stamp and cache_key in _route_preview_cache:
        return _route_preview_cache[cache_key]

    cfg = fish_config()
    fish = _find_fish()
    if cfg is None or not fish:
        return None

    cfg_q = shlex.quote(str(cfg))
    cmd_q = shlex.quote(cmd)
    inner = f"source {cfg_q}; agent_route {cmd_q}"
    try:
        env = _fish_env()
        # Preview is a deterministic symbolic check; AI fallback belongs to
        # the Python router after this call, not inside the fish probe.
        env["ROUTE_MODE"] = "symbolic"
        proc = subprocess.run(
            [fish, "-c", inner],
            capture_output=True,
            text=True,
            timeout=90,
            env=env,
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

    if not action or kind not in {"skill", ""} or action.lower() in {"connection error.", "connection error"}:
        try:
            from arka.routing.file_size import route_find_files_by_size
            from arka.routing.symbolic import route_offline_extras

            fallback = route_find_files_by_size(cmd) or route_offline_extras(cmd)
        except ImportError:
            fallback = None
        result = FishRoute(kind="skill", action=fallback) if fallback else None
        if stamp:
            _route_preview_cache[cache_key] = result
        return result
    result = FishRoute(kind=kind or "skill", action=action, why=why)
    if stamp:
        _route_preview_cache[cache_key] = result
    return result
