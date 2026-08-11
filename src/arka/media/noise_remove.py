#!/usr/bin/env python3
"""Remove background noise from audio and video files using ffmpeg afftdn."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import tempfile
from pathlib import Path

from arka.core.compute import ffmpeg_thread_args
from arka.media.compose_video import _require_ffmpeg, _which
from arka.media.convert_media import AUDIO_EXTS, VIDEO_EXTS, detect_media_type

MediaKind = str  # audio | video

MEDIA_EXT = r"(?:mp4|webm|mov|avi|mkv|m4v|mp3|wav|aac|m4a|flac|ogg|opus|wma)"
DEFAULT_STRENGTH = 12
MIN_STRENGTH = 0
MAX_STRENGTH = 97

AUDIO_CODEC = {
    ".mp3": ("libmp3lame", "192k"),
    ".aac": ("aac", "192k"),
    ".m4a": ("aac", "192k"),
    ".wav": ("pcm_s16le", None),
    ".flac": ("flac", None),
    ".ogg": ("libvorbis", "192k"),
    ".opus": ("libopus", "128k"),
    ".wma": ("wmav2", "192k"),
}


def detect_av_kind(path: Path) -> MediaKind:
    """Return audio or video for supported media paths."""
    media_type = detect_media_type(path)
    if media_type == "audio":
        return "audio"
    if media_type == "video":
        return "video"
    raise SystemExit(
        f"Unsupported input {path.name!r} — noise removal supports audio/video files only "
        f"(got {media_type!r})."
    )


def _ffmpeg_run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or str(proc.returncode)).strip()
        raise SystemExit(f"ffmpeg failed: {detail}")


def _require_ffprobe() -> str:
    ffprobe = _which("ffprobe")
    if not ffprobe:
        raise SystemExit(
            "ffprobe is required for video noise removal — install ffmpeg (includes ffprobe): "
            "brew install ffmpeg  or  sudo apt install ffmpeg"
        )
    return ffprobe


def _has_audio_stream(path: Path) -> bool:
    ffprobe = _require_ffprobe()
    proc = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-select_streams",
            "a",
            "-show_entries",
            "stream=codec_type",
            "-of",
            "csv=p=0",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    return proc.returncode == 0 and bool((proc.stdout or "").strip())


def _afftdn_filter(*, strength: float, noise_floor: float | None = None) -> str:
    nr = max(MIN_STRENGTH, min(MAX_STRENGTH, float(strength)))
    parts = [f"nr={nr:g}"]
    if noise_floor is not None:
        parts.append(f"nf={noise_floor:g}")
    return "afftdn=" + ":".join(parts)


def _audio_codec_for(path: Path) -> tuple[str, str | None]:
    ext = path.suffix.lower()
    if ext in AUDIO_CODEC:
        return AUDIO_CODEC[ext]
    return "aac", "192k"


def default_output_path(source: Path, *, audio_only: bool = False) -> Path:
    ext = source.suffix.lower()
    if audio_only and ext not in AUDIO_EXTS:
        return source.with_name(f"{source.stem}-denoised.wav")
    return source.with_name(f"{source.stem}-denoised{source.suffix or '.wav'}")


def remove_noise(
    source: str | Path,
    output: str | Path | None = None,
    *,
    strength: float = DEFAULT_STRENGTH,
    noise_floor: float | None = None,
    audio_only: bool = False,
) -> Path:
    """Denoise an audio or video file. Video keeps the original video stream when possible."""
    src = Path(source).expanduser()
    if not src.is_file():
        raise FileNotFoundError(f"Media file not found: {src}")

    ffmpeg = _require_ffmpeg()
    kind = detect_av_kind(src)
    dest = Path(output).expanduser() if output else default_output_path(src, audio_only=audio_only or kind == "audio")
    dest.parent.mkdir(parents=True, exist_ok=True)

    if kind == "video" and not _has_audio_stream(src):
        raise SystemExit(f"No audio stream found in {src.name!r} — nothing to denoise.")

    if kind == "video" and not audio_only:
        codec, bitrate = _audio_codec_for(dest)
        cmd = [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            *ffmpeg_thread_args(),
            "-y",
            "-i",
            str(src),
            "-af",
            _afftdn_filter(strength=strength, noise_floor=noise_floor),
            "-map",
            "0:v:0?",
            "-map",
            "0:a:0",
            "-c:v",
            "copy",
            "-c:a",
            codec,
        ]
        if bitrate:
            cmd.extend(["-b:a", bitrate])
        cmd.append(str(dest))
        _ffmpeg_run(cmd)
        return dest

    # Audio-only output (explicit flag or audio input).
    with tempfile.TemporaryDirectory(prefix="arka-noise-remove-") as tmp:
        raw = Path(tmp) / f"raw{src.suffix or '.wav'}"
        if kind == "video":
            _ffmpeg_run(
                [
                    ffmpeg,
                    "-nostdin",
                    "-hide_banner",
                    "-loglevel",
                    "error",
                    *ffmpeg_thread_args(),
                    "-y",
                    "-i",
                    str(src),
                    "-vn",
                    "-c:a",
                    "pcm_s16le",
                    str(raw),
                ]
            )
            input_for_denoise = raw
        else:
            input_for_denoise = src

        codec, bitrate = _audio_codec_for(dest)
        cmd = [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            *ffmpeg_thread_args(),
            "-y",
            "-i",
            str(input_for_denoise),
            "-af",
            _afftdn_filter(strength=strength, noise_floor=noise_floor),
            "-c:a",
            codec,
        ]
        if bitrate:
            cmd.extend(["-b:a", bitrate])
        cmd.append(str(dest))
        _ffmpeg_run(cmd)
    return dest


def media_info(path: str | Path) -> dict[str, object]:
    src = Path(path).expanduser()
    kind = detect_av_kind(src)
    info: dict[str, object] = {
        "input": str(src),
        "media_kind": kind,
        "has_audio": _has_audio_stream(src) if kind == "video" else True,
        "default_output": str(default_output_path(src)),
    }
    return info


def noise_remove_result(
    source: str | Path,
    *,
    output: str | Path | None = None,
    strength: float = DEFAULT_STRENGTH,
    noise_floor: float | None = None,
    audio_only: bool = False,
) -> dict[str, object]:
    saved = remove_noise(
        source,
        output,
        strength=strength,
        noise_floor=noise_floor,
        audio_only=audio_only,
    )
    return {
        "input": str(Path(source).expanduser()),
        "output": str(saved),
        "strength": strength,
        "audio_only": audio_only,
    }


def nl_to_argv(text: str) -> list[str]:
    t = text.strip()
    if not t:
        return []
    if re.search(r"(?i)\bnoise[\s-]?cancell", t):
        return []

    patterns = [
        rf"(?i)(?:remove|reduce|clean(?:\s+up)?)\s+(?:background\s+)?noise\s+(?:from\s+)?(?P<input>\S+\.{MEDIA_EXT})\b",
        rf"(?i)(?:denoise|de-noise)\s+(?:audio\s+|video\s+)?(?P<input>\S+\.{MEDIA_EXT})\b",
        rf"(?i)(?:noise[_\s-]?remove|noise removal)\s+(?P<input>\S+\.{MEDIA_EXT})\b",
        rf"(?i)(?P<input>\S+\.{MEDIA_EXT})\s+(?:with\s+)?(?:noise\s+removed|denoised|cleaned)\b",
        rf"(?i)^(?:please\s+)?(?:remove|clean)\s+noise\s+(?P<input>\S+\.{MEDIA_EXT})\b",
    ]
    for pat in patterns:
        m = re.search(pat, t)
        if not m:
            continue
        argv = [m.group("input")]
        if re.search(r"(?i)\baudio[\s-]?only\b|\bextract\s+audio\b", t):
            argv.append("--audio-only")
        strength = re.search(r"(?i)\b(?:strength|level)\s+(\d+(?:\.\d+)?)\b", t)
        if strength:
            argv.extend(["--strength", strength.group(1)])
        return argv

    tail = re.search(rf"(?i)(\S+\.{MEDIA_EXT})\s*$", t)
    if tail and re.search(r"(?i)\b(?:remove|reduce|clean|denoise)\b.*\bnoise\b", t):
        return [tail.group(1)]
    return []


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Remove background noise from audio or video files (ffmpeg afftdn)",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  noise_remove interview.wav\n"
            "  noise_remove clip.mp4 --strength 18\n"
            "  noise_remove webinar.mp4 --audio-only -o clean.wav\n"
            "  noise_remove check\n"
        ),
    )
    sub = p.add_subparsers(dest="command")

    p_remove = sub.add_parser("remove", help="Denoise a media file")
    p_remove.add_argument("input", help="Input audio or video file")
    p_remove.add_argument("-o", "--output", help="Output path (default: <name>-denoised.<ext>)")
    p_remove.add_argument(
        "-s",
        "--strength",
        type=float,
        default=DEFAULT_STRENGTH,
        help=f"Noise reduction strength 0–{MAX_STRENGTH} dB (default: {DEFAULT_STRENGTH})",
    )
    p_remove.add_argument(
        "--noise-floor",
        type=float,
        help="Optional afftdn noise floor in dB (-80 to -20)",
    )
    p_remove.add_argument(
        "--audio-only",
        action="store_true",
        help="For video input, export denoised audio only (no video remux)",
    )
    p_remove.set_defaults(func=cmd_remove)

    p_parse = sub.add_parser("parse", help="Parse natural language → noise_remove args")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)

    p_check = sub.add_parser("check", help="Verify ffmpeg/ffprobe are installed")
    p_check.set_defaults(func=cmd_check)

    return p


def cmd_check(_args: argparse.Namespace) -> int:
    ok = True
    try:
        _require_ffmpeg()
        print("✓ ffmpeg")
    except SystemExit:
        print("✗ ffmpeg — brew install ffmpeg  or  sudo apt install ffmpeg", file=sys.stderr)
        ok = False
    try:
        _require_ffprobe()
        print("✓ ffprobe")
    except SystemExit:
        print("✗ ffprobe — install ffmpeg (bundled with ffprobe)", file=sys.stderr)
        ok = False
    print("Filter: afftdn (Adaptive FFT Denoiser, built into ffmpeg)")
    return 0 if ok else 1


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def cmd_remove(args: argparse.Namespace) -> int:
    src = Path(args.input).expanduser()
    print(f"Denoising {src.name} (strength={args.strength:g})", file=sys.stderr)
    try:
        saved = remove_noise(
            src,
            args.output,
            strength=args.strength,
            noise_floor=args.noise_floor,
            audio_only=args.audio_only,
        )
    except FileNotFoundError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    except SystemExit as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(saved)
    return 0


def main(argv: list[str] | None = None) -> int:
    from arka.env import load_env

    load_env()
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        build_parser().print_help()
        return 0
    if argv[0] not in {"remove", "parse", "check", "-h", "--help"}:
        if argv[0] == "check":
            argv = ["check"]
        elif Path(argv[0]).suffix.lower() in AUDIO_EXTS | VIDEO_EXTS:
            argv = ["remove", *argv]
        else:
            nl = nl_to_argv(" ".join(argv))
            if nl:
                argv = ["remove", *nl]
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
