#!/usr/bin/env python3
"""Artificial Internet Enhancements (AIE) — orchestrate background internet/desktop automations."""

from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time
from pathlib import Path

AUTOMATION_DIR = Path.home() / "Projects/python/products/automation"
CACHE_DIR = Path.home() / ".cache/fish-agent/aie"

ENHANCERS: dict[str, dict[str, str]] = {
    "click": {
        "script": "auto_click.py",
        "label": "Auto-click when cursor shape changes (loading spinners)",
    },
    "copy": {
        "script": "auto_copy_selection.py",
        "label": "Auto-copy text selection to clipboard on paste",
    },
    "zip": {
        "script": "zip_open.py",
        "label": "Watch folders and auto-extract new zip archives",
    },
    "classify": {
        "script": "classifier.py",
        "label": "Auto-sort new files by type (docs, images, code)",
    },
}

ONE_SHOT: dict[str, dict[str, str]] = {
    "cleanup": {
        "script": "delete_useless.py",
        "label": "Remove installer junk (.zip, .deb, .tar.gz) from Downloads",
    },
}


def _python() -> str:
    venv = Path.home() / ".config/fish/venv-arka/bin/python3"
    if venv.is_file():
        return str(venv)
    return sys.executable


def _script_path(name: str, catalog: dict[str, dict[str, str]]) -> Path | None:
    entry = catalog.get(name)
    if not entry:
        return None
    path = AUTOMATION_DIR / entry["script"]
    return path if path.is_file() else None


def _pid_path(name: str) -> Path:
    return CACHE_DIR / f"{name}.pid"


def _log_path(name: str) -> Path:
    return CACHE_DIR / f"{name}.log"


def _read_pid(name: str) -> int | None:
    path = _pid_path(name)
    if not path.is_file():
        return None
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        return None
    if pid > 0 and _process_alive(pid):
        return pid
    path.unlink(missing_ok=True)
    return None


def _process_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def cmd_status(_args: argparse.Namespace) -> int:
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    print("━━━ Artificial Internet Enhancements (AIE) ━━━")
    print(f"Automation dir: {AUTOMATION_DIR}")
    print("")
    print("Background enhancers:")
    for key, meta in ENHANCERS.items():
        script = _script_path(key, ENHANCERS)
        pid = _read_pid(key)
        if pid:
            state = f"running (pid {pid})"
        elif script:
            state = "stopped"
        else:
            state = f"missing script ({meta['script']})"
        print(f"  {key:8} {state:22} — {meta['label']}")
    print("")
    print("One-shot tasks:")
    for key, meta in ONE_SHOT.items():
        script = _script_path(key, ONE_SHOT)
        ok = "ready" if script else "missing"
        print(f"  {key:8} {ok:22} — {meta['label']}")
    print("")
    print("Usage: internet_enhance start [all|click|copy|zip|classify]")
    print("       internet_enhance stop [all|...]  |  internet_enhance cleanup")
    return 0


def _start_one(name: str) -> bool:
    script = _script_path(name, ENHANCERS)
    if not script:
        print(f"aie: script not found for '{name}'", file=sys.stderr)
        return False
    if _read_pid(name):
        print(f"aie: {name} already running")
        return True
    CACHE_DIR.mkdir(parents=True, exist_ok=True)
    log = _log_path(name)
    with open(log, "ab") as fh:
        proc = subprocess.Popen(
            [_python(), str(script)],
            cwd=str(AUTOMATION_DIR),
            stdout=fh,
            stderr=subprocess.STDOUT,
            start_new_session=True,
        )
    _pid_path(name).write_text(str(proc.pid), encoding="utf-8")
    time.sleep(0.2)
    if proc.poll() is not None:
        print(f"aie: {name} exited immediately — see {log}", file=sys.stderr)
        _pid_path(name).unlink(missing_ok=True)
        return False
    print(f"aie: started {name} (pid {proc.pid}) → {script.name}")
    return True


def _stop_one(name: str) -> bool:
    pid = _read_pid(name)
    if not pid:
        print(f"aie: {name} not running")
        return True
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except ProcessLookupError:
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
    _pid_path(name).unlink(missing_ok=True)
    print(f"aie: stopped {name} (pid {pid})")
    return True


def _resolve_targets(raw: str | None) -> list[str]:
    if not raw or raw == "all":
        return list(ENHANCERS.keys())
    parts = [p.strip().lower() for p in raw.split(",") if p.strip()]
    bad = [p for p in parts if p not in ENHANCERS]
    if bad:
        raise SystemExit(f"Unknown enhancer(s): {', '.join(bad)}. Choose: all, {', '.join(ENHANCERS)}")
    return parts


def cmd_start(args: argparse.Namespace) -> int:
    ok = True
    for name in _resolve_targets(args.target):
        ok = _start_one(name) and ok
    return 0 if ok else 1


def cmd_stop(args: argparse.Namespace) -> int:
    for name in _resolve_targets(args.target):
        _stop_one(name)
    return 0


def cmd_cleanup(_args: argparse.Namespace) -> int:
    script = _script_path("cleanup", ONE_SHOT)
    if not script:
        print("aie: cleanup script not found", file=sys.stderr)
        return 1
    print(f"aie: running {script.name} …")
    return subprocess.call([_python(), str(script)], cwd=str(AUTOMATION_DIR))


def cmd_list(_args: argparse.Namespace) -> int:
    for key, meta in ENHANCERS.items():
        print(f"{key}\t{meta['label']}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Artificial Internet Enhancements (AIE) — background automation suite",
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("status", help="Show enhancer status").set_defaults(func=cmd_status)
    sub.add_parser("list", help="List enhancer ids").set_defaults(func=cmd_list)

    p_start = sub.add_parser("start", help="Start background enhancer(s)")
    p_start.add_argument("target", nargs="?", default="all")
    p_start.set_defaults(func=cmd_start)

    p_stop = sub.add_parser("stop", help="Stop background enhancer(s)")
    p_stop.add_argument("target", nargs="?", default="all")
    p_stop.set_defaults(func=cmd_stop)

    sub.add_parser("cleanup", help="One-shot Downloads cleanup").set_defaults(func=cmd_cleanup)

    args = parser.parse_args()
    if not args.cmd:
        return cmd_status(args)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
