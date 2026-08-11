#!/usr/bin/env python3
"""Generate music via Pollinations (elevenmusic) or local ffmpeg tone synthesis."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import urllib.parse
import urllib.request
from datetime import datetime
from pathlib import Path

from arka.media.compose_video import _require_ffmpeg

DEFAULT_MODEL = "elevenmusic"
DEFAULT_DURATION = 30
MIN_DURATION = 3
MAX_DURATION = 300

# Pentatonic C major (Hz) — used by the synthesize fallback
_SYNTH_NOTES = (261.63, 293.66, 329.63, 392.00, 440.00, 523.25, 587.33, 659.25)


def _pollinations_key() -> str:
    for name in ("POLLINATIONS_API_KEY", "POLLINATIONS_KEY"):
        val = os.environ.get(name, "").strip()
        if val:
            return val
    return ""


def _backend() -> str:
    return os.environ.get("MUSIC_BACKEND", "auto").strip().lower() or "auto"


def _default_output(prompt: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", prompt.lower())[:40].strip("-") or "music"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    env_dir = os.environ.get("MUSIC_OUTPUT_DIR", "").strip()
    out_dir = Path(env_dir).expanduser() if env_dir else Path.home() / "Music" / "arka-generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{slug}-{ts}.mp3"


def _setup_hint() -> str:
    return (
        "Music generation needs Pollinations or ffmpeg.\n\n"
        "  Pollinations (AI music, recommended):\n"
        "    1. Get a key: https://enter.pollinations.ai/\n"
        "    2. Add to .env: POLLINATIONS_API_KEY=pk_...\n"
        "    3. Run: arka music_generate upbeat jazz piano\n\n"
        "  Local fallback (simple tones, no API key):\n"
        "    MUSIC_BACKEND=synthesize arka music_generate calm ambient\n"
        "    Requires ffmpeg on PATH.\n\n"
        "  Auto (default): uses Pollinations when a key is set, otherwise synthesize.\n"
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
    headers = {"Authorization": f"Bearer {key}", "User-Agent": "arka-music-generate/1.0"}
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


def _synth_note_sequence(prompt: str, duration: int) -> list[tuple[float, float]]:
    digest = hashlib.sha256(prompt.encode("utf-8")).digest()
    seed = int.from_bytes(digest[:4], "big")
    note_dur = min(1.5, max(0.4, duration / 12))
    notes: list[tuple[float, float]] = []
    elapsed = 0.0
    idx = 0
    while elapsed + 0.05 < duration:
        freq = _SYNTH_NOTES[(seed + idx) % len(_SYNTH_NOTES)]
        dur = min(note_dur, duration - elapsed)
        notes.append((freq, dur))
        elapsed += dur
        idx += 1
    return notes or [(440.0, float(duration))]


def generate_synthesize(prompt: str, output: Path, *, duration: int) -> Path:
    ffmpeg = _require_ffmpeg()
    notes = _synth_note_sequence(prompt, duration)
    out = output if output.suffix.lower() == ".mp3" else output.with_suffix(".mp3")
    out.parent.mkdir(parents=True, exist_ok=True)

    print(
        f"  Synthesize ({duration}s, {len(notes)} tones) — local ffmpeg melody (no API key) …",
        file=sys.stderr,
    )

    with tempfile.TemporaryDirectory(prefix="arka-music-") as tmp:
        tmp_dir = Path(tmp)
        inputs: list[str] = []
        for i, (freq, note_dur) in enumerate(notes):
            seg = tmp_dir / f"note-{i:03d}.wav"
            fade_out = max(0.01, note_dur - 0.05)
            proc = subprocess.run(
                [
                    ffmpeg,
                    "-y",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    "-f",
                    "lavfi",
                    "-i",
                    f"sine=frequency={freq:.2f}:duration={note_dur:.3f}",
                    "-af",
                    f"afade=t=in:st=0:d=0.05,afade=t=out:st={fade_out:.3f}:d=0.05,volume=0.35",
                    str(seg),
                ],
                capture_output=True,
                text=True,
                check=False,
            )
            if proc.returncode != 0:
                detail = (proc.stderr or proc.stdout or str(proc.returncode)).strip()
                raise RuntimeError(f"ffmpeg tone synthesis failed: {detail}")
            inputs.extend(["-i", str(seg)])

        n = len(notes)
        filter_parts = "".join(f"[{i}:a]" for i in range(n))
        filter_complex = f"{filter_parts}concat=n={n}:v=0:a=1[outa]"
        cmd = [
            ffmpeg,
            "-y",
            "-hide_banner",
            "-loglevel",
            "error",
            *inputs,
            "-filter_complex",
            filter_complex,
            "-map",
            "[outa]",
            "-c:a",
            "libmp3lame",
            "-q:a",
            "4",
            str(out),
        ]
        proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
        if proc.returncode != 0:
            detail = (proc.stderr or proc.stdout or str(proc.returncode)).strip()
            raise RuntimeError(f"ffmpeg concat failed: {detail}")

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
    if backend == "auto":
        backend = "pollinations" if _pollinations_key() else "synthesize"

    if backend == "synthesize":
        try:
            saved = generate_synthesize(prompt, output, duration=duration)
        except SystemExit:
            raise
        except Exception as exc:
            raise SystemExit(str(exc)) from exc
        return saved, "synthesize"

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


def music_generate_result(
    prompt: str,
    *,
    output: str | Path | None = None,
    model: str | None = None,
    duration: int | None = None,
    lyrics: str = "",
    instrumental: bool = False,
) -> dict[str, object]:
    dur = min(max(duration or int(os.environ.get("MUSIC_DURATION", DEFAULT_DURATION)), MIN_DURATION), MAX_DURATION)
    out = Path(output).expanduser() if output else _default_output(prompt)
    saved, provider = generate(
        prompt,
        out,
        model=model or os.environ.get("MUSIC_MODEL", DEFAULT_MODEL),
        duration=dur,
        lyrics=lyrics,
        instrumental=instrumental,
    )
    return {
        "prompt": prompt,
        "output": str(saved),
        "provider": provider,
        "duration": dur,
        "instrumental": instrumental,
        "model": model or os.environ.get("MUSIC_MODEL", DEFAULT_MODEL),
    }


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


def cmd_check(_args: argparse.Namespace) -> int:
    backend = _backend()
    if backend == "auto":
        backend = "pollinations" if _pollinations_key() else "synthesize"
    print(f"MUSIC_BACKEND (effective): {backend}")
    if backend == "pollinations":
        if _pollinations_key():
            print("  POLLINATIONS_API_KEY: set")
        else:
            print("  POLLINATIONS_API_KEY: not set — run will fail unless MUSIC_BACKEND=synthesize")
    if backend in ("synthesize", "auto"):
        try:
            ffmpeg = _require_ffmpeg()
            print(f"  ffmpeg: {ffmpeg}")
        except SystemExit as exc:
            print(f"  ffmpeg: missing ({exc})")
            return 1
    print(f"  MUSIC_MODEL: {os.environ.get('MUSIC_MODEL', DEFAULT_MODEL)}")
    print(f"  MUSIC_DURATION: {os.environ.get('MUSIC_DURATION', DEFAULT_DURATION)}")
    return 0


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Generate music (Pollinations elevenmusic or local ffmpeg tones)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  music_generate upbeat lo-fi hip hop\n"
            "  music_generate indie folk --lyrics \"Verse one...\"\n"
            "  music_generate cinematic orchestral --instrumental\n"
            "  music_generate check\n"
        ),
    )
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

    p_parse = sub.add_parser("parse", help="Parse natural language → music_generate args")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)

    p_check = sub.add_parser("check", help="Verify backend (Pollinations key and/or ffmpeg)")
    p_check.set_defaults(func=cmd_check)

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
    if args[0] == "check":
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
