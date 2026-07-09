#!/usr/bin/env python3
"""Agent heartbeat — last activity, routines, and memory health (OpenClaw always-on layer)."""

from __future__ import annotations

import argparse
import json
import os
import sys
import time
from pathlib import Path

try:
    from arka.paths import cache_dir, load_env_file

    load_env_file()
except ImportError:

    def cache_dir() -> Path:
        return Path.home() / ".cache" / "fish-agent"

    def load_env_file() -> None:
        pass


HEARTBEAT_FILE = cache_dir() / "heartbeat.json"


def _load() -> dict:
    try:
        if HEARTBEAT_FILE.is_file():
            data = json.loads(HEARTBEAT_FILE.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                return data
    except (OSError, json.JSONDecodeError):
        pass
    return {}


def _save(data: dict) -> None:
    HEARTBEAT_FILE.parent.mkdir(parents=True, exist_ok=True)
    HEARTBEAT_FILE.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _routine_count() -> int:
    path = cache_dir() / "routines.json"
    try:
        if path.is_file():
            rows = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(rows, list):
                return sum(1 for r in rows if r.get("enabled", True))
    except (OSError, json.JSONDecodeError):
        pass
    return 0


def _memory_stats() -> dict[str, int]:
    stats = {"json_entries": 0, "session_daily": 0, "longterm_lines": 0}
    mem = cache_dir() / "memory.json"
    try:
        if mem.is_file():
            rows = json.loads(mem.read_text(encoding="utf-8"))
            if isinstance(rows, list):
                stats["json_entries"] = len(rows)
    except (OSError, json.JSONDecodeError):
        pass
    try:
        from arka.core.session_memory import daily_dir, long_term_path

        if daily_dir().is_dir():
            stats["session_daily"] = len(list(daily_dir().glob("*.md")))
        lt = long_term_path()
        if lt.is_file():
            stats["longterm_lines"] = len(lt.read_text(encoding="utf-8").splitlines())
    except ImportError:
        pass
    return stats


def ping(activity: str, *, source: str = "arka") -> None:
    data = _load()
    now = time.time()
    data.update(
        {
            "ts": now,
            "when": time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now)),
            "last_activity": activity,
            "source": source,
            "agent": os.environ.get("AGENT_NAME", "arka"),
            "security": {
                "enabled": os.environ.get("SECURITY", "1") != "0",
                "llm": os.environ.get("SECURITY_LLM", "1") != "0",
                "actions": os.environ.get("SECURITY_ACTIONS", "1") != "0",
            },
            "routines_enabled": _routine_count(),
            "memory": _memory_stats(),
        }
    )
    _save(data)


def status(*, json_out: bool = False) -> int:
    data = _load()
    if not data:
        ping("status.check", source="heartbeat")
        data = _load()
    if json_out:
        print(json.dumps(data, indent=2))
        return 0
    print(f"Agent: {data.get('agent', 'arka')}")
    print(f"Last activity: {data.get('last_activity', '?')} ({data.get('when', '?')})")
    print(f"Source: {data.get('source', '?')}")
    sec = data.get("security") or {}
    print(
        f"Security: master={sec.get('enabled', True)} "
        f"llm={sec.get('llm', True)} actions={sec.get('actions', True)}"
    )
    print(f"Routines enabled: {data.get('routines_enabled', 0)}")
    mem = data.get("memory") or {}
    print(
        f"Memory: json={mem.get('json_entries', 0)} "
        f"session_daily={mem.get('session_daily', 0)} "
        f"longterm_lines={mem.get('longterm_lines', 0)}"
    )
    return 0


def main() -> int:
    load_env_file()
    parser = argparse.ArgumentParser(description="Arka agent heartbeat")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("ping")
    p.add_argument("activity", nargs="?", default="manual.ping")

    p = sub.add_parser("status")
    p.add_argument("--json", action="store_true")

    args = parser.parse_args()
    if args.cmd == "ping":
        ping(args.activity, source="cli")
        print(f"Heartbeat: {args.activity}")
        return 0
    if args.cmd == "status":
        return status(json_out=args.json)
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
