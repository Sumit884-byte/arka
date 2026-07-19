"""Unified read-only view of Arka-owned background activity."""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
from typing import Any


def _pid_alive(pid: str | int | None) -> bool:
    try:
        value = int(str(pid or "").strip())
    except ValueError:
        return False
    if value <= 0:
        return False
    try:
        os.kill(value, 0)
        return True
    except OSError:
        return False


def _arka_processes() -> list[dict[str, Any]]:
    """Return live OS processes that look Arka-owned."""
    try:
        proc = subprocess.run(
            ["ps", "-axo", "pid=,command="],
            capture_output=True,
            text=True,
            check=False,
            timeout=5,
        )
    except (OSError, subprocess.TimeoutExpired):
        return []
    rows: list[dict[str, Any]] = []
    current = os.getpid()
    patterns = (
        "arka mcp serve",
        "python -m arka mcp serve",
        "arka.agent.remote_server",
        "arka.integrations.remote_server",
        "arka.integrations.webhook",
        "arka_webhook",
        "arka_routines",
        "routines run",
    )
    for line in (proc.stdout or "").splitlines():
        text = line.strip()
        if not text:
            continue
        pid_text, _, command = text.partition(" ")
        try:
            pid = int(pid_text)
        except ValueError:
            continue
        if pid == current:
            continue
        normalized = " ".join(command.split()).lower()
        if any(pattern in normalized for pattern in patterns):
            kind = (
                "server"
                if "serve" in normalized or "webhook" in normalized or "remote_server" in normalized
                else "routine"
            )
            rows.append({"pid": pid, "kind": kind, "command": command[:240]})
    return rows


def collect_status() -> dict[str, Any]:
    """Collect Arka background state from persisted records and live processes."""
    subagents: dict[str, Any] = {"summary": {}, "active": []}
    try:
        from arka.integrations.subagent import list_agents, status_summary

        rows = list_agents(limit=200)
        subagents = {
            "summary": status_summary(),
            "active": [row for row in rows if row.get("status") in {"pending", "running"}],
        }
    except Exception as exc:
        subagents = {"error": str(exc), "summary": {}, "active": []}

    routines: dict[str, Any] = {"enabled": [], "all": []}
    try:
        from arka.integrations.routines import list_routines

        all_rows = list_routines(enabled_only=False)
        routines = {
            "enabled": [row for row in all_rows if row.get("enabled", True)],
            "all": all_rows,
        }
    except Exception as exc:
        routines = {"error": str(exc), "enabled": [], "all": []}

    webhook: dict[str, Any] = {}
    try:
        from arka.integrations.webhook import status_info

        webhook = status_info()
        webhook["pid_alive"] = _pid_alive(webhook.get("pid"))
    except Exception as exc:
        webhook = {"error": str(exc)}

    mcp: dict[str, Any] = {"configured": [], "active_processes": []}
    try:
        from arka.integrations.mcp_manager import list_server_names, mcp_config_path

        mcp = {
            "config": str(mcp_config_path()),
            "configured": list_server_names(),
            "active_processes": [],
        }
    except Exception as exc:
        mcp = {"error": str(exc), "configured": [], "active_processes": []}

    processes = _arka_processes()
    mcp["active_processes"] = [row for row in processes if "mcp serve" in str(row.get("command", "")).lower()]
    servers = {
        "webhook": webhook,
        "mcp": mcp,
        "processes": processes,
    }
    webhook_pid = str(webhook.get("pid") or "")
    webhook_seen = any(str(row.get("pid")) == webhook_pid for row in processes)
    active_count = (
        len(subagents.get("active", []))
        + len(routines.get("enabled", []))
        + len([row for row in processes if row.get("kind") == "server"])
        + (1 if webhook.get("pid_alive") and not webhook_seen else 0)
    )
    return {
        "active_count": active_count,
        "subagents": subagents,
        "routines": routines,
        "servers": servers,
    }


def format_status(data: dict[str, Any]) -> str:
    lines = ["Arka background processes", f"active_items\t{data.get('active_count', 0)}"]
    subagents = data.get("subagents", {})
    active_agents = subagents.get("active") or []
    summary = subagents.get("summary") or {}
    lines.append(
        f"subagents\tactive={len(active_agents)} running={summary.get('running', 0)} total={summary.get('total', 0)}"
    )
    for row in active_agents:
        lines.append(f"  [{row.get('status')}] {row.get('id')} — {row.get('task', '')}")

    routines = data.get("routines", {})
    enabled = routines.get("enabled") or []
    lines.append(f"routines\tenabled={len(enabled)} total={len(routines.get('all') or [])}")
    for row in enabled[:20]:
        lines.append(f"  [on] {row.get('id')} {row.get('schedule')} → {row.get('action')}")

    servers = data.get("servers", {})
    webhook = servers.get("webhook") or {}
    if webhook:
        lines.append(
            "webhook\t"
            f"enabled={bool(webhook.get('enabled'))} running={bool(webhook.get('pid_alive'))} "
            f"pid={webhook.get('pid') or '-'} url={webhook.get('inbox_url') or '-'}"
        )
    mcp = servers.get("mcp") or {}
    lines.append(
        f"mcp\tconfigured={len(mcp.get('configured') or [])} "
        f"active_processes={len(mcp.get('active_processes') or [])}"
    )
    for name in mcp.get("configured") or []:
        lines.append(f"  configured\t{name}")
    processes = servers.get("processes") or []
    lines.append(f"processes\tarka_owned={len(processes)}")
    for row in processes[:20]:
        lines.append(f"  pid={row.get('pid')} {row.get('kind')} — {row.get('command')}")
    if data.get("active_count", 0) == 0:
        lines.append("No active Arka background subagents, enabled routines, or server processes were found.")
    return "\n".join(lines)


def route_command(text: str) -> str:
    clean = " ".join((text or "").split()).strip()
    if not clean:
        return ""
    if re.search(
        r"(?i)\b(?:background|running|active)\b.*\b(?:process(?:es)?|tasks?|agents?|routines?|servers?)\b",
        clean,
    ):
        return "background processes"
    if re.search(r"(?i)\bwhat\s+(?:is|are)\s+arka\s+running\b", clean):
        return "background processes"
    return ""


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka background")
    sub = parser.add_subparsers(dest="cmd")
    p = sub.add_parser("processes", help="Show active Arka subagents, routines, and servers")
    p.add_argument("--json", action="store_true")
    # Backward-compatible alias: arka background agent tasks
    agent = sub.add_parser("agent", help=argparse.SUPPRESS)
    agent.add_argument("agent_cmd", nargs="?")
    agent.add_argument("--json", action="store_true")
    args = parser.parse_args(list(argv or ["processes"]))
    if args.cmd == "agent" and args.agent_cmd not in {"tasks", "list", "status"}:
        print("Usage: arka background agent tasks", file=sys.stderr)
        return 1
    data = collect_status()
    if getattr(args, "json", False):
        print(json.dumps(data, indent=2))
    else:
        print(format_status(data))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
