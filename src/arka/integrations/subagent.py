#!/usr/bin/env python3
"""Isolated sub-agent delegation — parallel background agent tasks."""

from __future__ import annotations

import argparse
import json
import os
import shlex
import subprocess
import sys
import threading
import time
import uuid
from datetime import datetime
from pathlib import Path

try:
    from arka.paths import cache_dir, load_env_file

    load_env_file()
except ImportError:

    def cache_dir() -> Path:
        return Path.home() / ".cache" / "fish-agent"

    def load_env_file() -> None:
        pass


def _env(primary: str, legacy: str, default: str = "") -> str:
    val = os.environ.get(primary, "").strip()
    if val:
        return val
    val = os.environ.get(legacy, "").strip()
    if val:
        return val
    return default


def _enabled() -> bool:
    return _env("SUBAGENT_ENABLED", "HERMES_SUBAGENT", "1").lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def subagents_root() -> Path:
    if raw := _env("SUBAGENT_DIR", "HERMES_SUBAGENT_DIR", ""):
        return Path(raw).expanduser()
    return cache_dir() / "subagents"


def _max_concurrent() -> int:
    try:
        return max(1, int(_env("SUBAGENT_MAX", "HERMES_SUBAGENT_MAX", "3")))
    except ValueError:
        return 3


def _timeout() -> int:
    try:
        return max(30, int(_env("SUBAGENT_TIMEOUT", "HERMES_SUBAGENT_TIMEOUT", "600")))
    except ValueError:
        return 600


def _agent_path(agent_id: str) -> Path:
    safe = "".join(c if c.isalnum() or c in "-_" else "_" for c in agent_id)
    return subagents_root() / f"{safe}.json"


def _security_gate(task: str) -> tuple[bool, str]:
    task = (task or "").strip()
    if not task:
        return False, "empty task"
    if len(task) > int(_env("SUBAGENT_MAX_CHARS", "HERMES_SUBAGENT_MAX_CHARS", "4000")):
        return False, "task too long"
    if _env("SUBAGENT_SECURITY", "HERMES_SUBAGENT_SECURITY", "1").lower() in ("0", "false", "no"):
        return True, ""
    try:
        from arka.core.security import verify_user_prompt

        gate = verify_user_prompt(task)
        if gate.status == "block":
            return False, gate.reason
    except ImportError:
        pass
    return True, ""


def _load(agent_id: str) -> dict | None:
    path = _agent_path(agent_id)
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else None
    except (OSError, json.JSONDecodeError):
        return None


def _save(data: dict) -> None:
    root = subagents_root()
    root.mkdir(parents=True, exist_ok=True)
    agent_id = data.get("id") or uuid.uuid4().hex[:10]
    data["id"] = agent_id
    data["updated"] = time.time()
    _agent_path(agent_id).write_text(json.dumps(data, indent=2), encoding="utf-8")


def _running_count() -> int:
    count = 0
    root = subagents_root()
    if not root.is_dir():
        return 0
    for path in root.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict) and data.get("status") == "running":
                count += 1
        except (OSError, json.JSONDecodeError):
            continue
    return count


def _run_agent(task: str, *, session_channel: str = "", session_chat_id: str = "") -> tuple[str, int]:
    prefix = ""
    if session_channel:
        try:
            from arka.integrations.message_sessions import context_for

            ctx = context_for(session_channel, session_chat_id or "default")
            if ctx:
                prefix = f"[Sub-agent context]\n{ctx}\n\n[Task]\n"
        except ImportError:
            pass
    prompt = prefix + task.strip()
    try:
        from arka.agent.chat import answer_question

        _, answer = answer_question(prompt, deep=False, use_session=False, cleanup=True)
        return answer or "(no output)", 0
    except ImportError:
        pass
    env = os.environ.copy()
    env["AGENT_SPEAK"] = "0"
    cmd = f"agent {shlex.quote(prompt)}"
    try:
        proc = subprocess.run(
            ["fish", "-ic", cmd],
            capture_output=True,
            text=True,
            env=env,
            timeout=_timeout(),
        )
    except subprocess.TimeoutExpired:
        return "Sub-agent timed out.", 124
    out = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return out or "(no output)", int(proc.returncode or 0)


def _execute(agent_id: str) -> None:
    data = _load(agent_id)
    if not data or data.get("status") not in {"pending", "running"}:
        return
    data["status"] = "running"
    data["started"] = time.time()
    _save(data)
    output, code = _run_agent(
        str(data.get("task", "")),
        session_channel=str(data.get("session_channel", "")),
        session_chat_id=str(data.get("session_chat_id", "")),
    )
    data["status"] = "done" if code == 0 else "failed"
    data["finished"] = time.time()
    data["exit_code"] = code
    data["result"] = output[-4000:]
    _save(data)
    try:
        from arka.integrations.heartbeat import ping

        ping(f"subagent.{data['status']}", source="subagent")
    except Exception:
        pass
    sess_ch = data.get("session_channel")
    if sess_ch:
        try:
            from arka.integrations.message_sessions import is_silence_token, push

            if not is_silence_token(output):
                push(str(sess_ch), str(data.get("session_chat_id", "default")), "assistant", output)
        except ImportError:
            pass


def spawn(
    task: str,
    *,
    session_channel: str = "",
    session_chat_id: str = "",
    background: bool = True,
) -> tuple[dict | None, str | None]:
    if not _enabled():
        return None, "subagent disabled"
    ok, reason = _security_gate(task)
    if not ok:
        return None, reason
    if _running_count() >= _max_concurrent():
        return None, f"max concurrent sub-agents ({_max_concurrent()}) reached"
    agent_id = uuid.uuid4().hex[:10]
    data = {
        "id": agent_id,
        "task": task.strip(),
        "status": "pending",
        "session_channel": session_channel,
        "session_chat_id": session_chat_id,
        "created": time.time(),
        "when": datetime.now().isoformat(timespec="seconds"),
    }
    _save(data)
    if background and _env("SUBAGENT_SYNC", "HERMES_SUBAGENT_SYNC", "").lower() not in (
        "1",
        "true",
        "yes",
    ):
        thread = threading.Thread(target=_execute, args=(agent_id,), daemon=True)
        thread.start()
    else:
        _execute(agent_id)
        data = _load(agent_id) or data
    return data, None


def list_agents(*, limit: int = 20) -> list[dict]:
    root = subagents_root()
    if not root.is_dir():
        return []
    rows: list[tuple[float, dict]] = []
    for path in root.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if isinstance(data, dict):
                rows.append((float(data.get("created") or 0), data))
        except (OSError, json.JSONDecodeError):
            continue
    rows.sort(key=lambda x: x[0], reverse=True)
    out: list[dict] = []
    for _, data in rows[:limit]:
        out.append(
            {
                "id": data.get("id"),
                "status": data.get("status"),
                "task": str(data.get("task", ""))[:120],
                "when": data.get("when"),
                "exit_code": data.get("exit_code"),
            }
        )
    return out


def agent_status(agent_id: str) -> dict | None:
    return _load(agent_id)


def resume_payload(agent_id: str) -> dict | None:
    """Return a resume-friendly snapshot of a sub-agent (Hermes-style result fetch)."""
    data = _load(agent_id)
    if not data:
        return None
    return {
        "id": data.get("id"),
        "status": data.get("status"),
        "task": data.get("task"),
        "result": data.get("result"),
        "exit_code": data.get("exit_code"),
        "when": data.get("when"),
        "started": data.get("started"),
        "finished": data.get("finished"),
        "session_channel": data.get("session_channel"),
        "session_chat_id": data.get("session_chat_id"),
    }


def resume(agent_id: str) -> int:
    data = resume_payload(agent_id)
    if not data:
        print(f"No sub-agent {agent_id}.", file=sys.stderr)
        return 1
    print(f"Sub-agent {data.get('id')} [{data.get('status')}]")
    print(f"Task: {data.get('task', '')}")
    if data.get("result"):
        print(f"Result:\n{data.get('result')}")
    return 0


def status_summary() -> dict:
    root = subagents_root()
    rows = list_agents(limit=100)
    by_status: dict[str, int] = {}
    for row in rows:
        st = str(row.get("status", "?"))
        by_status[st] = by_status.get(st, 0) + 1
    return {
        "enabled": _enabled(),
        "root": str(root),
        "max_concurrent": _max_concurrent(),
        "running": _running_count(),
        "total": len(list(root.glob("*.json"))) if root.is_dir() else 0,
        "by_status": by_status,
    }


def print_status() -> None:
    info = status_summary()
    print(f"Sub-agents: {'on' if info['enabled'] else 'off'}")
    print(f"  Root: {info['root']}")
    print(f"  Running: {info['running']} / {info['max_concurrent']}")
    print(f"  Stored: {info['total']}")
    if info.get("by_status"):
        parts = [f"{k}={v}" for k, v in sorted(info["by_status"].items())]
        print(f"  Status: {', '.join(parts)}")


def main() -> int:
    load_env_file()
    parser = argparse.ArgumentParser(description="Isolated sub-agent delegation")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("spawn", help="Spawn a background sub-agent for a task")
    p.add_argument("task")
    p.add_argument("--session-channel", default="")
    p.add_argument("--session-chat-id", default="")
    p.add_argument("--sync", action="store_true", help="Run synchronously (for tests)")

    p = sub.add_parser("resume")
    p.add_argument("agent_id")

    p = sub.add_parser("status")
    p.add_argument("agent_id", nargs="?")

    sub.add_parser("list")

    args = parser.parse_args()
    if args.cmd == "spawn":
        if args.sync:
            os.environ["SUBAGENT_SYNC"] = "1"
        data, err = spawn(
            args.task,
            session_channel=args.session_channel,
            session_chat_id=args.session_chat_id,
            background=not args.sync,
        )
        if err:
            print(f"Spawn blocked: {err}", file=sys.stderr)
            return 1
        assert data is not None
        print(f"Sub-agent {data['id']} [{data.get('status', 'pending')}]")
        if data.get("result"):
            print(data["result"])
        return 0 if data.get("status") != "failed" else 1
    if args.cmd == "resume":
        return resume(args.agent_id)
    if args.cmd == "status":
        if args.agent_id:
            data = agent_status(args.agent_id)
            if not data:
                print(f"No sub-agent {args.agent_id}.", file=sys.stderr)
                return 1
            print(json.dumps(data, indent=2))
            return 0
        print_status()
        return 0
    if args.cmd == "list":
        rows = list_agents()
        if not rows:
            print("No sub-agents.")
            return 0
        for row in rows:
            print(f"[{row['status']}] {row['id']}  {row.get('when', '')}")
            print(f"  {row.get('task', '')}")
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
