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

from arka.paths import arka_home, cache_dir, python_executable

ENHANCERS: dict[str, dict[str, object]] = {
    "click": {
        "script": "auto_click.py",
        "label": "Auto-click when cursor shape changes (loading spinners)",
        "platforms": ("linux",),
    },
    "copy": {
        "script": "auto_copy_selection.py",
        "label": "Auto-copy text selection to clipboard on paste",
        "platforms": ("linux",),
    },
    "zip": {
        "script": "zip_open.py",
        "label": "Watch folders and auto-extract new zip archives",
        "platforms": ("macos", "linux", "windows"),
    },
    "classify": {
        "script": "classifier.py",
        "label": "Auto-sort new files by type (docs, images, code)",
        "platforms": ("macos", "linux", "windows"),
    },
}

ONE_SHOT: dict[str, dict[str, object]] = {
    "cleanup": {
        "script": "delete_useless.py",
        "label": "Remove installer junk (.zip, .deb, .dmg, …) from Downloads",
        "platforms": ("macos", "linux", "windows"),
    },
}

LEGACY_AUTOMATION_DIRS = (
    Path.home() / "Projects/python/products/automation",
    Path("/home/s/Projects/python/products/automation"),
)


def _host_platform() -> str:
    try:
        from arka.platform_info import system

        return system()
    except ImportError:
        pass
    if sys.platform == "darwin":
        return "macos"
    if sys.platform == "win32":
        return "windows"
    if sys.platform.startswith("linux"):
        return "linux"
    return sys.platform


def _bundled_aie_dir() -> Path:
    return arka_home() / "aie"


def automation_dir() -> Path:
    override = os.environ.get("ARKA_AIE_DIR", "").strip()
    if override:
        return Path(override).expanduser().resolve()
    bundled = _bundled_aie_dir()
    if bundled.is_dir():
        return bundled
    for legacy in LEGACY_AUTOMATION_DIRS:
        if legacy.is_dir():
            return legacy
    return bundled


def _aie_cache_dir() -> Path:
    return cache_dir() / "aie"


def _python() -> str:
    override = os.environ.get("ARKA_AIE_PYTHON", "").strip()
    if override and Path(override).is_file():
        return override
    return python_executable()


def _supported(meta: dict[str, object]) -> bool:
    platforms = meta.get("platforms")
    if not platforms:
        return True
    return _host_platform() in platforms


def _script_path(name: str, catalog: dict[str, dict[str, object]]) -> Path | None:
    entry = catalog.get(name)
    if not entry:
        return None
    script = str(entry["script"])
    root = automation_dir()
    path = root / script
    return path if path.is_file() else None


def _pid_path(name: str) -> Path:
    return _aie_cache_dir() / f"{name}.pid"


def _log_path(name: str) -> Path:
    return _aie_cache_dir() / f"{name}.log"


def _read_pid(name: str) -> int | None:
    path = _pid_path(name)
    if not path.is_file():
        return None
    try:
        pid = int(path.read_text(encoding="utf-8").strip())
    except ValueError:
        path.unlink(missing_ok=True)
        return None
    if pid > 0 and _process_alive(pid):
        return pid
    path.unlink(missing_ok=True)
    return None


def _process_alive(pid: int) -> bool:
    if sys.platform == "win32":
        try:
            import ctypes

            PROCESS_QUERY_LIMITED_INFORMATION = 0x1000
            handle = ctypes.windll.kernel32.OpenProcess(PROCESS_QUERY_LIMITED_INFORMATION, False, pid)
            if handle:
                ctypes.windll.kernel32.CloseHandle(handle)
                return True
            return False
        except Exception:
            return False
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _terminate_pid(pid: int) -> None:
    if sys.platform == "win32":
        subprocess.run(
            ["taskkill", "/PID", str(pid), "/T", "/F"],
            capture_output=True,
            check=False,
        )
        return
    try:
        os.killpg(os.getpgid(pid), signal.SIGTERM)
    except (ProcessLookupError, PermissionError, OSError):
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass


def _platform_note() -> str:
    plat = _host_platform()
    if plat == "macos":
        return "macOS: zip, classify, cleanup run locally; click/copy need Linux or ARKA_AIE_DIR"
    if plat == "windows":
        return "Windows: zip, classify, cleanup supported; click/copy need Linux or ARKA_AIE_DIR"
    return "Linux: all enhancers when scripts and tools (xdotool/xclip) are available"


def cmd_status(_args: argparse.Namespace) -> int:
    _aie_cache_dir().mkdir(parents=True, exist_ok=True)
    print("━━━ Artificial Internet Enhancements (AIE) ━━━")
    print(f"Platform:       {_host_platform()}")
    print(f"Automation dir: {automation_dir()}")
    print(f"Cache/PIDs:     {_aie_cache_dir()}")
    print(f"Note:           {_platform_note()}")
    print("")
    print("Background enhancers:")
    for key, meta in ENHANCERS.items():
        script = _script_path(key, ENHANCERS)
        pid = _read_pid(key)
        if pid:
            state = f"running (pid {pid})"
        elif not _supported(meta):
            state = f"unsupported on {_host_platform()}"
        elif script:
            state = "stopped"
        else:
            state = f"missing script ({meta['script']})"
        print(f"  {key:8} {state:28} — {meta['label']}")
    print("")
    print("One-shot tasks:")
    for key, meta in ONE_SHOT.items():
        script = _script_path(key, ONE_SHOT)
        if not _supported(meta):
            ok = f"unsupported on {_host_platform()}"
        else:
            ok = "ready" if script else "missing"
        print(f"  {key:8} {ok:28} — {meta['label']}")
    print("")
    print("Usage: aie start [all|click|copy|zip|classify]")
    print("       aie stop [all|name]  |  aie stop-all  |  aie cleanup")
    return 0


def _start_one(name: str) -> bool:
    meta = ENHANCERS.get(name, {})
    if not _supported(meta):
        print(f"aie: {name} is not supported on {_host_platform()}", file=sys.stderr)
        return False
    script = _script_path(name, ENHANCERS)
    if not script:
        print(f"aie: script not found for '{name}' in {automation_dir()}", file=sys.stderr)
        return False
    if _read_pid(name):
        print(f"aie: {name} already running")
        return True
    _aie_cache_dir().mkdir(parents=True, exist_ok=True)
    log = _log_path(name)
    log_handle = open(log, "ab")
    popen_kw: dict = {
        "cwd": str(script.parent),
        "stdout": log_handle,
        "stderr": subprocess.STDOUT,
    }
    if sys.platform == "win32":
        popen_kw["creationflags"] = subprocess.CREATE_NEW_PROCESS_GROUP  # type: ignore[attr-defined]
    else:
        popen_kw["start_new_session"] = True
    proc = subprocess.Popen([_python(), str(script)], **popen_kw)
    log_handle.close()
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
    _terminate_pid(pid)
    _pid_path(name).unlink(missing_ok=True)
    print(f"aie: stopped {name} (pid {pid})")
    return True


def _all_pid_files() -> list[Path]:
    root = _aie_cache_dir()
    if not root.is_dir():
        return []
    return sorted(root.glob("*.pid"))


def _stop_all() -> int:
    stopped = 0
    seen: set[str] = set()
    for name in ENHANCERS:
        seen.add(name)
        pid = _read_pid(name)
        if pid:
            _terminate_pid(pid)
            _pid_path(name).unlink(missing_ok=True)
            print(f"aie: stopped {name} (pid {pid})")
            stopped += 1
    for path in _all_pid_files():
        name = path.stem
        if name in seen:
            continue
        try:
            pid = int(path.read_text(encoding="utf-8").strip())
        except ValueError:
            path.unlink(missing_ok=True)
            continue
        if pid > 0 and _process_alive(pid):
            _terminate_pid(pid)
            print(f"aie: stopped orphan {name} (pid {pid})")
            stopped += 1
        path.unlink(missing_ok=True)
    if stopped == 0:
        print("aie: no running enhancers")
    else:
        print(f"aie: stopped {stopped} enhancer(s)")
    return 0


def _resolve_targets(raw: str | list[str] | None, *, for_start: bool = False) -> list[str]:
    if raw is None:
        raw = ["all"]
    if isinstance(raw, str):
        parts = [p.strip().lower() for p in raw.replace(",", " ").split() if p.strip()]
    else:
        parts = [p.strip().lower() for p in raw if p and str(p).strip()]
    if not parts or parts == ["all"] or "all" in parts or "everything" in parts or "*" in parts:
        if for_start:
            return [k for k, meta in ENHANCERS.items() if _supported(meta)]
        return list(ENHANCERS.keys())
    bad = [p for p in parts if p not in ENHANCERS]
    if bad:
        raise SystemExit(f"Unknown enhancer(s): {', '.join(bad)}. Choose: all, {', '.join(ENHANCERS)}")
    return parts


def cmd_start(args: argparse.Namespace) -> int:
    ok = True
    for name in _resolve_targets(args.target, for_start=True):
        ok = _start_one(name) and ok
    return 0 if ok else 1


def cmd_stop(args: argparse.Namespace) -> int:
    targets = args.target if isinstance(args.target, list) else [args.target]
    flat = " ".join(str(t) for t in targets if t).strip().lower()
    if not flat or flat in ("all", "everything", "*") or "all" in targets:
        return _stop_all()
    for name in _resolve_targets(targets):
        _stop_one(name)
    return 0


def cmd_stop_all(_args: argparse.Namespace) -> int:
    return _stop_all()


def cmd_cleanup(_args: argparse.Namespace) -> int:
    meta = ONE_SHOT["cleanup"]
    if not _supported(meta):
        print(f"aie: cleanup is not supported on {_host_platform()}", file=sys.stderr)
        return 1
    script = _script_path("cleanup", ONE_SHOT)
    if not script:
        print(f"aie: cleanup script not found in {automation_dir()}", file=sys.stderr)
        return 1
    print(f"aie: running {script.name} …")
    return subprocess.call([_python(), str(script)], cwd=str(script.parent))


def cmd_list(_args: argparse.Namespace) -> int:
    for key, meta in ENHANCERS.items():
        note = "" if _supported(meta) else f" [{_host_platform()} unsupported]"
        print(f"{key}\t{meta['label']}{note}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Artificial Internet Enhancements (AIE) — background automation suite",
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("status", help="Show enhancer status").set_defaults(func=cmd_status)
    sub.add_parser("list", help="List enhancer ids").set_defaults(func=cmd_list)

    p_start = sub.add_parser("start", help="Start background enhancer(s)")
    p_start.add_argument("target", nargs="*", default=["all"])
    p_start.set_defaults(func=cmd_start)

    p_stop = sub.add_parser("stop", help="Stop background enhancer(s); default is all")
    p_stop.add_argument("target", nargs="*", default=["all"])
    p_stop.set_defaults(func=cmd_stop)

    sub.add_parser("stop-all", help="Stop every running AIE enhancer (alias for stop all)").set_defaults(
        func=cmd_stop_all
    )

    sub.add_parser("cleanup", help="One-shot Downloads cleanup").set_defaults(func=cmd_cleanup)

    args = parser.parse_args()
    if not args.cmd:
        return cmd_status(args)
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
