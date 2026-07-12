#!/usr/bin/env python3
"""Per-channel message sessions — cross-platform continuity and idle reset."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from arka.paths import config_dir, load_env_file

    load_env_file()
except ImportError:

    def config_dir() -> Path:
        return Path.home() / ".config" / "arka"

    def load_env_file() -> None:
        pass


SILENCE_TOKENS = frozenset({"[silent]", "silent", "no_reply", "no reply"})
SESSION_KEY_RE = re.compile(r"^[a-z][a-z0-9_-]{0,31}:[a-zA-Z0-9_.@-]{1,64}$")


def _env(primary: str, legacy: str, default: str = "") -> str:
    val = os.environ.get(primary, "").strip()
    if val:
        return val
    val = os.environ.get(legacy, "").strip()
    if val:
        return val
    return default


def _enabled() -> bool:
    return _env("MESSAGE_SESSIONS", "HERMES_SESSIONS", "1").lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def sessions_root() -> Path:
    if raw := _env("MESSAGE_SESSIONS_DIR", "HERMES_SESSIONS_DIR", ""):
        return Path(raw).expanduser()
    return config_dir() / "message-sessions"


def _idle_minutes() -> int:
    try:
        return max(0, int(_env("MESSAGE_SESSION_IDLE_MINUTES", "HERMES_SESSION_IDLE_MINUTES", "0")))
    except ValueError:
        return 0


def _max_turns() -> int:
    try:
        return max(4, int(_env("MESSAGE_SESSION_MAX_TURNS", "HERMES_SESSION_MAX_TURNS", "40")))
    except ValueError:
        return 40


def cli_channel() -> str:
    return _env("MESSAGE_SESSION_CHANNEL", "HERMES_SESSION_CHANNEL", "cli") or "cli"


def cli_chat_id() -> str:
    return _env("MESSAGE_SESSION_CHAT_ID", "HERMES_SESSION_CHAT_ID", "default") or "default"


def session_key(channel: str, chat_id: str) -> str:
    ch = (channel or "cli").strip().lower()[:32] or "cli"
    cid = (chat_id or "default").strip()[:64] or "default"
    cid = re.sub(r"[^a-zA-Z0-9_.@-]", "_", cid)
    return f"{ch}:{cid}"


def _session_path(key: str) -> Path:
    safe = re.sub(r"[^a-zA-Z0-9_.@-]", "_", key)
    return sessions_root() / f"{safe}.json"


def _sanitize_text(text: str) -> tuple[str, str | None]:
    text = " ".join((text or "").split()).strip()
    if not text:
        return "", "empty"
    try:
        from arka.core.security import sanitize_llm_context, verify_user_prompt

        gate = verify_user_prompt(text)
        if gate.status == "block":
            return "", gate.reason
        cleaned, _ = sanitize_llm_context(text)
        return (cleaned or text).strip(), None
    except ImportError:
        return text, None


def is_silence_token(text: str) -> bool:
    return (text or "").strip().lower() in SILENCE_TOKENS


def silence_tokens() -> list[str]:
    """Return known Hermes-style silence tokens (stable order)."""
    return sorted(SILENCE_TOKENS)


def silence_check(text: str) -> dict[str, object]:
    """Structured silence-token check for MCP / webhooks."""
    raw = text or ""
    silent = is_silence_token(raw)
    return {
        "silent": silent,
        "text": raw.strip(),
        "tokens": silence_tokens(),
    }


def _load_session(key: str) -> dict:
    path = _session_path(key)
    if not path.is_file():
        return {
            "key": key,
            "channel": key.split(":", 1)[0],
            "chat_id": key.split(":", 1)[-1] if ":" in key else "default",
            "title": "",
            "turns": [],
            "created": time.time(),
            "last_activity": time.time(),
        }
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        if isinstance(data, dict):
            data.setdefault("key", key)
            data.setdefault("turns", [])
            return data
    except (OSError, json.JSONDecodeError):
        pass
    return {"key": key, "turns": [], "created": time.time(), "last_activity": time.time()}


def _save_session(data: dict) -> None:
    root = sessions_root()
    root.mkdir(parents=True, exist_ok=True)
    key = data.get("key") or session_key(str(data.get("channel", "cli")), str(data.get("chat_id", "default")))
    data["key"] = key
    data["last_activity"] = time.time()
    turns = data.get("turns") or []
    if isinstance(turns, list) and len(turns) > _max_turns():
        data["turns"] = turns[-_max_turns() :]
    _session_path(key).write_text(json.dumps(data, indent=2), encoding="utf-8")


def maybe_idle_reset(data: dict) -> bool:
    idle = _idle_minutes()
    if idle <= 0:
        return False
    last = float(data.get("last_activity") or 0)
    if last and (time.time() - last) > idle * 60:
        data["turns"] = []
        data["reset_reason"] = "idle"
        data["reset_at"] = time.time()
        return True
    return False


def push(
    channel: str,
    chat_id: str,
    role: str,
    text: str,
    *,
    title: str = "",
) -> tuple[int, str | None]:
    if not _enabled():
        return 1, "sessions disabled"
    cleaned, err = _sanitize_text(text)
    if err:
        return 1, err
    if not cleaned:
        return 1, "empty"
    role = (role or "user").strip().lower()
    if role not in {"user", "assistant", "system"}:
        role = "user"
    key = session_key(channel, chat_id)
    data = _load_session(key)
    maybe_idle_reset(data)
    data["channel"] = channel or "cli"
    data["chat_id"] = chat_id or "default"
    if title:
        data["title"] = title[:120]
    turns = data.setdefault("turns", [])
    if not isinstance(turns, list):
        turns = []
        data["turns"] = turns
    turns.append(
        {
            "role": role,
            "text": cleaned,
            "ts": time.time(),
            "when": datetime.now().isoformat(timespec="seconds"),
        }
    )
    _save_session(data)
    try:
        from arka.integrations.heartbeat import ping

        ping(f"session.{role}", source=f"channel:{channel}")
    except Exception:
        pass
    return 0, None


def reset(channel: str, chat_id: str) -> int:
    key = session_key(channel, chat_id)
    data = _load_session(key)
    data["turns"] = []
    data["reset_reason"] = "manual"
    data["reset_at"] = time.time()
    _save_session(data)
    return 0


def context_for(channel: str, chat_id: str, *, limit_chars: int = 3000) -> str:
    if not _enabled():
        return ""
    key = session_key(channel, chat_id)
    data = _load_session(key)
    maybe_idle_reset(data)
    turns = data.get("turns") or []
    if not isinstance(turns, list) or not turns:
        return ""
    lines: list[str] = []
    title = (data.get("title") or "").strip()
    if title:
        lines.append(f"Session: {title}")
    lines.append(f"Channel: {data.get('channel', channel)} / {data.get('chat_id', chat_id)}")
    for turn in turns[-12:]:
        role = str(turn.get("role", "user")).upper()
        text = str(turn.get("text", "")).strip()
        if text:
            lines.append(f"{role}: {text}")
    out = "\n".join(lines).strip()
    if len(out) > limit_chars:
        out = out[-limit_chars:]
    return out


def list_sessions(*, limit: int = 20) -> list[dict]:
    root = sessions_root()
    if not root.is_dir():
        return []
    rows: list[tuple[float, dict]] = []
    for path in root.glob("*.json"):
        try:
            data = json.loads(path.read_text(encoding="utf-8"))
            if not isinstance(data, dict):
                continue
            rows.append((float(data.get("last_activity") or 0), data))
        except (OSError, json.JSONDecodeError):
            continue
    rows.sort(key=lambda x: x[0], reverse=True)
    out: list[dict] = []
    for _, data in rows[:limit]:
        turns = data.get("turns") or []
        out.append(
            {
                "key": data.get("key", ""),
                "channel": data.get("channel", ""),
                "chat_id": data.get("chat_id", ""),
                "title": data.get("title", ""),
                "turns": len(turns) if isinstance(turns, list) else 0,
                "last_activity": data.get("last_activity"),
            }
        )
    return out


def resume_payload(channel: str, chat_id: str, *, limit: int = 12) -> dict:
    """Return structured session turns for MCP / programmatic resume."""
    key = session_key(channel, chat_id)
    data = _load_session(key)
    turns = data.get("turns") or []
    if not isinstance(turns, list):
        turns = []
    limit = max(1, min(int(limit or 12), 100))
    rows: list[dict] = []
    for turn in turns[-limit:]:
        if not isinstance(turn, dict):
            continue
        text = str(turn.get("text", "")).strip()
        if not text:
            continue
        rows.append(
            {
                "role": str(turn.get("role", "user")),
                "text": text,
                "when": turn.get("when", ""),
                "ts": turn.get("ts"),
            }
        )
    return {
        "key": key,
        "channel": data.get("channel", channel),
        "chat_id": data.get("chat_id", chat_id),
        "title": data.get("title", ""),
        "turns": rows,
        "turn_count": len(turns),
    }


def resume(channel: str, chat_id: str, *, limit: int = 12) -> int:
    payload = resume_payload(channel, chat_id, limit=limit)
    rows = payload.get("turns") or []
    if not rows:
        print(f"No turns in session {payload.get('key')}.")
        return 0
    title = payload.get("title") or ""
    print(f"Session {payload.get('key')}" + (f" — {title}" if title else ""))
    for turn in rows:
        role = str(turn.get("role", "user")).upper()
        when = turn.get("when", "")
        text = str(turn.get("text", "")).strip()
        print(f"[{when}] {role}: {text}")
    return 0


def status(channel: str | None = None, chat_id: str | None = None) -> dict:
    info: dict[str, object] = {
        "enabled": _enabled(),
        "root": str(sessions_root()),
        "idle_minutes": _idle_minutes(),
        "max_turns": _max_turns(),
        "sessions": len(list(sessions_root().glob("*.json"))) if sessions_root().is_dir() else 0,
    }
    if channel is not None:
        key = session_key(channel, chat_id or "default")
        data = _load_session(key)
        turns = data.get("turns") or []
        info["session"] = {
            "key": key,
            "title": data.get("title", ""),
            "turns": len(turns) if isinstance(turns, list) else 0,
            "last_activity": data.get("last_activity"),
        }
    return info


def print_status(channel: str | None = None, chat_id: str | None = None) -> None:
    info = status(channel, chat_id)
    print(f"Message sessions: {'on' if info['enabled'] else 'off'}")
    print(f"  Root: {info['root']}")
    print(f"  Stored sessions: {info['sessions']}")
    print(f"  Idle reset: {info['idle_minutes']} min (0 = never)")
    sess = info.get("session")
    if isinstance(sess, dict):
        print(f"  Active: {sess.get('key')} ({sess.get('turns')} turns)")


def main() -> int:
    load_env_file()
    parser = argparse.ArgumentParser(description="Per-channel message sessions")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("push", help="Append a turn to a channel session")
    p.add_argument("channel")
    p.add_argument("chat_id")
    p.add_argument("role", choices=["user", "assistant", "system"])
    p.add_argument("text")

    p = sub.add_parser("context")
    p.add_argument("channel")
    p.add_argument("chat_id")

    p = sub.add_parser("resume")
    p.add_argument("channel")
    p.add_argument("chat_id")
    p.add_argument("--limit", type=int, default=12)

    p = sub.add_parser("reset")
    p.add_argument("channel")
    p.add_argument("chat_id")

    sub.add_parser("list")

    p = sub.add_parser("status")
    p.add_argument("channel", nargs="?")
    p.add_argument("chat_id", nargs="?")

    args = parser.parse_args()
    if args.cmd == "push":
        code, err = push(args.channel, args.chat_id, args.role, args.text)
        if err:
            print(f"Push blocked: {err}", file=sys.stderr)
        else:
            print(f"Pushed to {session_key(args.channel, args.chat_id)}")
        return code
    if args.cmd == "context":
        ctx = context_for(args.channel, args.chat_id)
        print(ctx or "(no session context)")
        return 0
    if args.cmd == "resume":
        return resume(args.channel, args.chat_id, limit=args.limit)
    if args.cmd == "reset":
        reset(args.channel, args.chat_id)
        print(f"Reset {session_key(args.channel, args.chat_id)}")
        return 0
    if args.cmd == "list":
        rows = list_sessions()
        if not rows:
            print("No message sessions.")
            return 0
        for row in rows:
            title = f" — {row['title']}" if row.get("title") else ""
            print(f"{row['key']}{title}  ({row['turns']} turns)")
        return 0
    if args.cmd == "status":
        print_status(args.channel, args.chat_id)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
