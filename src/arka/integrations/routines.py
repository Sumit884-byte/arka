#!/usr/bin/env python3
"""Arka routines — schedule any task to run daily (or hourly) via launchd/systemd."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import time
from pathlib import Path

try:
    from arka.paths import cache_dir, fish_config
except ImportError:
    cache_dir = lambda: Path.home() / ".cache" / "fish-agent"  # noqa: E731
    fish_config = lambda: Path.home() / ".config" / "fish"  # noqa: E731

CACHE = cache_dir()
ROUTINE_FILE = CACHE / "routines.json"
FISH_DIR = fish_config()
LOG_FILE = CACHE / "arka_routines.log"

_KNOWN_CMDS = frozenset({"add", "list", "install", "remove", "run", "parse", "help", "enable", "disable"})


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


def _fish() -> str:
    return shutil.which("fish") or "/usr/bin/fish"


def _routines_security_enabled() -> bool:
    return os.environ.get("ROUTINES_SECURITY", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _security_gate_action(action: str) -> bool:
    """Cron runs are non-interactive — block confirm/block actions (OpenClaw safety)."""
    if not _routines_security_enabled():
        return True
    try:
        from arka.core.security import check_action
    except ImportError:
        return True
    result = check_action(action.strip())
    if result.status == "block":
        print(f"Routine blocked: {result.reason}", file=sys.stderr)
        return False
    if result.status == "confirm":
        print(
            f"Routine skipped (needs confirm, non-interactive): {result.reason}",
            file=sys.stderr,
        )
        return False
    return True


def _normalize_time(token: str) -> str:
    t = token.strip().lower().replace(".", "")
    if t in {"noon", "12pm"}:
        return "12:00"
    if t in {"midnight", "12am"}:
        return "00:00"
    m = re.fullmatch(r"(\d{1,2})(?::(\d{2}))?\s*(am|pm)?", t)
    if not m:
        return t
    hour = int(m.group(1))
    minute = int(m.group(2) or 0)
    mer = m.group(3)
    if mer == "pm" and hour < 12:
        hour += 12
    if mer == "am" and hour == 12:
        hour = 0
    if mer is None and hour <= 12 and hour < 8:
        hour += 12
    return f"{hour:02d}:{minute:02d}"


def parse_schedule(text: str) -> str:
    t = text.lower()
    if re.search(r"\b(?:hourly|every\s+hour|each\s+hour)\b", t):
        return "hourly"
    m = re.search(r"(?:\bat|@)\s*(\d{1,2}(?::\d{2})?\s*(?:am|pm)?)", t, re.I)
    if m:
        return _normalize_time(m.group(1))
    if re.search(r"\b(?:every\s+morning|each\s+morning|morning)\b", t):
        return os.environ.get("ROUTINES_MORNING", "09:00")
    if re.search(r"\b(?:every\s+evening|each\s+evening|evening)\b", t):
        return os.environ.get("ROUTINES_EVENING", "18:00")
    if re.search(r"\b(?:daily|every\s+day|each\s+day|everyday)\b", t):
        return os.environ.get("ROUTINES_DAILY", "09:00")
    return os.environ.get("ROUTINES_DAILY", "09:00")


def _strip_schedule_words(text: str) -> str:
    t = text.strip()
    t = re.sub(
        r"(?i)^(?:please\s+)?(?:add\s+)?(?:a\s+)?(?:new\s+)?(?:arka\s+)?(?:routine\s+)?",
        "",
        t,
    )
    t = re.sub(
        r"(?i)\b(?:every\s+day|each\s+day|everyday)\b",
        " ",
        t,
    )
    t = re.sub(r"(?i)\bdaily\b(?!\s+brief)", " ", t)
    t = re.sub(
        r"(?i)\b(?:hourly|every\s+hour|each\s+hour|every\s+morning|each\s+morning|"
        r"every\s+evening|each\s+evening)\b",
        " ",
        t,
    )
    t = re.sub(r"(?i)(?:\bat|@)\s*\d{1,2}(?::\d{2})?\s*(?:am|pm)?", " ", t)
    t = re.sub(r"(?i)^(?:to\s+|for\s+|run\s+|do\s+|that\s+)", "", t)
    return re.sub(r"\s+", " ", t).strip()


def normalize_action(task: str) -> str:
    t = _strip_schedule_words(task)
    if not t:
        return ""
    low = t.lower()
    if re.search(
        r"(?i)\b("
        r"(?:daily|morning|news)\s+brief|"
        r"today['']?s\s+(?:tech\s+)?brief|"
        r"(?:daily|morning|news|today['']?s)\s+tech\s+brief|"
        r"tech\s+brief(?:\s+(?:personalized(?:\s+for\s+me)?|for\s+me))?|"
        r"personalized\s+(?:tech\s+)?brief"
        r")\b",
        low,
    ):
        return "daily_brief"
    if low in {"daily brief", "morning brief", "news brief", "today's brief"}:
        return "daily_brief"
    if re.match(
        r"(?i)^(agent|daily_brief|chart|give|google|remind|weather|wifi_info|"
        r"sports_score|system_monitor|summarize|play_|generate_)\b",
        t,
    ):
        return t
    return f"agent {shlex.quote(t)}"


def nl_to_argv(text: str) -> list[str]:
    raw = text.strip()
    if not raw:
        return []
    low = raw.lower()

    if re.search(r"\b(?:list|show|my)\s+(?:arka\s+)?routines?\b", low) or low in {
        "routines",
        "routines list",
        "list routines",
        "my routines",
    }:
        return ["list"]

    m = re.search(r"\b(?:remove|delete|cancel|stop|disable)\s+(?:routine\s+)?(\S+)", raw, re.I)
    if m:
        return ["remove", m.group(1)]

    if re.search(r"\b(?:install|enable|activate)\s+(?:my\s+)?(?:arka\s+)?routines?\b", low):
        return ["install"]

    if not re.search(
        r"(?i)\b(?:routine|routines|every\s+day|each\s+day|everyday|daily\s+at|"
        r"every\s+morning|every\s+evening|every\s+hour|schedule\s+daily)\b",
        raw,
    ):
        return []

    if re.search(r"(?i)\bremind(?:\s+me)?\b", raw):
        return []

    schedule = parse_schedule(raw)
    action = normalize_action(raw)
    if not action:
        return []
    return ["add", schedule, action]


def routine_add(schedule: str, action: str, *, name: str = "", auto_install: bool = False) -> str:
    routines = _load_json(ROUTINE_FILE, [])
    if not isinstance(routines, list):
        routines = []
    rid = name.strip() or hashlib.sha256(f"{schedule}{action}".encode()).hexdigest()[:8]
    entry = {
        "id": rid,
        "schedule": schedule.strip(),
        "action": action.strip(),
        "enabled": True,
        "created": time.time(),
    }
    routines = [r for r in routines if r.get("id") != rid]
    routines.append(entry)
    _save_json(ROUTINE_FILE, routines)
    print(f"Routine {rid}: {schedule} → {action}")
    if auto_install or os.environ.get("ROUTINES_AUTO_INSTALL", "").strip().lower() in {
        "1",
        "true",
        "yes",
    }:
        _install_one(entry)
    else:
        print("Install scheduler: routines install")
    return rid


def list_routines(*, enabled_only: bool = False) -> list[dict]:
    """Return scheduled routines as structured rows (OpenClaw always-on layer)."""
    routines = _load_json(ROUTINE_FILE, [])
    if not isinstance(routines, list):
        return []
    out: list[dict] = []
    for r in routines:
        if not isinstance(r, dict):
            continue
        enabled = bool(r.get("enabled", True))
        if enabled_only and not enabled:
            continue
        out.append(
            {
                "id": str(r.get("id") or ""),
                "schedule": str(r.get("schedule") or ""),
                "action": str(r.get("action") or ""),
                "enabled": enabled,
                "created": r.get("created"),
            }
        )
    return out


def routine_list() -> None:
    routines = list_routines()
    if not routines:
        print("No routines. Add one with:")
        print('  routines add daily 9am "check unread emails"')
        print('  arka every day at 9am summarize my gmail')
        return
    for r in routines:
        en = "on" if r.get("enabled", True) else "off"
        print(f"[{en}] {r.get('id', '?')}  {r.get('schedule', '')} → {r.get('action', '')}")


def routine_remove(rid: str) -> None:
    routines = _load_json(ROUTINE_FILE, [])
    if isinstance(routines, list):
        kept = [r for r in routines if r.get("id") != rid]
        _save_json(ROUTINE_FILE, kept)
        if len(kept) < len(routines):
            _uninstall_one(rid)
            print(f"Removed routine {rid}.")
            return
    print(f"No routine {rid}.")


def routine_set_enabled(rid: str, enabled: bool) -> dict | None:
    """Pause or resume a routine without deleting it (OpenClaw always-on toggle)."""
    routines = _load_json(ROUTINE_FILE, [])
    if not isinstance(routines, list):
        return None
    match: dict | None = None
    for r in routines:
        if isinstance(r, dict) and r.get("id") == rid:
            r["enabled"] = bool(enabled)
            match = r
            break
    if match is None:
        return None
    _save_json(ROUTINE_FILE, routines)
    if enabled:
        try:
            _install_one(match)
        except Exception:
            pass
    else:
        try:
            _uninstall_one(rid)
        except Exception:
            pass
    return {
        "id": str(match.get("id") or rid),
        "schedule": str(match.get("schedule") or ""),
        "action": str(match.get("action") or ""),
        "enabled": bool(match.get("enabled", True)),
        "created": match.get("created"),
    }


def routine_run(rid: str) -> int:
    routines = _load_json(ROUTINE_FILE, [])
    if not isinstance(routines, list):
        print(f"No routine {rid}.", file=sys.stderr)
        return 1
    match = next((r for r in routines if r.get("id") == rid), None)
    if not match:
        print(f"No routine {rid}.", file=sys.stderr)
        return 1
    action = str(match.get("action") or "")
    print(f"Running routine {rid}: {action}")
    return _run_action(action)


def _run_action(action: str) -> int:
    if not _security_gate_action(action):
        LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
        with LOG_FILE.open("a", encoding="utf-8") as fh:
            fh.write(
                f"{time.strftime('%Y-%m-%d %H:%M:%S')} skipped {action!r} (security gate)\n"
            )
        return 2
    fish = _fish()
    env = os.environ.copy()
    env.setdefault("FISH_DIR", str(FISH_DIR))
    proc = subprocess.run(
        [fish, "-ic", action],
        env=env,
        cwd=str(Path.home()),
    )
    try:
        from arka.integrations.heartbeat import ping

        ping(f"routine.run", source="routines")
    except ImportError:
        pass
    LOG_FILE.parent.mkdir(parents=True, exist_ok=True)
    with LOG_FILE.open("a", encoding="utf-8") as fh:
        fh.write(
            f"{time.strftime('%Y-%m-%d %H:%M:%S')} run {action!r} exit={proc.returncode}\n"
        )
    return int(proc.returncode or 0)


def _systemctl(*args: str) -> None:
    if not shutil.which("systemctl"):
        return
    subprocess.run(["systemctl", *args], check=False)


def _launchctl(*args: str) -> None:
    if not shutil.which("launchctl"):
        return
    subprocess.run(["launchctl", *args], check=False)


def _calendar_spec(schedule: str) -> str:
    sched = (schedule or "daily").lower().strip()
    if sched == "hourly":
        return "hourly"
    if sched == "daily":
        return "daily"
    if re.fullmatch(r"\d{1,2}:\d{2}", sched):
        hour, minute = sched.split(":", 1)
        return f"*-*-* {int(hour):02d}:{minute}:00"
    return "daily"


def _install_systemd(entry: dict) -> None:
    rid = str(entry.get("id") or "routine")
    sched = str(entry.get("schedule") or "daily")
    action = str(entry.get("action") or "")
    unit_dir = Path.home() / ".config/systemd/user"
    unit_dir.mkdir(parents=True, exist_ok=True)
    service = unit_dir / f"arka-routine-{rid}.service"
    timer = unit_dir / f"arka-routine-{rid}.timer"
    fish = _fish()
    service.write_text(
        f"[Unit]\nDescription=Arka routine {rid}\n\n"
        f"[Service]\nType=oneshot\n"
        f"ExecStart={fish} -ic {shlex.quote(action)}\n"
        f"Environment=FISH_DIR={FISH_DIR}\n",
        encoding="utf-8",
    )
    on_calendar = _calendar_spec(sched)
    timer.write_text(
        f"[Unit]\nDescription=Arka routine timer {rid}\n\n"
        f"[Timer]\nOnCalendar={on_calendar}\nPersistent=true\n\n"
        f"[Install]\nWantedBy=timers.target\n",
        encoding="utf-8",
    )
    _systemctl("--user", "daemon-reload")
    _systemctl("--user", "enable", "--now", f"arka-routine-{rid}.timer")
    print(f"Installed systemd timer arka-routine-{rid}.timer ({on_calendar})")


def _install_launchd(entry: dict) -> None:
    rid = str(entry.get("id") or "routine")
    sched = str(entry.get("schedule") or "daily").lower()
    action = str(entry.get("action") or "")
    label = f"com.arka.routine.{rid}"
    plist = Path.home() / "Library/LaunchAgents" / f"{label}.plist"
    plist.parent.mkdir(parents=True, exist_ok=True)
    fish = _fish()
    args = [fish, "-ic", action]
    lines = [
        '<?xml version="1.0" encoding="UTF-8"?>',
        '<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" '
        '"http://www.apple.com/DTDs/PropertyList-1.0.dtd">',
        "<plist version=\"1.0\">",
        "<dict>",
        f"  <key>Label</key><string>{label}</string>",
        "  <key>ProgramArguments</key>",
        "  <array>",
    ]
    for arg in args:
        lines.append(f"    <string>{arg.replace('&', '&amp;').replace('<', '&lt;')}</string>")
    lines.extend(
        [
            "  </array>",
            f"  <key>StandardOutPath</key><string>{LOG_FILE}</string>",
            f"  <key>StandardErrorPath</key><string>{LOG_FILE}</string>",
        ]
    )
    if sched == "hourly":
        lines.extend(["  <key>StartInterval</key><integer>3600</integer>"])
    else:
        if re.fullmatch(r"\d{1,2}:\d{2}", sched):
            hour, minute = sched.split(":", 1)
        elif sched == "daily":
            hour, minute = "09", "00"
        else:
            hour, minute = "09", "00"
        lines.extend(
            [
                "  <key>StartCalendarInterval</key>",
                "  <dict>",
                f"    <key>Hour</key><integer>{int(hour)}</integer>",
                f"    <key>Minute</key><integer>{int(minute)}</integer>",
                "  </dict>",
            ]
        )
    lines.extend(["</dict>", "</plist>"])
    plist.write_text("\n".join(lines) + "\n", encoding="utf-8")
    uid = os.getuid()
    _launchctl("bootout", f"gui/{uid}", str(plist))
    proc = subprocess.run(["launchctl", "bootstrap", f"gui/{uid}", str(plist)], check=False)
    if proc.returncode != 0:
        _launchctl("load", str(plist))
    when = "hourly" if sched == "hourly" else f"daily at {sched}"
    print(f"Installed launchd agent {label} ({when})")


def _install_one(entry: dict) -> None:
    if sys.platform == "darwin":
        _install_launchd(entry)
    elif shutil.which("systemctl"):
        _install_systemd(entry)
    else:
        print("Saved routine. Install launchd/systemd timers with: routines install")


def _uninstall_one(rid: str) -> None:
    if sys.platform == "darwin":
        label = f"com.arka.routine.{rid}"
        plist = Path.home() / "Library/LaunchAgents" / f"{label}.plist"
        uid = os.getuid()
        _launchctl("bootout", f"gui/{uid}", str(plist))
        plist.unlink(missing_ok=True)
    if shutil.which("systemctl"):
        _systemctl("--user", "disable", "--now", f"arka-routine-{rid}.timer")
        unit_dir = Path.home() / ".config/systemd/user"
        for p in unit_dir.glob(f"arka-routine-{rid}.*"):
            p.unlink(missing_ok=True)
        _systemctl("--user", "daemon-reload")


def routine_install() -> None:
    routines = _load_json(ROUTINE_FILE, [])
    if not isinstance(routines, list) or not routines:
        print("No routines to install.")
        return
    installed = 0
    for entry in routines:
        if not entry.get("enabled", True):
            continue
        _install_one(entry)
        installed += 1
    if installed == 0:
        print("No enabled routines.")
    elif sys.platform not in ("darwin", "linux") and not shutil.which("systemctl"):
        print("Timers require macOS (launchd) or Linux (systemd user timers).")


def cmd_add(args: argparse.Namespace) -> int:
    schedule = args.schedule
    action = " ".join(args.action).strip()
    if not action:
        print("Usage: routines add daily|hourly|HH:MM \"task command\"", file=sys.stderr)
        return 1
    if schedule.lower() not in {"daily", "hourly"} and not re.fullmatch(
        r"\d{1,2}:\d{2}", schedule
    ):
        schedule = _normalize_time(schedule) if ":" not in schedule else schedule
    action = normalize_action(action) if not re.match(
        r"(?i)^(agent|daily_brief|chart|give|google)\b", action
    ) else action
    routine_add(schedule, action, name=args.name or "", auto_install=args.install)
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    routine_list()
    return 0


def cmd_install(_args: argparse.Namespace) -> int:
    routine_install()
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    routine_remove(args.id)
    return 0


def cmd_enable(args: argparse.Namespace) -> int:
    row = routine_set_enabled(args.id, True)
    if not row:
        print(f"No routine {args.id}.", file=sys.stderr)
        return 1
    print(f"Enabled routine {row['id']}.")
    return 0


def cmd_disable(args: argparse.Namespace) -> int:
    row = routine_set_enabled(args.id, False)
    if not row:
        print(f"No routine {args.id}.", file=sys.stderr)
        return 1
    print(f"Disabled routine {row['id']}.")
    return 0


def cmd_run(args: argparse.Namespace) -> int:
    return routine_run(args.id)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Schedule daily tasks — run any Arka command on a timer"
    )
    sub = p.add_subparsers(dest="cmd")

    p_add = sub.add_parser("add", help="Add a recurring routine")
    p_add.add_argument("schedule", help="daily, hourly, or HH:MM (e.g. 09:00, 9am)")
    p_add.add_argument("action", nargs="+", help="Task to run (quoted natural language OK)")
    p_add.add_argument("--name", default="", help="Optional routine id")
    p_add.add_argument(
        "--install",
        action="store_true",
        help="Install launchd/systemd timer immediately",
    )
    p_add.set_defaults(func=cmd_add)

    sub.add_parser("list", help="List saved routines").set_defaults(func=cmd_list)
    sub.add_parser("install", help="Install all routines as timers").set_defaults(func=cmd_install)

    p_rm = sub.add_parser("remove", help="Remove a routine by id")
    p_rm.add_argument("id")
    p_rm.set_defaults(func=cmd_remove)

    p_en = sub.add_parser("enable", help="Re-enable a paused routine")
    p_en.add_argument("id")
    p_en.set_defaults(func=cmd_enable)

    p_dis = sub.add_parser("disable", help="Pause a routine without deleting it")
    p_dis.add_argument("id")
    p_dis.set_defaults(func=cmd_disable)

    p_run = sub.add_parser("run", help="Run a routine once now (test)")
    p_run.add_argument("id")
    p_run.set_defaults(func=cmd_run)

    p_parse = sub.add_parser("parse", help="Parse natural language → routines args (internal)")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)

    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        build_parser().print_help()
        return 0
    if argv[0] not in _KNOWN_CMDS:
        nl = nl_to_argv(" ".join(argv))
        if nl:
            argv = nl
        else:
            print("Could not parse routine request. Try:", file=sys.stderr)
            print('  routines add daily 9am "check unread emails"', file=sys.stderr)
            print('  arka every day at 9am summarize my gmail', file=sys.stderr)
            print("  routines list", file=sys.stderr)
            return 1
    parser = build_parser()
    args = parser.parse_args(argv)
    func = getattr(args, "func", None)
    if not func:
        parser.print_help()
        return 0
    return int(func(args))


if __name__ == "__main__":
    raise SystemExit(main())
