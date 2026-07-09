#!/usr/bin/env python3
"""Arka describe_screen — countdown, capture display, describe via vision stack."""

from __future__ import annotations

import argparse
import re
import shlex
import shutil
import subprocess
import sys
import time
from datetime import datetime
from pathlib import Path

try:
    from arka.paths import cache_dir
except ImportError:
    cache_dir = lambda: Path.home() / ".cache" / "fish-agent"  # noqa: E731

DEFAULT_COUNTDOWN = 10
DEFAULT_PROMPT = (
    "Describe what is visible on this computer screen. "
    "Mention applications, windows, text, UI elements, and overall activity."
)

_KNOWN_CMDS = frozenset({"capture", "parse", "help"})
_SCREEN_PATTERNS = (
    re.compile(
        r"(?i)^(?:please\s+)?(?:tell\s+me\s+)?what(?:'|\s+)s\s+on\s+(?:my\s+)?(?:the\s+)?screen\b(?:\s+(.*))?$"
    ),
    re.compile(
        r"(?i)^(?:please\s+)?what\s+is\s+on\s+(?:my\s+)?(?:the\s+)?screen\b(?:\s+(.*))?$"
    ),
    re.compile(
        r"(?i)^(?:please\s+)?(?:describe|analyze|explain)\s+"
        r"(?:what(?:'|\s+)s\s+on\s+)?(?:my\s+)?(?:the\s+)?screen\b(?:\s+(.*))?$"
    ),
    re.compile(
        r"(?i)^(?:please\s+)?(?:look\s+at|see)\s+(?:my\s+)?(?:the\s+)?screen\b(?:\s+(.*))?$"
    ),
    re.compile(r"(?i)^(?:please\s+)?(?:describe|analyze)\s+screen\b(?:\s+(.*))?$"),
    re.compile(r"(?i)^screen(?:\s+describe)?$"),
    re.compile(r"(?i)^describe\s+screen$"),
)


def _normalize(text: str) -> str:
    t = re.sub(r"\s+", " ", text.strip())
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "\"'":
        t = t[1:-1].strip()
    t = re.sub(r"(?i)^(?:please\s+)?tell\s+me\s+", "", t).strip()
    return t


def is_screen_describe_request(text: str) -> bool:
    t = _normalize(text)
    if not t:
        return False
    if re.search(r"(?i)\b(?:screen\s*time|app\s*usage|usage\s*stats)\b", t):
        return False
    if re.search(r"(?i)\b(?:take|save)\s+(?:a\s+)?screenshot\b", t):
        return False
    return any(pat.match(t) for pat in _SCREEN_PATTERNS)


def _extract_question(text: str) -> str:
    t = _normalize(text)
    for pat in _SCREEN_PATTERNS:
        m = pat.match(t)
        if not m:
            continue
        if m.lastindex and m.group(1):
            q = (m.group(1) or "").strip(" .,-")
            if q:
                return q
        return DEFAULT_PROMPT
    return DEFAULT_PROMPT


def nl_to_argv(text: str) -> list[str]:
    if not is_screen_describe_request(text):
        return []
    question = _extract_question(text)
    if question == DEFAULT_PROMPT:
        return ["capture"]
    return ["capture", question]


def run_countdown(seconds: int = DEFAULT_COUNTDOWN, *, stream=None) -> None:
    out = stream or sys.stderr
    seconds = max(0, int(seconds))
    for remaining in range(seconds, 0, -1):
        print(f"Capturing in {remaining}...", file=out, flush=True)
        time.sleep(1)
    if seconds > 0:
        print("Capturing now...", file=out, flush=True)


def _capture_darwin(path: Path) -> bool:
    screencapture = shutil.which("screencapture")
    if not screencapture:
        return False
    proc = subprocess.run(
        [screencapture, "-x", str(path)],
        capture_output=True,
        timeout=30,
    )
    return proc.returncode == 0 and path.is_file()


def _capture_linux(path: Path) -> bool:
    for cmd in (
        ["gnome-screenshot", "-f", str(path)],
        ["scrot", str(path)],
        ["import", "-window", "root", str(path)],
        ["maim", str(path)],
    ):
        if not shutil.which(cmd[0]):
            continue
        try:
            proc = subprocess.run(cmd, capture_output=True, timeout=30)
        except (subprocess.TimeoutExpired, OSError):
            continue
        if proc.returncode == 0 and path.is_file():
            return True
    return False


def capture_screen(path: Path | None = None) -> Path:
    cache = cache_dir()
    cache.mkdir(parents=True, exist_ok=True)
    dest = path or cache / f"screen_capture_{datetime.now():%Y%m%d_%H%M%S}.png"
    dest.parent.mkdir(parents=True, exist_ok=True)

    ok = False
    if sys.platform == "darwin":
        ok = _capture_darwin(dest)
    elif sys.platform.startswith("linux"):
        ok = _capture_linux(dest)
    else:
        ok = _capture_darwin(dest) or _capture_linux(dest)

    if not ok or not dest.is_file():
        raise SystemExit(
            "Screen capture failed. On macOS install screencapture (built-in); "
            "on Linux install gnome-screenshot, scrot, or imagemagick."
        )
    return dest


def describe_screen(
    question: str | None = None,
    *,
    countdown: int = DEFAULT_COUNTDOWN,
    output_path: Path | None = None,
    skip_countdown: bool = False,
) -> str:
    if not skip_countdown and countdown > 0:
        run_countdown(countdown)
    image_path = capture_screen(output_path)
    try:
        from arka.vision.describe import describe_source
    except ImportError as exc:
        raise SystemExit(f"Vision stack unavailable: {exc}") from exc
    prompt = (question or "").strip() or DEFAULT_PROMPT
    return describe_source(str(image_path), prompt)


def cmd_capture(args: argparse.Namespace) -> int:
    question = " ".join(args.question).strip() if args.question else None
    print(
        describe_screen(
            question,
            countdown=args.countdown,
            output_path=Path(args.output).expanduser() if args.output else None,
            skip_countdown=args.no_countdown,
        )
    )
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(_normalize(" ".join(args.text)))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Capture the screen and describe it with vision")
    sub = p.add_subparsers(dest="cmd")

    p_cap = sub.add_parser("capture", help="Count down, capture screen, describe")
    p_cap.add_argument("question", nargs="*", help="Optional focus question")
    p_cap.add_argument(
        "--countdown",
        type=int,
        default=DEFAULT_COUNTDOWN,
        help=f"Seconds before capture (default {DEFAULT_COUNTDOWN})",
    )
    p_cap.add_argument("--no-countdown", action="store_true", help="Capture immediately")
    p_cap.add_argument("-o", "--output", help="Screenshot path (default: cache dir)")
    p_cap.set_defaults(func=cmd_capture)

    p_parse = sub.add_parser("parse", help="Parse natural language → describe_screen args")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)

    sub.add_parser("help", help="Show usage").set_defaults(
        func=lambda _a: (build_parser().print_help(), 0)[1]
    )
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
            argv = ["capture", *argv]
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 1
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
