#!/usr/bin/env python3
"""Generate music via Pollinations (elevenmusic / acestep)."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

DEFAULT_MODEL = "elevenmusic"
DEFAULT_DURATION = 30
MIN_DURATION = 3
MAX_DURATION = 300


def _pollinations_key() -> str:
    for name in ("POLLINATIONS_API_KEY", "POLLINATIONS_KEY"):
        val = os.environ.get(name, "").strip()
        if val:
            return val
    return ""


def _backend() -> str:
    return os.environ.get("MUSIC_BACKEND", "pollinations").strip().lower() or "pollinations"


def _default_output(prompt: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower())[:40].strip("-") or "music"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    env_dir = os.environ.get("MUSIC_OUTPUT_DIR", "").strip()
    out_dir = Path(env_dir).expanduser() if env_dir else Path.home() / "Music" / "arka-generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{slug}-{ts}.mp3"


def _setup_hint() -> str:
    return (
        "Music generation needs a Pollinations API key.\n\n"
        "  1. Get a key: https://enter.pollinations.ai/\n"
        "  2. Add to .env:\n"
        "       POLLINATIONS_API_KEY=pk_...\n"
        "  3. Run:\n"
        "       arka generate music upbeat jazz piano\n"
        "       arka generate music indie folk --lyrics \"Verse one...\"\n"
        "       arka generate music cinematic --instrumental\n"
    )


def _friendly_error(exc: Exception) -> str:
    text = str(exc)
    if "401" in text or "403" in text:
        return "Pollinations rejected the API key — check POLLINATIONS_API_KEY in .env"
    if "429" in text:
        return "Pollinations rate limit — try again shortly."
    return text[:240]


def _compose_input(prompt: str, lyrics: str, *, instrumental: bool) -> str:
    style = prompt.strip()
    lyrics = lyrics.strip()
    if instrumental:
        return style or "instrumental music"
    if lyrics:
        if style:
            return f"{style}. Lyrics:\n{lyrics}"
        return f"Song with lyrics:\n{lyrics}"
    return style or "original song"


def _download_url(url: str, headers: dict[str, str], timeout: int = 600) -> bytes:
    req = urllib.request.Request(url, headers=headers)
    with urllib.request.urlopen(req, timeout=timeout) as resp:
        data = resp.read()
    if not data:
        raise RuntimeError("Empty response from music provider")
    if data[:1] == b"{":
        try:
            payload = json.loads(data.decode("utf-8", errors="replace"))
            msg = payload.get("error") or payload.get("message") or payload
            raise RuntimeError(str(msg))
        except json.JSONDecodeError:
            pass
    return data


def generate_pollinations(
    prompt: str,
    output: Path,
    *,
    model: str,
    duration: int,
    lyrics: str,
    instrumental: bool,
) -> Path:
    key = _pollinations_key()
    if not key:
        raise RuntimeError("POLLINATIONS_API_KEY not set")

    text = _compose_input(prompt, lyrics, instrumental=instrumental)
    encoded = urllib.parse.quote(text)
    params: dict[str, str | int] = {
        "model": model,
        "duration": duration,
    }
    if instrumental:
        params["instrumental"] = "true"
    url = f"https://gen.pollinations.ai/audio/{encoded}?{urllib.parse.urlencode(params)}"
    headers = {"Authorization": f"Bearer {key}", "User-Agent": "arka-generate-music/1.0"}
    mode = "instrumental" if instrumental else ("with lyrics" if lyrics else "vocals from prompt")
    print(
        f"  Pollinations ({model}, {duration}s, {mode}) — generating music, may take a minute …",
        file=sys.stderr,
    )
    data = _download_url(url, headers=headers)

    out = output if output.suffix.lower() == ".mp3" else output.with_suffix(".mp3")
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_bytes(data)
    return out


def generate(
    prompt: str,
    output: Path,
    *,
    model: str,
    duration: int,
    lyrics: str,
    instrumental: bool,
) -> tuple[Path, str]:
    backend = _backend()
    if backend != "pollinations":
        raise RuntimeError(f"Unsupported MUSIC_BACKEND: {backend}")

    if not _pollinations_key():
        raise SystemExit(_setup_hint())

    try:
        saved = generate_pollinations(
            prompt,
            output,
            model=model,
            duration=duration,
            lyrics=lyrics,
            instrumental=instrumental,
        )
    except SystemExit:
        raise
    except Exception as exc:
        raise SystemExit(_friendly_error(exc)) from exc
    return saved, "pollinations"


_MUSIC_VERBS = r"(?:generate|create|make|compose|produce)"
_MUSIC_NOUNS = r"(?:music|song|track|tune|melody|beat)"


def _is_music_generation_request(text: str) -> bool:
    t = text.strip()
    if not t:
        return False
    if re.search(rf"(?i)^{_MUSIC_VERBS}\s+(?:an?\s+)?{_MUSIC_NOUNS}\b", t):
        return True
    if re.search(rf"(?i)^{_MUSIC_VERBS}\s+(?:an?\s+)?.+\b{_MUSIC_NOUNS}\b", t):
        return True
    return False


def _extract_music_prompt(text: str) -> str:
    t = text.strip()
    t = re.sub(
        rf"(?i)^{_MUSIC_VERBS}\s+(?:an?\s+)?{_MUSIC_NOUNS}\s*",
        "",
        t,
    )
    if t == text.strip():
        t = re.sub(rf"(?i)^{_MUSIC_VERBS}\s+(?:an?\s+)?", "", text.strip())
        t = re.sub(rf"(?i)\s+\b{_MUSIC_NOUNS}\s*$", "", t)
    t = re.sub(r"(?i)\s+with\s+lyrics\s*:?\s*[\s\S]+$", "", t)
    t = re.sub(r"(?i)\s+lyrics\s*:?\s*[\s\S]+$", "", t)
    t = re.sub(r"(?i)\s+--instrumental\b", "", t)
    t = re.sub(r"(?i)\b(instrumental|no\s+lyrics|without\s+lyrics)\b", "", t)
    t = re.sub(r"(?i)\b(?:for|-d|--duration)\s+\d+\s*(?:seconds?|secs?|s)?\b", "", t)
    t = re.sub(r"(?i)^(?:of|about|for)\s+", "", t.strip())
    return re.sub(r"\s+", " ", t).strip()


def _extract_lyrics(text: str) -> str:
    m = re.search(r"(?i)(?:with\s+)?lyrics\s*:?\s*(.+)$", text.strip(), re.DOTALL)
    return m.group(1).strip() if m else ""


def nl_to_argv(text: str) -> list[str]:
    t = text.strip()
    if not t or not _is_music_generation_request(t):
        return []

    argv: list[str] = []
    if re.search(r"(?i)\b(instrumental|no\s+lyrics|without\s+lyrics)\b", t):
        argv.append("--instrumental")

    dur = re.search(r"(?i)\b(?:for|-d|--duration)\s+(\d+)\s*(?:seconds?|secs?|s)?\b", t)
    if dur:
        argv.extend(["-d", dur.group(1)])

    lyrics = _extract_lyrics(t)
    prompt = _extract_music_prompt(t)
    if lyrics:
        argv.extend(["--lyrics", lyrics])
    if prompt:
        argv.append(prompt)
    elif not argv:
        return []
    return argv


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def cmd_generate(args: argparse.Namespace) -> int:
    lyrics = (args.lyrics or "").strip()
    if args.lyrics_file:
        lyrics = Path(args.lyrics_file).expanduser().read_text(encoding="utf-8").strip()
    instrumental = bool(args.instrumental)

    duration = min(max(args.duration, MIN_DURATION), MAX_DURATION)
    out = Path(args.output) if args.output else _default_output(args.prompt)

    print(f"Generating music ({duration}s) …")
    try:
        saved, provider = generate(
            args.prompt,
            out,
            model=args.model,
            duration=duration,
            lyrics=lyrics,
            instrumental=instrumental,
        )
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 1

    print(f"Saved ({provider}): {saved}")
    if os.environ.get("OPEN_MUSIC", "1") not in ("0", "false"):
        try:
            if sys.platform == "darwin":
                subprocess.Popen(["open", str(saved)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            elif sys.platform.startswith("linux"):
                subprocess.Popen(["xdg-open", str(saved)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        except OSError:
            pass
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="Generate music with Pollinations (elevenmusic)")
    sub = p.add_subparsers(dest="cmd")

    p_gen = sub.add_parser("generate", help="Generate music from a style prompt")
    p_gen.add_argument("prompt", help="Music style or theme")
    p_gen.add_argument("-o", "--output", help="Output .mp3 path")
    p_gen.add_argument("-d", "--duration", type=int, default=int(os.environ.get("MUSIC_DURATION", DEFAULT_DURATION)))
    p_gen.add_argument("-m", "--model", default=os.environ.get("MUSIC_MODEL", DEFAULT_MODEL))
    p_gen.add_argument("--lyrics", help="Lyrics to sing (omit for prompt-only vocals)")
    p_gen.add_argument("--lyrics-file", help="Read lyrics from a text file")
    p_gen.add_argument("--instrumental", action="store_true", help="Instrumental only — no vocals")
    p_gen.set_defaults(func=cmd_generate)

    p_parse = sub.add_parser("parse", help="Parse natural language → generate_music args")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)

    return p


def main(argv: list[str] | None = None) -> int:
    args = list(argv if argv is not None else sys.argv[1:])
    if not args:
        build_parser().print_help()
        return 0
    if args in (["-h"], ["--help"]):
        build_parser().parse_args(["generate", "--help"])
        return 0
    if args[0] == "parse":
        ns = build_parser().parse_args(args)
        return int(ns.func(ns))
    if args[0] not in {"generate", "-h", "--help"}:
        args = ["generate", *args]
    try:
        ns = build_parser().parse_args(args)
    except SystemExit as exc:
        return int(exc.code or 0)
    if not getattr(ns, "cmd", None):
        build_parser().print_help()
        return 0
    return int(ns.func(ns))


if __name__ == "__main__":
    raise SystemExit(main())
