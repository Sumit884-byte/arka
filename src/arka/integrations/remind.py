#!/usr/bin/env python3
"""Arka remind — schedule reminders that survive shutdown and idle time."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
import signal
import subprocess
import sys
import time
import uuid
from datetime import datetime, timedelta
from pathlib import Path

try:
    from arka.paths import cache_dir
except ImportError:
    cache_dir = lambda: Path.home() / ".cache" / "fish-agent"  # noqa: E731

CACHE = cache_dir()
REMINDERS_FILE = CACHE / "reminders.json"
STATE_FILE = CACHE / "reminders_state.json"
PID_FILE = CACHE / "arka_remind.pid"
LOG_FILE = CACHE / "arka_remind.log"

TICK_SEC = float(os.environ.get("ARKA_REMIND_TICK_SEC", "30"))
GAP_SEC = float(os.environ.get("ARKA_REMIND_GAP_SEC", "120"))
IDLE_SEC = float(os.environ.get("ARKA_REMIND_IDLE_SEC", "300"))
ACTIVE_SEC = float(os.environ.get("ARKA_REMIND_ACTIVE_SEC", "60"))

_KNOWN_CMDS = frozenset({"daemon", "add", "list", "status", "start", "stop", "check", "cancel"})


def _load_json(path: Path, default: object) -> object:
    try:
        if path.is_file():
            return json.loads(path.read_text(encoding="utf-8"))
    except (json.JSONDecodeError, OSError):
        pass
    return default


def _save_json(path: Path, data: object) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, ensure_ascii=False), encoding="utf-8")


def _load_reminders() -> list[dict]:
    data = _load_json(REMINDERS_FILE, [])
    return data if isinstance(data, list) else []


def _save_reminders(items: list[dict]) -> None:
    _save_json(REMINDERS_FILE, items)


def _load_state() -> dict:
    data = _load_json(STATE_FILE, {})
    return data if isinstance(data, dict) else {}


def _save_state(state: dict) -> None:
    _save_json(STATE_FILE, state)


def _user_idle_seconds() -> float | None:
    try:
        from arka.core.usage import user_idle_seconds

        return user_idle_seconds()
    except ImportError:
        pass
    if sys.platform == "darwin" and shutil.which("ioreg"):
        try:
            proc = subprocess.run(
                ["ioreg", "-c", "IOHIDSystem", "-d", "4"],
                capture_output=True,
                text=True,
                timeout=3,
            )
            m = re.search(r'"HIDIdleTime"\s*=\s*(\d+)', proc.stdout or "")
            if m:
                return int(m.group(1)) / 1_000_000_000.0
        except (subprocess.TimeoutExpired, ValueError, OSError):
            pass
    return None


def _user_is_active() -> bool:
    idle = _user_idle_seconds()
    if idle is None:
        return True
    return idle < ACTIVE_SEC


def _user_is_idle() -> bool:
    idle = _user_idle_seconds()
    if idle is None:
        return False
    return idle >= IDLE_SEC


def _notify(title: str, body: str) -> None:
    body = body.strip()
    print(f"\n⏰ {title}: {body}", flush=True)
    sys.stdout.write("\a")
    sys.stdout.flush()
    if sys.platform == "darwin" and shutil.which("osascript"):
        esc = lambda s: s.replace("\\", "\\\\").replace('"', '\\"')
        subprocess.run(
            [
                "osascript",
                "-e",
                f'display notification "{esc(body)}" with title "{esc(title)}" sound name "Glass"',
            ],
            capture_output=True,
            timeout=5,
        )
    elif shutil.which("notify-send"):
        subprocess.run(
            ["notify-send", "-a", "Arka", "-u", "normal", "-t", "10000", title, body],
            capture_output=True,
            timeout=5,
        )
    if os.environ.get("ARKA_REMIND_SPEAK", "").strip().lower() in {"1", "true", "yes"}:
        try:
            subprocess.Popen(
                [sys.executable, str(Path(__file__).resolve().parent / "edge_speak.py"), body[:200]],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except OSError:
            pass


def _fire(rem: dict, *, kind: str) -> None:
    label = "Reminder" if kind == "at_time" else "Reminder (you're back)"
    _notify(label, str(rem.get("text") or ""))
    log = LOG_FILE
    log.parent.mkdir(parents=True, exist_ok=True)
    with log.open("a", encoding="utf-8") as fh:
        fh.write(f"{datetime.now().isoformat(timespec='seconds')} [{kind}] {rem.get('id')} {rem.get('text')!r}\n")


def _is_done(rem: dict) -> bool:
    if rem.get("cancelled"):
        return True
    if not rem.get("at_time_fired"):
        return False
    if rem.get("pending_active") and not rem.get("on_active_fired"):
        return False
    return True


def _parse_clock(token: str, base: datetime) -> datetime | None:
    t = token.strip().lower().replace(".", "")
    if t in {"noon", "12pm"}:
        return base.replace(hour=12, minute=0, second=0, microsecond=0)
    if t in {"midnight", "12am"}:
        d = base + timedelta(days=1)
        return d.replace(hour=0, minute=0, second=0, microsecond=0)
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t)
    if not m:
        return None
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    mer = m.group(3)
    if mer == "pm" and hour < 12:
        hour += 12
    if mer == "am" and hour == 12:
        hour = 0
    if mer is None and hour < 8:
        hour += 12
    dt = base.replace(hour=hour, minute=minute, second=0, microsecond=0)
    if dt <= base and mer is None:
        dt += timedelta(days=1)
    return dt


def _parse_default_in_spec() -> str | None:
    spec = os.environ.get("ARKA_REMIND_DEFAULT", "1h").strip().lower()
    if spec in ("0", "off", "false", "no", "none"):
        return None
    return spec or None


def _task_message(text: str) -> str:
    msg = text.strip()
    msg = re.sub(r"^(?:to|that)\s+", "", msg, flags=re.I).strip()
    msg = re.sub(r"^(?:remind(?:\s+me)?|me)\s+", "", msg, flags=re.I).strip()
    return msg


def _parse_due(
    text: str, *, at: str | None = None, in_spec: str | None = None
) -> tuple[int, str, bool]:
    now = datetime.now()
    msg = text.strip()
    used_default = False

    if at:
        try:
            if re.fullmatch(r"\d{10,}", at.strip()):
                due = datetime.fromtimestamp(int(at.strip()))
            else:
                due = datetime.fromisoformat(at.strip())
            return int(due.timestamp()), msg or "Reminder", used_default
        except ValueError as exc:
            raise SystemExit(f"Invalid --at time: {at!r} ({exc})") from exc

    if in_spec:
        m = re.fullmatch(
            r"(\d+)\s*(s|sec|secs|seconds?|m|min|mins|minutes?|h|hr|hrs|hours?|d|days?)",
            in_spec.strip().lower(),
        )
        if not m:
            raise SystemExit(f"Invalid --in duration: {in_spec!r} (use 30m, 2h, 1d)")
        n, unit = int(m.group(1)), m.group(2)[0]
        mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}[unit]
        due = now + timedelta(seconds=n * mult)
        return int(due.timestamp()), msg or "Reminder", used_default

    patterns: list[tuple[str, str]] = [
        (r"\bin\s+(\d+)\s*(seconds?|secs?|s)\b", "s"),
        (r"\bin\s+(\d+)\s*(minutes?|mins?|m)\b", "m"),
        (r"\bin\s+(\d+)\s*(hours?|hrs?|h)\b", "h"),
        (r"\bin\s+(\d+)\s*(days?|d)\b", "d"),
        (r"\btomorrow\s+(?:at\s+)?(\d{1,2}(?::\d{2})?\s*(?:am|pm)?|noon|midnight)\b", "tomorrow"),
        (r"\bat\s+(\d{1,2}(?::\d{2})?\s*(?:am|pm)?|noon|midnight)\b", "at"),
    ]

    due: datetime | None = None
    matched = ""
    for pat, kind in patterns:
        m = re.search(pat, msg, re.I)
        if not m:
            continue
        matched = m.group(0)
        if kind in {"s", "m", "h", "d"}:
            n = int(m.group(1))
            mult = {"s": 1, "m": 60, "h": 3600, "d": 86400}[kind]
            due = now + timedelta(seconds=n * mult)
        elif kind == "tomorrow":
            base = (now + timedelta(days=1)).replace(hour=0, minute=0, second=0, microsecond=0)
            due = _parse_clock(m.group(1), base)
        else:
            due = _parse_clock(m.group(1), now)
            if due and due <= now:
                due += timedelta(days=1)
        break

    if due is None:
        default_in = _parse_default_in_spec()
        task = _task_message(msg)
        if default_in and task:
            due_ts, message, _ = _parse_due(task, in_spec=default_in)
            return due_ts, message, True
        raise SystemExit(
            "Could not parse when to remind. Examples:\n"
            "  remind to go to gym          (default delay: 1h — set ARKA_REMIND_DEFAULT=30m)\n"
            "  remind in 30m stretch\n"
            "  remind at 5pm call mom\n"
            "  remind tomorrow 9am standup\n"
            "  remind add --in 2h take medicine"
        )

    clean = re.sub(re.escape(matched), "", msg, count=1, flags=re.I).strip()
    clean = _task_message(clean)
    if not clean:
        clean = "Reminder"
    return int(due.timestamp()), clean, used_default


def _normalize_add_argv(argv: list[str]) -> str:
    """Natural language: 'me in 1 min stretch' -> 'in 1 min stretch'."""
    text = " ".join(argv).strip()
    return re.sub(r"^(?:please\s+)?(?:remind(?:\s+me)?|me)\s+", "", text, flags=re.I).strip()


def _add_reminder(text: str, *, at: str | None = None, in_spec: str | None = None) -> tuple[dict, bool]:
    due_at, message, used_default = _parse_due(text, at=at, in_spec=in_spec)
    rem = {
        "id": uuid.uuid4().hex[:8],
        "text": message,
        "due_at": due_at,
        "created_at": int(time.time()),
        "at_time_fired": False,
        "on_active_fired": False,
        "pending_active": False,
        "cancelled": False,
    }
    items = _load_reminders()
    items.append(rem)
    _save_reminders(items)
    return rem, used_default


def _format_rem(rem: dict) -> str:
    due = datetime.fromtimestamp(int(rem["due_at"])).strftime("%Y-%m-%d %H:%M")
    flags = []
    if rem.get("cancelled"):
        flags.append("cancelled")
    elif _is_done(rem):
        flags.append("done")
    elif rem.get("pending_active"):
        flags.append("waiting for you")
    elif rem.get("at_time_fired"):
        flags.append("partial")
    else:
        flags.append("pending")
    state = ", ".join(flags)
    return f"{rem.get('id')}  {due}  [{state}]  {rem.get('text')}"


def _pc_was_off(last_tick: float, now: float, due_at: float) -> bool:
    if last_tick <= 0:
        return False
    gap = now - last_tick
    if gap <= GAP_SEC:
        return False
    return last_tick < due_at <= now


def tick(*, quiet: bool = False) -> int:
    now = time.time()
    state = _load_state()
    last_tick = float(state.get("last_tick") or 0)
    items = _load_reminders()
    changed = False

    for rem in items:
        if _is_done(rem):
            continue
        due_at = float(rem.get("due_at") or 0)
        if due_at > now:
            continue

        if not rem.get("at_time_fired"):
            if _pc_was_off(last_tick, now, due_at):
                rem["at_time_fired"] = True
                rem["pending_active"] = True
                changed = True
            else:
                _fire(rem, kind="at_time")
                rem["at_time_fired"] = True
                if _user_is_idle():
                    rem["pending_active"] = True
                changed = True

        if rem.get("pending_active") and not rem.get("on_active_fired") and _user_is_active():
            _fire(rem, kind="on_active")
            rem["on_active_fired"] = True
            rem["pending_active"] = False
            changed = True

    if changed:
        _save_reminders(items)

    state["last_tick"] = now
    if not state.get("daemon_started_at"):
        state["daemon_started_at"] = now
    _save_state(state)

    if not quiet:
        pending = sum(1 for r in items if not _is_done(r))
        if pending:
            print(f"{pending} reminder(s) pending.", file=sys.stderr)
    return 0


def _write_pid() -> None:
    PID_FILE.parent.mkdir(parents=True, exist_ok=True)
    PID_FILE.write_text(str(os.getpid()), encoding="utf-8")


def _remove_pid() -> None:
    PID_FILE.unlink(missing_ok=True)


def daemon_loop() -> None:
    signal.signal(signal.SIGTERM, lambda *_: sys.exit(0))
    signal.signal(signal.SIGINT, lambda *_: sys.exit(0))
    _write_pid()
    try:
        while True:
            tick(quiet=True)
            time.sleep(TICK_SEC)
    finally:
        _remove_pid()


def start_daemon() -> int:
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)
            print(f"Reminder daemon already running (pid {pid}).", file=sys.stderr)
            return 0
        except (OSError, ValueError):
            PID_FILE.unlink(missing_ok=True)

    CACHE.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("ab") as fh:
        subprocess.Popen(
            [sys.executable, str(Path(__file__).resolve()), "daemon"],
            stdout=fh,
            stderr=fh,
            start_new_session=True,
        )
    time.sleep(0.3)
    if PID_FILE.exists():
        print(f"Reminder daemon started (pid {PID_FILE.read_text().strip()}).", file=sys.stderr)
    else:
        print("Reminder daemon started.", file=sys.stderr)
    return 0


def stop_daemon() -> int:
    if not PID_FILE.exists():
        print("Reminder daemon not running.", file=sys.stderr)
        return 0
    try:
        pid = int(PID_FILE.read_text().strip())
        os.kill(pid, signal.SIGTERM)
    except (OSError, ValueError):
        pass
    PID_FILE.unlink(missing_ok=True)
    print("Reminder daemon stopped.", file=sys.stderr)
    return 0


def cmd_status(_args: argparse.Namespace) -> int:
    running = False
    pid = None
    if PID_FILE.exists():
        try:
            pid = int(PID_FILE.read_text().strip())
            os.kill(pid, 0)
            running = True
        except (OSError, ValueError):
            PID_FILE.unlink(missing_ok=True)
    items = _load_reminders()
    pending = [r for r in items if not _is_done(r)]
    print("Arka remind")
    print(f"  Daemon:   {'running (pid ' + str(pid) + ')' if running else 'stopped'}")
    print(f"  Pending:  {len(pending)}")
    print(f"  Store:    {REMINDERS_FILE}")
    if pending:
        print("")
        for rem in pending[:10]:
            print(f"  {_format_rem(rem)}")
    return 0


def cmd_add(args: argparse.Namespace) -> int:
    text = " ".join(args.message).strip() if args.message else ""
    text = _normalize_add_argv(text.split()) if text else ""
    if not text and not args.at and not args.in_spec:
        raise SystemExit("Usage: remind add [--in 30m | --at TIME] <message>")
    rem, used_default = _add_reminder(text, at=args.at, in_spec=args.in_spec)
    due = datetime.fromtimestamp(rem["due_at"]).strftime("%Y-%m-%d %H:%M")
    print(f"✓ Reminder set for {due} — {rem['text']} (id {rem['id']})")
    if used_default:
        default_in = _parse_default_in_spec() or "1h"
        print(
            f"  (no time given — used default delay {default_in}; "
            f"override with 'in 30m …' or ARKA_REMIND_DEFAULT=30m)",
            file=sys.stderr,
        )
    start_daemon()
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    items = sorted(_load_reminders(), key=lambda r: int(r.get("due_at") or 0))
    if not items:
        print("No reminders.")
        return 0
    for rem in items:
        print(_format_rem(rem))
    return 0


def cmd_cancel(args: argparse.Namespace) -> int:
    rid = args.id.strip().lower()
    items = _load_reminders()
    found = False
    for rem in items:
        if str(rem.get("id", "")).lower().startswith(rid):
            rem["cancelled"] = True
            found = True
            print(f"Cancelled {rem.get('id')} — {rem.get('text')}")
    if not found:
        raise SystemExit(f"No reminder matching id {rid!r}")
    _save_reminders(items)
    return 0


def main() -> int:
    argv = sys.argv[1:]
    if argv and argv[0] not in _KNOWN_CMDS and argv[0] not in ("-h", "--help"):
        text = _normalize_add_argv(argv)
        return cmd_add(argparse.Namespace(message=[text], at=None, in_spec=None))

    parser = argparse.ArgumentParser(
        description="Schedule reminders — fires at due time; again when you're back after idle or shutdown.",
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("daemon", help=argparse.SUPPRESS).set_defaults(func=lambda _: daemon_loop() or 0)

    p_add = sub.add_parser("add", help="Create a reminder (default command)")
    p_add.add_argument("message", nargs="*", help="e.g. 'in 30m stretch' or 'at 5pm call mom'")
    p_add.add_argument("--at", dest="at", default=None, help="ISO datetime or unix timestamp")
    p_add.add_argument("--in", dest="in_spec", default=None, help="Duration: 30m, 2h, 1d")
    p_add.set_defaults(func=cmd_add)

    sub.add_parser("list", help="List reminders").set_defaults(func=cmd_list)
    sub.add_parser("status", help="Daemon + pending reminders").set_defaults(func=cmd_status)
    sub.add_parser("start", help="Start background daemon").set_defaults(func=lambda _: start_daemon())
    sub.add_parser("stop", help="Stop background daemon").set_defaults(func=lambda _: stop_daemon())
    p_check = sub.add_parser("check", help="Process due reminders once (shell hook)")
    p_check.add_argument("--quiet", action="store_true")
    p_check.set_defaults(func=lambda a: tick(quiet=a.quiet))

    p_cancel = sub.add_parser("cancel", help="Cancel reminder by id prefix")
    p_cancel.add_argument("id")
    p_cancel.set_defaults(func=cmd_cancel)

    args = parser.parse_args()
    if args.cmd is None:
        if len(sys.argv) > 1 and sys.argv[1] not in ("-h", "--help"):
            text = _normalize_add_argv(sys.argv[1:])
            return cmd_add(argparse.Namespace(message=[text], at=None, in_spec=None))
        parser.print_help()
        return 0
    if args.cmd == "daemon":
        daemon_loop()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
