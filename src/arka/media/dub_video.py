#!/usr/bin/env python3
"""Dub video locally — transcribe speech, translate, TTS, and mux onto video."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from arka.agent.survival_lang import google_translate, resolve_lang_code
from arka.core.compute import ffmpeg_thread_args
from arka.media.compose_video import _require_ffmpeg, _which
from arka.media.edit_video import default_output_path, media_info, mux_audio
from arka.media.transcript import transcribe_file

MEDIA_EXT = r"(?:mp4|webm|mov|avi|mkv|m4v|mp3|wav|aac|m4a|flac|ogg|opus|wma)"
INDIC_TTS_LANGS = frozenset({"hi", "bn", "ta", "te", "mr", "gu", "kn", "ml", "pa", "as", "ur"})


def _ffmpeg_run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or str(proc.returncode)).strip()
        raise SystemExit(f"ffmpeg failed: {detail}")


def target_bcp47(code: str) -> str:
    """Map translate lang code to a TTS locale hint."""
    raw = (code or "").strip()
    if not raw:
        return "en-IN"
    if "-" in raw:
        return raw
    from arka.voice.edge_speak import LANG_ALIASES

    return LANG_ALIASES.get(raw.lower(), raw)


def _sarvam_to_file(text: str, output: Path, *, lang: str) -> Path:
    from arka.voice.sarvam_speak import chunk_text, synthesize_chunk

    output = Path(output)
    output.parent.mkdir(parents=True, exist_ok=True)
    chunks = chunk_text(" ".join(text.split()), 2000)
    wav_paths: list[Path] = []
    with tempfile.TemporaryDirectory(prefix="arka-dub-sarvam-") as tmp:
        tmpdir = Path(tmp)
        for i, chunk in enumerate(chunks):
            wav = tmpdir / f"chunk_{i:03d}.wav"
            wav.write_bytes(synthesize_chunk(chunk))
            wav_paths.append(wav)
        if len(wav_paths) == 1:
            _ffmpeg_run(
                [
                    _require_ffmpeg(),
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    *ffmpeg_thread_args(),
                    "-y",
                    "-i",
                    str(wav_paths[0]),
                    "-c:a",
                    "libmp3lame",
                    "-b:a",
                    "192k",
                    str(output),
                ]
            )
            return output
        list_file = tmpdir / "concat.txt"
        list_file.write_text("\n".join(f"file '{p.resolve()}'" for p in wav_paths), encoding="utf-8")
        merged = tmpdir / "merged.wav"
        _ffmpeg_run(
            [
                _require_ffmpeg(),
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                *ffmpeg_thread_args(),
                "-y",
                "-f",
                "concat",
                "-safe",
                "0",
                "-i",
                str(list_file),
                "-c",
                "copy",
                str(merged),
            ]
        )
        _ffmpeg_run(
            [
                _require_ffmpeg(),
                "-nostdin",
                "-hide_banner",
                "-loglevel",
                "error",
                *ffmpeg_thread_args(),
                "-y",
                "-i",
                str(merged),
                "-c:a",
                "libmp3lame",
                "-b:a",
                "192k",
                str(output),
            ]
        )
    return output


def synthesize_dub_audio(
    text: str,
    output: Path,
    *,
    target_lang: str,
    tts: str = "auto",
    voice: str | None = None,
) -> tuple[Path, str]:
    """Synthesize dubbed narration; return (path, provider)."""
    text = " ".join((text or "").split())
    if not text:
        raise SystemExit("Nothing to synthesize — transcript or translation was empty.")

    target = resolve_lang_code(target_lang) or target_lang
    base = target.split("-")[0].lower()
    mode = (tts or "auto").strip().lower()
    out = Path(output)
    out.parent.mkdir(parents=True, exist_ok=True)

    if mode in {"sarvam", "auto"} and base in INDIC_TTS_LANGS and os.environ.get("SARVAM_API_KEY", "").strip():
        prev = os.environ.get("SPEAK_LANG")
        os.environ["SPEAK_LANG"] = target_bcp47(target)
        try:
            return _sarvam_to_file(text, out, lang=target), "sarvam"
        finally:
            if prev is None:
                os.environ.pop("SPEAK_LANG", None)
            else:
                os.environ["SPEAK_LANG"] = prev

    if mode in {"edge", "auto", ""}:
        from arka.voice.edge_speak import synthesize_to_file

        locale = target_bcp47(target)
        prev = os.environ.get("SPEAK_LANG")
        os.environ["SPEAK_LANG"] = locale
        try:
            synthesize_to_file(text, out, voice=voice or None)
        finally:
            if prev is None:
                os.environ.pop("SPEAK_LANG", None)
            else:
                os.environ["SPEAK_LANG"] = prev
        return out, f"edge-tts ({locale})"

    raise SystemExit(f"Unsupported TTS mode {tts!r}. Use auto, edge, or sarvam.")


def dub_video(
    source: str | Path,
    target_lang: str,
    output: str | Path | None = None,
    *,
    source_lang: str = "auto",
    script: str | None = None,
    tts: str = "auto",
    voice: str | None = None,
    save_transcript: bool = True,
) -> dict[str, object]:
    """Transcribe (or use script), translate, TTS, and mux dubbed audio onto video."""
    src = Path(source).expanduser()
    if not src.is_file():
        raise FileNotFoundError(f"Media file not found: {src}")

    target = resolve_lang_code(target_lang) or target_lang.strip()
    if not target:
        raise SystemExit(f"Unknown target language: {target_lang!r}")

    dest = Path(output).expanduser() if output else default_output_path(src, f"dub-{target.split('-')[0]}")
    work_dir = dest.parent
    work_dir.mkdir(parents=True, exist_ok=True)

    from arka.core.skill_requirements import exit_if_blocked, preflight_skill

    checks = ["tts"] if (script or "").strip() else ["stt", "tts"]
    ok, msg = preflight_skill("dub_video", extra={"checks": checks})
    exit_if_blocked(ok, msg)

    transcript = (script or "").strip()
    if not transcript:
        print(f"Transcribing {src.name} …", file=sys.stderr)
        transcript = transcribe_file(src).strip()
    if not transcript:
        raise SystemExit("Transcription returned empty text — provide --script or check STT setup.")

    src_code = resolve_lang_code(source_lang) if source_lang != "auto" else "auto"
    print(f"Translating to {target} …", file=sys.stderr)
    translated = google_translate(transcript, target=target, source=src_code).strip()
    if not translated:
        raise SystemExit("Translation failed or returned empty text.")

    if save_transcript:
        stem = dest.stem
        (work_dir / f"{stem}.transcript.txt").write_text(transcript + "\n", encoding="utf-8")
        (work_dir / f"{stem}.translation.txt").write_text(translated + "\n", encoding="utf-8")

    audio_path = work_dir / f"{dest.stem}.dub.mp3"
    dubbed, provider = synthesize_dub_audio(translated, audio_path, target_lang=target, tts=tts, voice=voice)

    print(f"Merging dubbed audio ({provider}) …", file=sys.stderr)
    saved = mux_audio(src, dubbed, dest)

    return {
        "input": str(src),
        "output": str(saved),
        "target_lang": target,
        "source_lang": src_code,
        "transcript_chars": len(transcript),
        "translation_chars": len(translated),
        "tts_provider": provider,
        "audio_track": str(dubbed),
    }


def dub_video_result(
    path: str | Path,
    *,
    target_lang: str,
    output: str | Path | None = None,
    source_lang: str = "auto",
    script: str | None = None,
    tts: str = "auto",
    voice: str | None = None,
) -> dict[str, object]:
    return dub_video(
        path,
        target_lang,
        output,
        source_lang=source_lang,
        script=script,
        tts=tts,
        voice=voice,
    )


def nl_to_argv(text: str) -> list[str]:
    t = text.strip()
    if not t:
        return []

    m = re.search(
        rf"(?i)(?:dub|dubbing|voice[\s-]?over)\s+(?P<input>\S+\.{MEDIA_EXT})\s+(?:to|in|into)\s+(?P<lang>[a-zA-Z][\w-]*)",
        t,
    )
    if m:
        return ["dub", m.group("input"), "--target", m.group("lang")]

    m = re.search(
        rf"(?i)translate\s+and\s+dub\s+(?P<input>\S+\.{MEDIA_EXT})\s+(?:to|in|into)\s+(?P<lang>[a-zA-Z][\w-]*)",
        t,
    )
    if m:
        return ["dub", m.group("input"), "--target", m.group("lang")]

    m = re.search(
        rf"(?i)(?:dub|dubbing)\s+(?P<input>\S+\.{MEDIA_EXT})\s+(?P<lang>hindi|tamil|telugu|spanish|french|german|english|[a-z]{{2,3}})\b",
        t,
    )
    if m:
        return ["dub", m.group("input"), "--target", m.group("lang")]

    return []


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Dub video — transcribe, translate, TTS, mux (local ffmpeg + STT/TTS)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  dub_video dub reel.mp4 --target hindi\n"
            "  dub_video dub talk.mp4 --target es --source en\n"
            "  dub_video dub clip.mp4 --target ta --script narration.txt\n"
            "  dub_video check\n"
        ),
    )
    sub = p.add_subparsers(dest="command")

    p_dub = sub.add_parser("dub", help="Dub a video into another language")
    p_dub.add_argument("input", help="Input video or audio file")
    p_dub.add_argument("-t", "--target", required=True, help="Target language (hindi, es, ta, …)")
    p_dub.add_argument("-o", "--output", help="Output video path")
    p_dub.add_argument("--source", default="auto", help="Source language code (default: auto)")
    p_dub.add_argument("--script", help="Skip STT — read narration text from this file")
    p_dub.add_argument("--tts", default="auto", choices=["auto", "edge", "sarvam"], help="TTS backend")
    p_dub.add_argument("--voice", help="Explicit TTS voice id")
    p_dub.add_argument("--no-save-transcript", action="store_true")
    p_dub.set_defaults(func=cmd_dub)

    p_parse = sub.add_parser("parse", help="Parse natural language → dub_video args")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)

    p_check = sub.add_parser("check", help="Verify ffmpeg/ffprobe and TTS/STT hints")
    p_check.set_defaults(func=cmd_check)

    return p


def cmd_check(_args: argparse.Namespace) -> int:
    from arka.core.skill_requirements import check_requires, stt_backend_available, tts_backend_available

    ok, msg = check_requires(
        {
            "bins": ["ffmpeg", "ffprobe"],
            "checks": ["stt", "tts"],
            "note": "Pass --script to skip STT. Add keys to ~/.config/arka/.env",
        },
        skill="dub_video",
    )
    if not ok:
        print(msg, file=sys.stderr)
    else:
        print("✓ dub_video requirements look satisfied")
        print(f"  STT: {'yes' if stt_backend_available() else 'no'}")
        print(f"  TTS: {'yes' if tts_backend_available() else 'no'}")
    return 0 if ok else 1


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def cmd_dub(args: argparse.Namespace) -> int:
    script = None
    if args.script:
        script = Path(args.script).expanduser().read_text(encoding="utf-8")
    try:
        result = dub_video(
            args.input,
            args.target,
            args.output,
            source_lang=args.source,
            script=script,
            tts=args.tts,
            voice=args.voice,
            save_transcript=not args.no_save_transcript,
        )
    except (FileNotFoundError, SystemExit) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(json.dumps(result, indent=2))
    print(result["output"])
    return 0


_SUBCOMMANDS = {"dub", "parse", "check"}


def main(argv: list[str] | None = None) -> int:
    from arka.env import load_env

    load_env()
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        build_parser().print_help()
        return 0
    if argv[0] not in _SUBCOMMANDS | {"-h", "--help"}:
        nl = nl_to_argv(" ".join(argv))
        if nl:
            argv = nl
        else:
            build_parser().print_help()
            return 1
    parser = build_parser()
    args = parser.parse_args(argv)
    if not getattr(args, "func", None):
        parser.print_help()
        return 0
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())
