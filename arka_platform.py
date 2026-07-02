#!/usr/bin/env python3
"""Detect host platform once and cache capabilities for Arka (fish + Python)."""

from __future__ import annotations

import argparse
import json
import platform
import shutil
import sys
from datetime import datetime, timezone
from pathlib import Path

try:
    import arka_paths as _ap

    _ap.load_env_file()
    CONFIG_DIR = _ap.config_dir()
except ImportError:
    CONFIG_DIR = Path.home() / ".config" / "arka"

PLATFORM_JSON = "platform.json"
PLATFORM_ENV = "platform.env"


def _config_dir() -> Path:
    if v := __import__("os").environ.get("ARKA_CONFIG_DIR", "").strip():
        return Path(v).expanduser().resolve()
    legacy = Path.home() / ".config" / "fish"
    if (legacy / ".env").is_file():
        return legacy
    CONFIG_DIR.mkdir(parents=True, exist_ok=True)
    return CONFIG_DIR


def platform_json_path() -> Path:
    return _config_dir() / PLATFORM_JSON


def platform_env_path() -> Path:
    return _config_dir() / PLATFORM_ENV


def detect_platform() -> dict:
    sysname = platform.system()
    if sysname == "Darwin":
        plat = "macos"
    elif sysname == "Windows":
        plat = "windows"
    elif sysname.startswith("Linux") or sysname == "Linux":
        plat = "linux"
    else:
        plat = sysname.lower()

    caps: dict[str, str | None] = {}
    if plat == "macos":
        caps["open"] = "open" if shutil.which("open") else None
        caps["clipboard_copy"] = "pbcopy" if shutil.which("pbcopy") else None
        caps["clipboard_paste"] = "pbpaste" if shutil.which("pbpaste") else None
        caps["stat_mtime"] = "darwin"
        caps["package_manager"] = "brew"
    elif plat == "linux":
        caps["open"] = "xdg-open" if shutil.which("xdg-open") else None
        if shutil.which("wl-copy"):
            caps["clipboard_copy"] = "wl-copy"
            caps["clipboard_paste"] = "wl-paste" if shutil.which("wl-paste") else None
        elif shutil.which("xclip"):
            caps["clipboard_copy"] = "xclip"
            caps["clipboard_paste"] = "xclip"
        else:
            caps["clipboard_copy"] = None
            caps["clipboard_paste"] = None
        caps["stat_mtime"] = "linux"
        caps["package_manager"] = "apt"
    elif plat == "windows":
        caps["open"] = "start"
        caps["clipboard_copy"] = "clip" if shutil.which("clip") else None
        caps["clipboard_paste"] = None
        caps["stat_mtime"] = "windows"
        caps["package_manager"] = "winget"
    else:
        caps["stat_mtime"] = "unknown"

    return {
        "version": 1,
        "platform": plat,
        "system": sysname,
        "machine": platform.machine(),
        "detected_at": datetime.now(timezone.utc).isoformat(timespec="seconds"),
        "capabilities": caps,
    }


def load_platform() -> dict | None:
    path = platform_json_path()
    if not path.is_file():
        return None
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return None
    if isinstance(data, dict) and data.get("platform"):
        return data
    return None


def save_platform(data: dict) -> Path:
    cfg = _config_dir()
    cfg.mkdir(parents=True, exist_ok=True)
    json_path = cfg / PLATFORM_JSON
    json_path.write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")

    plat = data["platform"]
    caps = data.get("capabilities") or {}
    lines = [
        f"ARKA_PLATFORM={plat}",
        f"ARKA_PLATFORM_DETECTED_AT={data.get('detected_at', '')}",
        f"ARKA_PLATFORM_IS_MACOS={1 if plat == 'macos' else 0}",
        f"ARKA_PLATFORM_IS_LINUX={1 if plat == 'linux' else 0}",
        f"ARKA_PLATFORM_IS_WINDOWS={1 if plat == 'windows' else 0}",
    ]
    for key, val in caps.items():
        env_key = "ARKA_" + key.upper()
        lines.append(f"{env_key}={val or ''}")
    (cfg / PLATFORM_ENV).write_text("\n".join(lines) + "\n", encoding="utf-8")
    return json_path


def ensure_platform(*, force: bool = False) -> dict:
    existing = load_platform()
    if existing and not force:
        return existing
    data = detect_platform()
    save_platform(data)
    return data


def cached_platform() -> str | None:
    data = load_platform()
    if data:
        return str(data["platform"])
    return None


def cmd_detect(force: bool) -> int:
    data = ensure_platform(force=force)
    print(f"__PLATFORM__={data['platform']}")
    print(f"__DETECTED_AT__={data.get('detected_at', '')}")
    print(f"__SAVED__={platform_json_path()}")
    return 0


def cmd_show() -> int:
    data = load_platform()
    if not data:
        print("Platform not cached yet. Run: arka platform detect", file=sys.stderr)
        return 1
    print(f"platform: {data['platform']}")
    print(f"system:   {data.get('system', '?')}")
    print(f"cached:   {platform_json_path()}")
    print(f"detected: {data.get('detected_at', '?')}")
    caps = data.get("capabilities") or {}
    if caps:
        print("capabilities:")
        for k, v in sorted(caps.items()):
            print(f"  {k}: {v or '-'}")
    return 0


def main() -> int:
    parser = argparse.ArgumentParser(description="Arka platform detection and cache")
    sub = parser.add_subparsers(dest="cmd", required=True)

    p = sub.add_parser("detect", help="Detect platform and save cache (first run)")
    p.add_argument("--force", action="store_true", help="Re-detect even if cache exists")

    sub.add_parser("show", help="Show cached platform profile")
    sub.add_parser("ensure", help="Detect only if cache missing")

    args = parser.parse_args()
    if args.cmd == "detect":
        return cmd_detect(force=args.force)
    if args.cmd == "show":
        return cmd_show()
    if args.cmd == "ensure":
        ensure_platform(force=False)
        return 0
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
