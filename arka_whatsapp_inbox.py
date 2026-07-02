#!/usr/bin/env python3
"""Arka bridge — WhatsApp inbox → agent (Selenium listen + pywhatkit send)."""

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
import time
from pathlib import Path


def _automation_dir() -> Path:
    override = os.environ.get("ARKA_WHATSAPP_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    try:
        from arka.paths import arka_home

        bundled = arka_home() / "whatsapp"
        if (bundled / "whatsapp_automation.py").is_file():
            return bundled
    except ImportError:
        pass
    root = Path(__file__).resolve().parent
    if (root / "whatsapp" / "whatsapp_automation.py").is_file():
        return root / "whatsapp"
    legacy = Path.home() / "Projects/python/products/automation"
    if legacy.is_dir():
        return legacy
    return root / "whatsapp"


def _ensure_automation_import() -> None:
    path = str(_automation_dir())
    if path not in sys.path:
        sys.path.insert(0, path)


_ensure_automation_import()

try:
    from whatsapp_automation import (  # noqa: E402
        DEBUG_LOG,
        backend_label,
        listen_inbox,
        normalize_phone,
        phone_matches,
        send_instant,
        wa_log,
    )
except ImportError as exc:
    print(
        f"whatsapp: missing automation module in {_automation_dir()} ({exc})",
        file=sys.stderr,
    )
    raise SystemExit(1) from exc


def _cache_dir() -> Path:
    try:
        from arka.paths import cache_dir

        return cache_dir()
    except ImportError:
        return Path.home() / ".cache" / "fish-agent"


def _config_env() -> Path:
    try:
        from arka.paths import env_file

        return env_file()
    except ImportError:
        return Path.home() / ".config" / "fish" / ".env"


CACHE = _cache_dir()
STATE_PATH = CACHE / "whatsapp_inbox.json"
PID_PATH = CACHE / "arka_whatsapp.pid"


def load_dotenv() -> None:
    try:
        from arka.env import load_env

        load_env()
        return
    except ImportError:
        pass
    env_path = _config_env()
    if not env_path.is_file():
        return
    for line in env_path.read_text(encoding="utf-8").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        os.environ.setdefault(key.strip(), val.strip().strip('"').strip("'"))


def allowed_senders() -> list[str]:
    raw = os.environ.get("ARKA_WHATSAPP_FROM", "").strip()
    if not raw:
        return []
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
    text = re.sub(r"\n?\s*Model:\s*\S+.*", "", text, flags=re.I)
    text = re.sub(r"\s*🔎\s*.*$", "", text)
    text = " ".join(text.split())
    max_len = int(os.environ.get("AGENT_SPEAK_MAX", "450"))
    if len(text) > max_len:
        text = text[: max_len - 3].rstrip() + "..."
    return text


def _message_state():
    try:
        sys.path.insert(0, str(_automation_dir()))
        from message_state import (  # noqa: WPS433
            format_bot_reply,
            is_outgoing_echo,
            register_outgoing,
        )

        return format_bot_reply, is_outgoing_echo, register_outgoing
    except ImportError:
        def _fmt(t: str) -> str:
            return t

        def _echo(_t: str) -> bool:
            return False

        def _reg(_t: str) -> None:
            return None

        return _fmt, _echo, _reg


def run_arka_agent(text: str) -> tuple[str, str, int]:
    text = text.strip()
    if not text:
        return "", "", 1
    env = os.environ.copy()
    env["AGENT_SPEAK"] = "0"
    timeout = int(os.environ.get("ARKA_REMOTE_TIMEOUT", "600"))

    fish = shutil_which("fish")
    cfg = None
    try:
        from arka.paths import fish_config

        cfg = fish_config()
    except ImportError:
        pass

    if fish and cfg:
        cmd = f"source {shlex.quote(str(cfg))}; agent {shlex.quote(text)}"
        try:
            proc = subprocess.run(
                [fish, "-c", cmd],
                capture_output=True,
                text=True,
                env=env,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return "", "Sorry, that took too long.", 124
        output = ((proc.stdout or "") + (proc.stderr or "")).strip()
        return output, extract_speak_text(output), proc.returncode

    arka = shutil_which("arka")
    if arka:
        try:
            proc = subprocess.run(
                [arka, text],
                capture_output=True,
                text=True,
                env=env,
                timeout=timeout,
            )
        except subprocess.TimeoutExpired:
            return "", "Sorry, that took too long.", 124
        output = ((proc.stdout or "") + (proc.stderr or "")).strip()
        return output, extract_speak_text(output), proc.returncode

    return "", "Arka agent unavailable (install fish or run: pip install -e arka-agent)", 1


def shutil_which(name: str) -> str | None:
    import shutil

    return shutil.which(name)


def load_state() -> dict:
    if not STATE_PATH.exists():
        return {"seen": []}
    try:
        return json.loads(STATE_PATH.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        return {"seen": []}


def save_state(state: dict) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    seen = state.get("seen", [])
    if len(seen) > 500:
        seen = seen[-500:]
    state["seen"] = seen
    STATE_PATH.write_text(json.dumps(state, indent=2), encoding="utf-8")


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
    format_bot_reply, is_outgoing_echo, register_outgoing = _message_state()
    if not text:
        return {"ok": False, "error": "empty message"}
    if is_outgoing_echo(text):
        wa_log("skip", reason="bot/outgoing echo", from_=from_num, text=text[:120])
        return {"ok": True, "skipped": True, "reason": "bot_echo"}
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
            reply = format_bot_reply(reply[:1500])
            wa_log("send", to=from_num, via="automation", source=source, text=reply[:1500])
            try:
                send_instant(from_num, reply[:1500])
                register_outgoing(reply[:1500])
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
    format_bot_reply, _, _ = _message_state()
    reply = result.get("speak_text") or result.get("output") or ""
    max_len = int(os.environ.get("ARKA_WHATSAPP_REPLY_MAX", "1500"))
    if len(reply) > max_len:
        reply = reply[: max_len - 3].rstrip() + "..."
    reply = format_bot_reply(reply) if reply else ""
    return reply if reply else None


def listen_whatsapp_web() -> int:
    load_dotenv()
    backend = backend_label()
    if "web" in backend:
        try:
            import selenium  # noqa: F401
        except ImportError:
            print("Install: pip install selenium pywhatkit", file=sys.stderr)
            print("  Or on macOS use native app (default): ARKA_WHATSAPP_BACKEND=desktop", file=sys.stderr)
            return 1

    senders = allowed_senders()
    if not senders:
        print(f"Set ARKA_WHATSAPP_FROM in {_config_env()}", file=sys.stderr)
        print("  Example: ARKA_WHATSAPP_FROM=+919876543210", file=sys.stderr)
        return 1

    poll = float(os.environ.get("ARKA_WHATSAPP_POLL", "5"))
    CACHE.mkdir(parents=True, exist_ok=True)
    PID_PATH.write_text(str(os.getpid()), encoding="utf-8")

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

    def handler(sender: str, text: str) -> str | None:
        key = message_key(sender, text)
        if already_seen(_state, key):
            wa_log("skip", reason="already in session", from_=sender, text=text)
            return None
        reply = _on_whatsapp_message(sender, text)
        return reply

    print(f"WhatsApp inbox listening for: {', '.join(senders)}")
    print(f"Backend: {backend}  log: {DEBUG_LOG}")
    try:
        sys.path.insert(0, str(_automation_dir()))
        from message_state import self_chat_enabled  # noqa: WPS433

        if self_chat_enabled(len(senders)):
            print("Self-chat mode: watching “You” / message-yourself + allowed numbers.")
    except ImportError:
        pass
    if "desktop" in backend:
        print("Using your installed WhatsApp app — not Chrome.")
        print("Grant Accessibility to Terminal/Cursor/iTerm in System Settings if sends/listen fail.")
    else:
        print(f"Profile: {CACHE / 'whatsapp-chrome-profile'}")
        print("Scan QR in Chrome if this is the first web run. Ctrl+C to stop.")
    listen_inbox(senders, handler, poll=poll, reply_in_browser=reply_in_browser)
    return 0


def cmd_status() -> int:
    load_dotenv()
    senders = allowed_senders()
    print("━━━ WhatsApp inbox ━━━")
    print(f"Automation: {_automation_dir()}")
    print(f"Backend:    {backend_label()}")
    print(f"Allowed senders: {', '.join(senders) if senders else '(not set — add ARKA_WHATSAPP_FROM)'}")
    print(f"Reply enabled: {os.environ.get('ARKA_WHATSAPP_REPLY', '1')}")
    print(f"Debug: {os.environ.get('ARKA_WHATSAPP_DEBUG', '0')}  log: {DEBUG_LOG}")
    if not senders:
        return 1
    if PID_PATH.exists():
        pid = PID_PATH.read_text(encoding="utf-8").strip()
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
        print("WhatsApp inbox: not running")
        return 0
    try:
        pid = int(PID_PATH.read_text(encoding="utf-8").strip())
        os.kill(pid, signal.SIGTERM)
    except (OSError, ValueError):
        pass
    PID_PATH.unlink(missing_ok=True)
    print("[whatsapp-inbox] Stopped")
    return 0


def cmd_start() -> int:
    """Start listener in background (same as whatsapp_listen with no args)."""
    if PID_PATH.is_file():
        try:
            pid = int(PID_PATH.read_text(encoding="utf-8").strip())
            os.kill(pid, 0)
            print(f"WhatsApp inbox already running (pid {pid})")
            return 0
        except (OSError, ValueError):
            PID_PATH.unlink(missing_ok=True)
    log = CACHE / "arka_whatsapp.log"
    CACHE.mkdir(parents=True, exist_ok=True)
    script = Path(__file__).resolve()
    py = sys.executable
    with open(log, "ab") as fh:
        proc = subprocess.Popen(
            [py, str(script), "listen"],
            stdout=fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    time.sleep(1.5)
    if proc.poll() is not None:
        print(f"Listener exited — see {log}", file=sys.stderr)
        return 1
    print(f"WhatsApp inbox started in background (pid {proc.pid})")
    print(f"  log: {log}  |  stop: arka whatsapp inbox stop")
    return cmd_status()


def _normalize_whatsapp_argv(argv: list[str]) -> list[str]:
    if len(argv) < 2:
        return argv
    alias = {
        "fg": "listen",
        "foreground": "listen",
        "run": "listen",
    }
    head = argv[1].lower()
    if head in alias:
        argv = argv[:1] + [alias[head]] + argv[2:]
    return argv


def main() -> int:
    load_dotenv()
    sys.argv = _normalize_whatsapp_argv(sys.argv)
    parser = argparse.ArgumentParser(description="WhatsApp inbox → Arka")
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("listen", help="Listen in foreground (fg)")
    sub.add_parser("start", help="Start listener in background")
    sub.add_parser("status", help="Show listener status")
    sub.add_parser("stop", help="Stop background listener")

    p_fwd = sub.add_parser("forward", help="Test forward a message to agent")
    p_fwd.add_argument("--from", dest="from_num", required=True)
    p_fwd.add_argument("--text", required=True)
    p_fwd.add_argument("--source", default="manual")

    _add_send_parser(sub)

    args = parser.parse_args()
    if args.cmd == "listen":
        return listen_whatsapp_web()
    if args.cmd == "start":
        return cmd_start()
    if args.cmd == "status":
        return cmd_status()
    if args.cmd == "stop":
        return cmd_stop()
    if args.cmd == "forward":
        result = handle_inbox_message(args.from_num, args.text, source=args.source)
        print(json.dumps(result, indent=2))
        return 0 if result.get("ok") else 1
    if args.cmd == "send":
        send_instant(args.to, args.text)
        print(f"Sent to {normalize_phone(args.to)}")
        return 0
    return cmd_status()


def _add_send_parser(sub) -> None:
    p = sub.add_parser("send", help="Send a WhatsApp message")
    p.add_argument("to", help="Phone number or contact")
    p.add_argument("text", help="Message text")


if __name__ == "__main__":
    raise SystemExit(main())
