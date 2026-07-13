"""Install local Whisper STT (faster-whisper) for Arka voice and media transcription."""

from __future__ import annotations

import argparse
import re
import subprocess
import sys
from pathlib import Path

DEFAULT_MODEL = "large-v3"

# faster-whisper model ids (see speech-to-speech faster_whisper_stt_arguments)
KNOWN_MODELS = frozenset(
    {
        "tiny",
        "tiny.en",
        "base",
        "base.en",
        "small",
        "small.en",
        "distil-small.en",
        "medium",
        "medium.en",
        "distil-medium.en",
        "large-v1",
        "large-v2",
        "large-v3",
        "large",
        "distil-large-v2",
        "distil-large-v3",
    }
)


def _normalize_model_token(token: str) -> str:
    t = token.lower().strip().replace("_", "-")
    t = re.sub(r"\s+", "-", t)
    return t


def parse_whisper_model(cmd: str) -> str:
    """Extract a faster-whisper model id from natural language."""
    clean = cmd.lower()
    m = re.search(
        r"(?i)\b(?:distil[- ]?)?large[- ]?v[- ]?3\b|\blarge[- ]?v[- ]?3\b",
        clean,
    )
    if m:
        return "distil-large-v3" if "distil" in m.group(0).lower() else "large-v3"
    m = re.search(r"(?i)\b(?:distil[- ]?)?large[- ]?v[- ]?2\b|\blarge[- ]?v[- ]?2\b", clean)
    if m:
        return "distil-large-v2" if "distil" in m.group(0).lower() else "large-v2"
    m = re.search(r"(?i)\b(?:distil[- ]?)?large[- ]?v[- ]?1\b|\blarge[- ]?v[- ]?1\b", clean)
    if m:
        return "large-v1"
    for name in (
        "distil-large-v3",
        "distil-large-v2",
        "distil-medium.en",
        "distil-small.en",
        "medium.en",
        "medium",
        "small.en",
        "small",
        "base.en",
        "base",
        "tiny.en",
        "tiny",
        "large",
    ):
        if re.search(rf"(?i)\b{re.escape(name)}\b", clean):
            return name
    m = re.search(r"(?i)\bwhisper[- ](\S+(?:[- ]\S+)?)", clean)
    if m:
        candidate = _normalize_model_token(m.group(1).replace(" ", "-"))
        if candidate in KNOWN_MODELS:
            return candidate
    return DEFAULT_MODEL


def is_stt_install_request(cmd: str) -> bool:
    clean = cmd.lower().strip()
    if not clean:
        return False
    if re.search(
        r"(?i)\b(?:install|setup|get|download)\b.*\b(?:whisper|faster-whisper|speech[- ]to[- ]text|speech recognition)\b",
        clean,
    ):
        return True
    if re.search(r"(?i)\b(?:install|setup|get|download)\b.*\bstt\b", clean) and re.search(
        r"(?i)\bwhisper\b", clean
    ):
        return True
    if re.search(
        r"(?i)\bwhisper\b.*\b(?:large[- ]?v[- ]?\d|medium|small|base|tiny|distil)\b",
        clean,
    ) and re.search(r"(?i)\b(?:install|setup|get|download)\b", clean):
        return True
    if re.search(r"(?i)^install_stt\b", clean):
        return True
    return False


def route_command(cmd: str) -> str | None:
    if not is_stt_install_request(cmd):
        return None
    model = parse_whisper_model(cmd)
    return f"install_stt {model}"


def cmd_install(argv: list[str] | None = None) -> int:
    from arka.media.transcript import cmd_setup_local

    args = list(argv or [])
    model = DEFAULT_MODEL
    if args and not args[0].startswith("-"):
        model = _normalize_model_token(args[0])
        args = args[1:]
    if model not in KNOWN_MODELS:
        print(f"Unknown Whisper model {model!r}. Try: large-v3, small, medium, base", file=sys.stderr)
        return 1
    return cmd_setup_local(argparse.Namespace(model=model))


def main() -> int:
    parser = argparse.ArgumentParser(description="Install local Whisper STT for Arka")
    sub = parser.add_subparsers(dest="cmd")

    p_route = sub.add_parser("route", help="NL → install_stt command")
    p_route.add_argument("text", nargs="+")

    p_is = sub.add_parser("is-request", help="True if text is an STT install request")
    p_is.add_argument("text", nargs="+")

    p_install = sub.add_parser("install", help="Install faster-whisper and download model")
    p_install.add_argument("model", nargs="?", default=DEFAULT_MODEL)

    args = parser.parse_args()
    text = " ".join(getattr(args, "text", []) or []).strip()

    if args.cmd == "route":
        hit = route_command(text)
        if hit:
            print(hit)
        return 0
    if args.cmd == "is-request":
        print("yes" if is_stt_install_request(text) else "no")
        return 0
    if args.cmd == "install":
        return cmd_install([args.model])
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
