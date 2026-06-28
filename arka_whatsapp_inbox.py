#!/usr/bin/env python3
"""Arka bridge — WhatsApp inbox → agent (uses whatsapp_automation + pywhatkit + Selenium)."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import signal
import subprocess
import sys
from pathlib import Path

AUTOMATION_DIR = Path("/home/s/Projects/python/products/automation")
sys.path.insert(0, str(AUTOMATION_DIR))

from whatsapp_automation import (  # noqa: E402
    DEBUG_LOG,
    listen_inbox,
    normalize_phone,
    phone_matches,
    send_instant,
    wa_log,
)

CACHE = Path.home() / ".cache" / "fish-agent"
STATE_PATH = CACHE / "whatsapp_inbox.json"
PID_PATH = CACHE / "arka_whatsapp.pid"
ENV_PATH = Path.home() / ".config" / "fish" / ".env"


def load_dotenv() -> None:
    if not ENV_PATH.exists():
        return
    for line in ENV_PATH.read_text().splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def allowed_senders() -> list[str]:
    raw = os.environ.get("ARKA_WHATSAPP_FROM", "+919073153257").strip()
    return [normalize_phone(p.strip()) for p in raw.split(",") if p.strip()]


def sender_allowed(from_num: str) -> bool:
    allowed = allowed_senders()
    if not allowed:
        return True
    return any(phone_matches(from_num, s) for s in allowed)


def strip_ansi(text: str) -> str:
    return re.sub(r"\x1b\[[0-9;]*m", "", text)


def extract_speak_text(raw: str) -> str:
    text = strip_ansi(raw)
    if "━━━ Answer ━━━" in text:
        text = text.split("━━━ Answer ━━━", 1)[1]
    text = " ".join(text.split())
    max_len = int(os.environ.get("AGENT_SPEAK_MAX", "450"))
    if len(text) > max_len:
        text = text[: max_len - 3].rstrip() + "..."
    return text


def run_arka_agent(text: str) -> tuple[str, str, int]:
    text = text.strip()
    if not text:
        return "", "", 1
    env = os.environ.copy()
    env["AGENT_SPEAK"] = "0"
    cmd = f"agent {shlex.quote(text)}"
    try:
        proc = subprocess.run(
            ["fish", "-ic", cmd],
            capture_output=True,
            text=True,
            env=env,
            timeout=int(os.environ.get("ARKA_REMOTE_TIMEOUT", "600")),
        )
    except subprocess.TimeoutExpired:
        return "", "Sorry, that took too long.", 124
    output = ((proc.stdout or "") + (proc.stderr or "")).strip()
    return output, extract_speak_text(output), proc.returncode


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"seen": []}
    try:
        return json.loads(STATE_PATH.read_text())
    except (json.JSONDecodeError, OSError):
        return {"seen": []}


def save_state(state: dict) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    seen = state.get("seen", [])
    if len(seen) > 500:
        seen = seen[-500:]
    state["seen"] = seen
    STATE_PATH.write_text(json.dumps(state, indent=2))


def message_key(sender: str, text: str, msg_id: str = "") -> str:
    if msg_id:
        return msg_id
    blob = f"{normalize_phone(sender)}|{text.strip()}"
    return hashlib.sha256(blob.encode()).hexdigest()[:24]


def already_seen(state: dict, key: str) -> bool:
    return key in state.get("seen", [])


def mark_seen(state: dict, key: str) -> None:
    seen = state.setdefault("seen", [])
    if key not in seen:
        seen.append(key)


def handle_inbox_message(
    from_num: str, text: str, source: str = "whatsapp", auto_reply: bool | None = None
) -> dict:
    text = (text or "").strip()
    from_num = normalize_phone(from_num)
    if not text:
        return {"ok": False, "error": "empty message"}
    if not sender_allowed(from_num):
        wa_log("skip", reason="sender not allowed", from_=from_num, text=text)
        return {"ok": False, "error": f"sender {from_num} not in ARKA_WHATSAPP_FROM"}

    state = load_state()
    key = message_key(from_num, text)
    if already_seen(state, key):
        wa_log("skip", reason="duplicate", from_=from_num, text=text)
        return {"ok": True, "skipped": True, "reason": "duplicate"}

    mark_seen(state, key)
    save_state(state)
    wa_log("agent_in", from_=from_num, source=source, text=text)

    output, speak_text, code = run_arka_agent(text)
    reply = speak_text or output
    wa_log("agent_out", from_=from_num, exit_code=code, reply=reply)
    replied = False
    if auto_reply is None:
        auto_reply = source != "whatsapp"
    if auto_reply and os.environ.get("ARKA_WHATSAPP_REPLY", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    ):
        if reply:
            wa_log("send", to=from_num, via="pywhatkit", source=source, text=reply[:1500])
            try:
                send_instant(from_num, reply[:1500])
                replied = True
            except SystemExit:
                pass

    return {
        "ok": code == 0,
        "exit_code": code,
        "from": from_num,
        "source": source,
        "input": text,
        "output": output,
        "speak_text": speak_text,
        "replied": replied,
    }


_state = load_state()


def _on_whatsapp_message(sender: str, text: str) -> str | None:
    result = handle_inbox_message(sender, text, source="whatsapp", auto_reply=False)
    if result.get("skipped"):
        return None
    reply = result.get("speak_text") or result.get("output") or ""
    max_len = int(os.environ.get("ARKA_WHATSAPP_REPLY_MAX", "1500"))
    if len(reply) > max_len:
        reply = reply[: max_len - 3].rstrip() + "..."
    return reply if reply else None


def listen_whatsapp_web() -> int:
    load_dotenv()
    try:
        import selenium  # noqa: F401
    except ImportError:
        print("Install: venv-arka/bin/pip install selenium pywhatkit", file=sys.stderr)
        return 1

    senders = allowed_senders()
    if not senders:
        print("Set ARKA_WHATSAPP_FROM in ~/.config/fish/.env", file=sys.stderr)
        return 1

    poll = float(os.environ.get("ARKA_WHATSAPP_POLL", "5"))
    CACHE.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(str(os.getpid()))

    def _stop(_signum, _frame):
        PID_PATH.unlink(missing_ok=True)
        sys.exit(0)

    signal.signal(signal.SIGTERM, _stop)
    signal.signal(signal.SIGINT, _stop)

    reply_in_browser = os.environ.get("ARKA_WHATSAPP_REPLY", "1").strip().lower() not in (
        "0",
        "false",
        "no",
    )

    # Wrap handler to skip duplicates already in persistent state before agent runs
    def handler(sender: str, text: str) -> str | None:
        key = message_key(sender, text)
        if already_seen(_state, key):
            wa_log("skip", reason="already in session", from_=sender, text=text)
            return None
        reply = _on_whatsapp_message(sender, text)
        return reply

    listen_inbox(senders, handler, poll=poll, reply_in_browser=reply_in_browser)
    return 0


def cmd_status() -> int:
    load_dotenv()
    print(f"Allowed senders: {', '.join(allowed_senders())}")
    print(f"Reply enabled: {os.environ.get('ARKA_WHATSAPP_REPLY', '1')}")
    print(f"Debug: {os.environ.get('ARKA_WHATSAPP_DEBUG', '0')}  log: {DEBUG_LOG}")
    print("Engine: pywhatkit (send) + Selenium (listen)")
    if PID_PATH.exists():
        pid = PID_PATH.read_text().strip()
        try:
            os.kill(int(pid), 0)
            print(f"Listener: running (pid {pid})")
            return 0
        except (OSError, ValueError):
            PID_PATH.unlink(missing_ok=True)
    print("Listener: stopped")
    return 1


def cmd_stop() -> int:
    if not PID_PATH.exists():
        return 0
    try:
        pid = int(PID_PATH.read_text().strip())
        os.kill(pid, signal.SIGTERM)
    except (OSError, ValueError):
        pass
    PID_PATH.unlink(missing_ok=True)
    print("[whatsapp-inbox] Stopped")
    return 0


def main() -> int:
    load_dotenv()
    parser = argparse.ArgumentParser(description="WhatsApp inbox → Arka")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("listen")
    sub.add_parser("status")
    sub.add_parser("stop")
    p_fwd = sub.add_parser("forward")
    p_fwd.add_argument("--from", dest="from_num", required=True)
    p_fwd.add_argument("--text", required=True)
    p_fwd.add_argument("--source", default="manual")

    args = parser.parse_args()
    if args.cmd == "listen":
        return listen_whatsapp_web()
    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "stop":
        return cmd_stop()
    if args.cmd == "forward":
        result = handle_inbox_message(args.from_num, args.text, source=args.source)
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
