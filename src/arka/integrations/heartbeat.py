#!/usr/bin/env python3
"""Agent heartbeat — last activity, routines, and memory health (OpenClaw always-on layer)."""

from __future__ import annotations

import argparse
import json
import os
import re
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
_DEFAULT_HISTORY = 20


def _history_limit() -> int:
    try:
        return max(1, min(int(os.environ.get("HEARTBEAT_HISTORY", str(_DEFAULT_HISTORY))), 100))
    except ValueError:
        return _DEFAULT_HISTORY


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


def _append_history(data: dict, *, activity: str, source: str, ts: float, when: str) -> None:
    history = data.get("history")
    if not isinstance(history, list):
        history = []
    history.append(
        {
            "ts": ts,
            "when": when,
            "activity": activity,
            "source": source,
        }
    )
    data["history"] = history[-_history_limit() :]


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


def _channel_stats() -> dict[str, int]:
    stats = {"message_sessions": 0, "subagents_running": 0, "subagents_total": 0}
    try:
        from arka.integrations.message_sessions import list_sessions, sessions_root

        stats["message_sessions"] = len(list_sessions(limit=500))
        if not stats["message_sessions"] and sessions_root().is_dir():
            stats["message_sessions"] = len(list(sessions_root().glob("*.json")))
    except ImportError:
        pass
    try:
        from arka.integrations.subagent import list_agents, status_summary

        summary = status_summary()
        stats["subagents_running"] = int(summary.get("running") or 0)
        stats["subagents_total"] = int(summary.get("total") or 0)
        if not stats["subagents_total"]:
            stats["subagents_total"] = len(list_agents(limit=500))
    except ImportError:
        pass
    return stats


_hermes_stats = _channel_stats  # backward compat for JSON readers


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
    when = time.strftime("%Y-%m-%d %H:%M:%S", time.localtime(now))
    data.update(
        {
            "ts": now,
            "when": when,
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
            "channels": _channel_stats(),
            "hermes": _channel_stats(),
        }
    )
    _append_history(data, activity=activity, source=source, ts=now, when=when)
    _save(data)


def history(*, limit: int = 20) -> list[dict]:
    """Return recent heartbeat activity events (newest last)."""
    data = _load()
    rows = data.get("history")
    if not isinstance(rows, list):
        return []
    clean: list[dict] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        clean.append(
            {
                "ts": row.get("ts"),
                "when": row.get("when", ""),
                "activity": row.get("activity", ""),
                "source": row.get("source", ""),
            }
        )
    limit = max(1, min(int(limit or 20), 100))
    return clean[-limit:]


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
    channels = data.get("channels") or data.get("hermes") or {}
    print(
        f"Channels: sessions={channels.get('message_sessions', 0)} "
        f"subagents_running={channels.get('subagents_running', 0)} "
        f"subagents_total={channels.get('subagents_total', 0)}"
    )
    recent = history(limit=5)
    if recent:
        print(f"Recent activity ({len(recent)}):")
        for row in recent:
            print(f"  {row.get('when', '?')}  {row.get('activity', '?')}  ({row.get('source', '?')})")
    return 0


_TRIGGER_RE = re.compile(
    r"(?i)\b("
    r"agent\s+heartbeat|heartbeat\s+status|"
    r"(?:show|check|get)\s+(?:agent\s+)?heartbeat|"
    r"(?:recent|activity)\s+history|heartbeat\s+history|"
    r"last\s+activity|agent\s+health\s+check|"
    r"memory\s+stats|routines\s+enabled"
    r")\b"
)
_HISTORY_RE = re.compile(r"(?i)\b(?:history|recent\s+activit(?:y|ies))\b")
_PING_RE = re.compile(r"(?i)\bping\b")


def wants_heartbeat(text: str) -> bool:
    if re.search(r"(?i)\bheartbeat\s+ping\b", text or ""):
        return True
    return bool(_TRIGGER_RE.search(text or ""))


def route_command(text: str) -> str:
    if not wants_heartbeat(text):
        return ""
    clean = (text or "").strip()
    if _HISTORY_RE.search(clean):
        return "heartbeat history"
    if _PING_RE.search(clean):
        m = re.search(r"(?i)\bping\s+(.+)$", clean)
        if m:
            return f"heartbeat ping {m.group(1).strip()}"
        return "heartbeat ping"
    return "heartbeat status"


def main() -> int:
    load_env_file()
    parser = argparse.ArgumentParser(description="Arka agent heartbeat")
    sub = parser.add_subparsers(dest="cmd")

    p_route = sub.add_parser("route", help="Map NL to heartbeat command")
    p_route.add_argument("text", nargs="+")

    p = sub.add_parser("ping")
    p.add_argument("activity", nargs="?", default="manual.ping")

    p = sub.add_parser("status")
    p.add_argument("--json", action="store_true")

    p = sub.add_parser("history")
    p.add_argument("--limit", type=int, default=20)
    p.add_argument("--json", action="store_true")

    args = parser.parse_args()
    if args.cmd == "route":
        route = route_command(" ".join(args.text))
        if route:
            print(route)
            return 0
        return 1
    if args.cmd == "ping":
        ping(args.activity, source="cli")
        print(f"Heartbeat: {args.activity}")
        return 0
    if args.cmd == "status":
        return status(json_out=args.json)
    if args.cmd == "history":
        rows = history(limit=args.limit)
        if args.json:
            print(json.dumps(rows, indent=2))
            return 0
        if not rows:
            print("No heartbeat history yet.")
            return 0
        for row in rows:
            print(f"{row.get('when', '?')}  {row.get('activity', '?')}  ({row.get('source', '?')})")
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
