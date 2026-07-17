"""User skill preferences and hosted-runtime capability filtering."""
from __future__ import annotations

import argparse
import json
import os
import sys
from pathlib import Path

from arka.paths import config_dir

PROFILE_VERSION = 1
HOSTED_DEVICE_SKILLS = frozenset({
    "play_youtube", "youtube_download", "youtube_bulk", "spotify", "spotify_control", "voice",
    "wake", "screen", "browser_check", "app_automation", "desktop_automation",
})


def _path() -> Path:
    return config_dir() / "skills.json"


def _read() -> dict[str, object]:
    try:
        value = json.loads(_path().read_text())
        return value if isinstance(value, dict) else {}
    except (OSError, ValueError, TypeError):
        return {}


def disabled() -> set[str]:
    value = _read().get("disabled", [])
    return {str(name) for name in value} if isinstance(value, list) else set()


def _enabled_overrides() -> set[str]:
    value = _read().get("enabled", [])
    return {str(name) for name in value} if isinstance(value, list) else set()


def _hosted_reasons() -> list[str]:
    reasons: list[str] = []
    if os.environ.get("CI", "").lower() in {"1", "true", "yes"}:
        reasons.append("CI environment")
    if Path("/.dockerenv").exists() or os.environ.get("CONTAINER", "").lower() in {"1", "true", "yes"}:
        reasons.append("container environment")
    if sys.platform.startswith("linux") and not (os.environ.get("DISPLAY") or os.environ.get("WAYLAND_DISPLAY")):
        reasons.append("headless Linux (no display)")
    if sys.platform.startswith("linux") and not Path("/dev/snd").exists():
        reasons.append("no audio device")
    return reasons


def hosted_mode() -> str:
    configured = os.environ.get("ARKA_HOSTED_MODE", "auto").strip().lower()
    if configured in {"1", "true", "yes", "hosted", "server"}:
        return "hosted"
    if configured in {"0", "false", "no", "desktop", "local"}:
        return "desktop"
    stored = str(_read().get("profile", "auto")).lower()
    if stored in {"hosted", "desktop"}:
        return stored
    return "hosted" if _hosted_reasons() else "desktop"


def profile_disabled() -> set[str]:
    return set(HOSTED_DEVICE_SKILLS) if hosted_mode() == "hosted" else set()


def is_disabled(name: str) -> bool:
    return name in (disabled() | (profile_disabled() - _enabled_overrides()))


def _write(data: dict[str, object]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2, sort_keys=True) + "\n")


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(prog="arka skills")
    sub = parser.add_subparsers(dest="cmd", required=True)
    for command in ("disable", "enable"):
        sub.add_parser(command).add_argument("name")
    sub.add_parser("list")
    sub.add_parser("status")
    profile = sub.add_parser("profile")
    profile.add_argument("name", choices=("hosted", "desktop", "auto"))
    profile.add_argument("--apply", action="store_true")
    args = parser.parse_args(argv)
    data = _read()
    user_disabled = disabled()
    overrides = _enabled_overrides()
    if args.cmd == "list":
        print("disabled\t" + (", ".join(sorted(user_disabled)) if user_disabled else "none"))
        return 0
    if args.cmd == "status":
        print(f"profile\t{hosted_mode()}")
        print("reasons\t" + (", ".join(_hosted_reasons()) or "none"))
        print("profile-disabled\t" + (", ".join(sorted(profile_disabled())) or "none"))
        print("user-disabled\t" + (", ".join(sorted(user_disabled)) or "none"))
        print("enabled-overrides\t" + (", ".join(sorted(overrides)) or "none"))
        return 0
    if args.cmd == "profile":
        data.update({"profile": args.name, "profile_version": PROFILE_VERSION})
        if args.apply:
            _write(data)
            print(f"profile\t{args.name}")
        else:
            print(f"profile\t{args.name}\tpreview (add --apply to save)")
        return 0
    if args.cmd == "enable":
        user_disabled.discard(args.name)
        overrides.add(args.name)
    else:
        user_disabled.add(args.name)
        overrides.discard(args.name)
    data.update({"disabled": sorted(user_disabled), "enabled": sorted(overrides), "profile_version": PROFILE_VERSION})
    _write(data)
    print(f"{args.cmd}d\t{args.name}")
    return 0
