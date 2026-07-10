#!/usr/bin/env python3
"""Clipboard history — save, list, and recall recent clipboard entries."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    from arka.core.platform import detect_platform
    from arka.paths import config_dir, load_env_file

    load_env_file()
except ImportError:

    def load_env_file() -> None:
        pass

    def config_dir() -> Path:
        return Path.home() / ".config" / "arka"

    def detect_platform() -> dict:
        import platform as _platform
        from shutil import which

        plat = "macos" if sys.platform == "darwin" else "linux"
        caps: dict[str, str | None] = {}
        if plat == "macos":
            caps["clipboard_copy"] = "pbcopy" if which("pbcopy") else None
            caps["clipboard_paste"] = "pbpaste" if which("pbpaste") else None
        else:
            caps["clipboard_copy"] = "xclip" if which("xclip") else None
            caps["clipboard_paste"] = "xclip" if which("xclip") else None
        return {"platform": plat, "capabilities": caps}


_HISTORY_FILE = "clipboard_history.json"
_MAX_ENTRIES = 50

_TRIGGER_RE = re.compile(
    r"(?i)\b("
    r"clipboard\s+history|clipboard\s+manager|clip\s+history|"
    r"saved?\s+clipboard|paste\s+from\s+history|clipboard\s+entries"
    r")\b"
)
_SAVE_RE = re.compile(r"(?i)\b(?:save|store|remember)\s+(?:this\s+)?(?:clipboard|clip)\b")
_LIST_RE = re.compile(r"(?i)\b(?:list|show)\s+(?:clipboard\s+)?history\b")
_PASTE_RE = re.compile(r"(?i)\b(?:paste|restore)\s+(?:clipboard\s+)?(?:entry|item|#)?\s*(\d+)?\b")
_CLEAR_RE = re.compile(r"(?i)\b(?:clear|wipe)\s+clipboard\s+history\b")


def _store_path() -> Path:
    path = config_dir() / _HISTORY_FILE
    path.parent.mkdir(parents=True, exist_ok=True)
    return path


def _now_iso() -> str:
    return datetime.now(timezone.utc).replace(microsecond=0).isoformat()


def _clipboard_caps() -> tuple[str | None, str | None]:
    info = detect_platform()
    caps = info.get("capabilities") or {}
    return caps.get("clipboard_paste"), caps.get("clipboard_copy")


def _read_clipboard() -> str:
    paste_cmd, _ = _clipboard_caps()
    if not paste_cmd:
        return ""
    if paste_cmd == "pbpaste":
        code, out, _ = _run([paste_cmd])
        return out if code == 0 else ""
    if paste_cmd == "xclip":
        code, out, _ = _run([paste_cmd, "-selection", "clipboard", "-o"])
        return out if code == 0 else ""
    if paste_cmd == "wl-paste":
        code, out, _ = _run([paste_cmd, "--no-newline"])
        return out if code == 0 else ""
    return ""


def _write_clipboard(text: str) -> bool:
    _, copy_cmd = _clipboard_caps()
    if not copy_cmd or not text:
        return False
    try:
        if copy_cmd == "pbcopy":
            proc = subprocess.run([copy_cmd], input=text, text=True, capture_output=True, timeout=10)
            return proc.returncode == 0
        if copy_cmd == "xclip":
            proc = subprocess.run(
                [copy_cmd, "-selection", "clipboard"],
                input=text,
                text=True,
                capture_output=True,
                timeout=10,
            )
            return proc.returncode == 0
        if copy_cmd == "wl-copy":
            proc = subprocess.run([copy_cmd], input=text, text=True, capture_output=True, timeout=10)
            return proc.returncode == 0
    except (OSError, subprocess.TimeoutExpired):
        return False
    return False


def _run(cmd: list[str]) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True, timeout=15)
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except (OSError, subprocess.TimeoutExpired) as exc:
        return 1, "", str(exc)


def _load() -> list[dict]:
    path = _store_path()
    if not path.is_file():
        return []
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return []
    return data if isinstance(data, list) else []


def _save(rows: list[dict]) -> None:
    _store_path().write_text(json.dumps(rows[:_MAX_ENTRIES], indent=2), encoding="utf-8")


def _preview(text: str, limit: int = 80) -> str:
    one_line = " ".join(text.split())
    return one_line[:limit] + ("…" if len(one_line) > limit else "")


def wants_clipboard_history(text: str) -> bool:
    clean = (text or "").strip()
    if not clean:
        return False
    if _TRIGGER_RE.search(clean):
        return True
    if _SAVE_RE.search(clean) or _LIST_RE.search(clean) or _CLEAR_RE.search(clean):
        return True
    if _PASTE_RE.search(clean):
        return True
    return False


def cmd_save(_args: argparse.Namespace) -> int:
    text = _read_clipboard().strip()
    if not text:
        print("Clipboard is empty or clipboard tools are unavailable.", file=sys.stderr)
        return 1
    rows = _load()
    if rows and rows[0].get("text") == text:
        print("Already saved (latest entry matches clipboard).")
        return 0
    rows.insert(
        0,
        {
            "id": len(rows) + 1,
            "text": text,
            "preview": _preview(text),
            "saved_at": _now_iso(),
        },
    )
    _save(rows)
    print(f"Saved clipboard entry #1 ({len(text)} chars)")
    print(_preview(text, 120))
    return 0


def cmd_list(_args: argparse.Namespace) -> int:
    rows = _load()
    if not rows:
        print("Clipboard history is empty. Try: clipboard_history save")
        return 0
    lines = [f"Clipboard history ({len(rows)}):"]
    for idx, row in enumerate(rows, start=1):
        lines.append(f"{idx}. {_preview(str(row.get('text') or ''), 100)}")
        saved = str(row.get("saved_at") or "")[:19]
        if saved:
            lines.append(f"   saved: {saved}")
    print("\n".join(lines))
    return 0


def cmd_paste(args: argparse.Namespace) -> int:
    rows = _load()
    try:
        idx = int(args.index)
    except ValueError:
        print("Index must be a number", file=sys.stderr)
        return 1
    if idx < 1 or idx > len(rows):
        print(f"Invalid index {idx} (have {len(rows)} entries)", file=sys.stderr)
        return 1
    text = str(rows[idx - 1].get("text") or "")
    if args.stdout:
        print(text, end="")
        return 0
    if _write_clipboard(text):
        print(f"Restored entry #{idx} to clipboard ({len(text)} chars)")
        return 0
    print(text)
    print("(clipboard copy unavailable — printed above)", file=sys.stderr)
    return 0


def cmd_clear(_args: argparse.Namespace) -> int:
    _save([])
    print("Clipboard history cleared.")
    return 0


def route_command(text: str) -> str:
    if not wants_clipboard_history(text):
        return ""
    clean = (text or "").strip()
    if _CLEAR_RE.search(clean):
        return "clipboard_history clear"
    if _LIST_RE.search(clean) or _TRIGGER_RE.search(clean) and not _SAVE_RE.search(clean):
        return "clipboard_history list"
    if _SAVE_RE.search(clean):
        return "clipboard_history save"
    m = _PASTE_RE.search(clean)
    if m and m.group(1):
        return f"clipboard_history paste {m.group(1)}"
    num = re.search(r"\b(\d+)\b", clean)
    if num and re.search(r"(?i)\b(?:paste|restore)\b", clean):
        return f"clipboard_history paste {num.group(1)}"
    return "clipboard_history list"


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    parser = argparse.ArgumentParser(description="Clipboard history manager")
    sub = parser.add_subparsers(dest="cmd")

    p_route = sub.add_parser("route", help="Map NL to clipboard_history command")
    p_route.add_argument("text", nargs="+")

    sub.add_parser("save", help="Save current clipboard to history").set_defaults(func=cmd_save)
    sub.add_parser("list", help="List clipboard history").set_defaults(func=cmd_list)
    sub.add_parser("clear", help="Clear clipboard history").set_defaults(func=cmd_clear)

    p_paste = sub.add_parser("paste", help="Restore history entry to clipboard")
    p_paste.add_argument("index")
    p_paste.add_argument("--stdout", action="store_true")
    p_paste.set_defaults(func=cmd_paste)

    args = parser.parse_args(argv)
    if args.cmd == "route":
        route = route_command(" ".join(args.text))
        if route:
            print(route)
            return 0
        return 1
    if hasattr(args, "func"):
        return int(args.func(args))
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
