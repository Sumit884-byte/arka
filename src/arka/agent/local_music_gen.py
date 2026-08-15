"""Local music generation via ffmpeg tone synthesis (no cloud API)."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
from pathlib import Path

_LOCAL_INTENT_RE = re.compile(
    r"(?i)\b(?:"
    r"locally|local(?:ly)?|offline|on[\s-]device|on[\s-]prem(?:ises)?|"
    r"without\s+(?:cloud|api)|no\s+cloud|self[\s-]hosted|private|"
    r"ffmpeg|synthesize|synthesis|tone[\s-]?synth|local\s+(?:music|audio|model)"
    r")\b"
)

_EXPLICIT_MUSIC_RE = re.compile(
    r"(?i)(?:^|\b)(?:generate|create|make|compose|produce)\s+(?:\w+\s+){0,6}"
    r"(?:music|song|track|tune|melody|beat)\b"
)

_PLAY_MUSIC_RE = re.compile(
    r"(?i)\b(?:play|listen(?:\s+to)?|open|queue|shuffle)\b.*\b(?:music|song|track|album)\b"
)


def _clean_nl_text(text: str) -> str:
    t = (text or "").strip()
    if len(t) >= 2 and t[0] == t[-1] and t[0] in "'\"":
        t = t[1:-1].strip()
    return t


def wants_local_music(text: str) -> bool:
    """True when the user wants offline ffmpeg synthesis, not cloud generate_music."""
    t = _clean_nl_text(text)
    if not t:
        return False
    if _PLAY_MUSIC_RE.search(t) and not _EXPLICIT_MUSIC_RE.search(t):
        return False
    if _LOCAL_INTENT_RE.search(t) and _EXPLICIT_MUSIC_RE.search(t):
        return True
    if re.search(
        r"(?i)\b(?:generate|create|compose|make|produce)\b.*\b(?:music|song|track|tune|melody|beat)\b.*\blocal(?:ly)?\b",
        t,
    ):
        return True
    if re.search(
        r"(?i)\blocal(?:ly)?\b.*\b(?:generate|create|compose|make|produce)\b.*\b(?:music|song|track|tune|melody|beat)\b",
        t,
    ):
        return True
    if re.search(r"(?i)\b(?:offline|without\s+cloud)\s+(?:music|song|track)\b", t):
        return True
    return False


def _normalize_local_request(text: str) -> str:
    t = _clean_nl_text(text)
    t = re.sub(
        r"(?i)\b(?:"
        r"locally|local(?:ly)?|offline|on[\s-]device|on[\s-]prem(?:ises)?|"
        r"using\s+local(?:\s+(?:music|audio|model))?|"
        r"with\s+ffmpeg|via\s+ffmpeg|without\s+(?:cloud|api)|no\s+cloud|"
        r"self[\s-]hosted|private|ffmpeg|synthesize|synthesis|tone[\s-]?synth|"
        r"local\s+(?:music|audio|model)"
        r")\b",
        " ",
        t,
    )
    return " ".join(t.split())


def _argv_from_text(text: str) -> list[str]:
    from arka.media.music_generate import (
        _extract_lyrics,
        _extract_music_prompt,
        _is_music_generation_request,
    )

    normalized = _normalize_local_request(text)
    source = normalized
    if not _is_music_generation_request(source) and not _EXPLICIT_MUSIC_RE.search(source):
        source = f"generate music {source}".strip()

    argv: list[str] = ["generate"]
    if re.search(r"(?i)\b(instrumental|no\s+lyrics|without\s+lyrics)\b", text):
        argv.append("--instrumental")
    dur = re.search(r"(?i)\b(?:for|-d|--duration)\s+(\d+)\s*(?:seconds?|secs?|s)?\b", text)
    if dur:
        argv.extend(["-d", dur.group(1)])
    lyrics = _extract_lyrics(source)
    prompt = _extract_music_prompt(source)
    if lyrics:
        argv.extend(["--lyrics", lyrics])
    if prompt:
        argv.append(prompt)
    elif len(argv) == 1:
        return []
    return argv


def nl_to_argv(text: str) -> list[str] | None:
    t = (text or "").strip()
    if not t or not wants_local_music(t):
        return None
    argv = _argv_from_text(t)
    if not argv or argv == ["generate"]:
        return None
    return argv


def route_command(text: str) -> str:
    argv = nl_to_argv(text)
    if not argv:
        return ""
    return "music local " + " ".join(shlex.quote(a) for a in argv)


def generate(
    prompt: str,
    output: str,
    *,
    duration: int = 30,
    lyrics: str = "",
    instrumental: bool = False,
) -> dict[str, object]:
    from arka.media.music_generate import _default_output, generate as cloud_generate

    out = Path(output).expanduser() if output else _default_output(prompt)
    prev = os.environ.get("MUSIC_BACKEND")
    os.environ["MUSIC_BACKEND"] = "synthesize"
    try:
        saved, provider = cloud_generate(
            prompt,
            out,
            model=os.environ.get("MUSIC_MODEL", "elevenmusic"),
            duration=duration,
            lyrics=lyrics,
            instrumental=instrumental,
        )
    finally:
        if prev is None:
            os.environ.pop("MUSIC_BACKEND", None)
        else:
            os.environ["MUSIC_BACKEND"] = prev
    if provider != "synthesize":
        raise RuntimeError(f"expected local synthesize backend, got {provider}")
    return {
        "output": str(saved),
        "backend": "synthesize",
        "prompt": prompt,
        "duration": duration,
        "instrumental": instrumental,
    }


def local_music_result(
    prompt: str,
    *,
    output: str | None = None,
    duration: int | None = None,
    lyrics: str = "",
    instrumental: bool = False,
) -> dict[str, object]:
    from arka.media.music_generate import DEFAULT_DURATION, MAX_DURATION, MIN_DURATION, _default_output

    dur = min(
        max(duration or int(os.environ.get("MUSIC_DURATION", DEFAULT_DURATION)), MIN_DURATION),
        MAX_DURATION,
    )
    out = output or str(_default_output(prompt))
    return generate(prompt, out, duration=dur, lyrics=lyrics, instrumental=instrumental)


def doctor() -> dict[str, object]:
    ffmpeg = None
    issue = None
    try:
        from arka.media.compose_video import _require_ffmpeg

        ffmpeg = _require_ffmpeg()
    except SystemExit as exc:
        issue = str(exc)
    return {
        "backend": "synthesize",
        "ffmpeg": ffmpeg,
        "music_output_dir": os.environ.get("MUSIC_OUTPUT_DIR") or str(Path.home() / "Music" / "arka-generated"),
        "recommendation": "Local music uses ffmpeg tone synthesis — no API key required."
        if ffmpeg
        else "Install ffmpeg and retry.",
        "issue": issue,
    }


def run_nl(text: str) -> int:
    argv = nl_to_argv(text)
    if not argv or argv[0] != "generate":
        return 1
    return main(argv[1:])


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if argv and argv[0] == "doctor":
        print(json.dumps(doctor(), indent=2))
        return 0
    if argv and argv[0] == "parse":
        parsed = nl_to_argv(" ".join(argv[1:]))
        if not parsed:
            return 1
        print(" ".join(shlex.quote(a) for a in parsed))
        return 0

    p = argparse.ArgumentParser(prog="arka music local generate")
    p.add_argument("prompt", nargs="+")
    p.add_argument("--output", "-o")
    p.add_argument("--duration", "-d", type=int)
    p.add_argument("--lyrics")
    p.add_argument("--instrumental", action="store_true")
    p.add_argument("--json", action="store_true")
    if argv and argv[0] == "generate":
        argv = argv[1:]
    args = p.parse_args(argv)

    prompt_parts = list(args.prompt)
    if args.lyrics:
        prompt_parts = [a for a in prompt_parts if a != args.lyrics]
    prompt = " ".join(prompt_parts).strip()
    if not prompt:
        p.error("prompt is required")

    from arka.media.music_generate import DEFAULT_DURATION

    try:
        result = local_music_result(
            prompt,
            output=args.output,
            duration=args.duration or int(os.environ.get("MUSIC_DURATION", DEFAULT_DURATION)),
            lyrics=(args.lyrics or "").strip(),
            instrumental=bool(args.instrumental),
        )
    except (OSError, RuntimeError, ValueError) as exc:
        p.error(str(exc))
    print(
        json.dumps(result, indent=2)
        if args.json
        else f"Generated local music: {result['output']}"
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
