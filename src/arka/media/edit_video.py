#!/usr/bin/env python3
"""Basic video editing with ffmpeg — trim, concat, text overlay, extract audio, crop, resize."""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from pathlib import Path

from arka.core.compute import ffmpeg_thread_args
from arka.media.compose_video import _concat_videos, _ffprobe_duration, _require_ffmpeg, _which
from arka.media.convert_media import AUDIO_EXTS, VIDEO_EXTS, detect_media_type

MEDIA_EXT = r"(?:mp4|webm|mov|avi|mkv|m4v|mp3|wav|aac|m4a|flac|ogg|opus|wma)"


def _num_str(value: float) -> str:
    return str(int(value)) if value == int(value) else str(value)


def _ffmpeg_run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or str(proc.returncode)).strip()
        raise SystemExit(f"ffmpeg failed: {detail}")


def _require_video(path: Path) -> None:
    if detect_media_type(path) != "video":
        raise SystemExit(f"Expected a video file, got {path.name!r}.")


def _require_media(path: Path) -> None:
    kind = detect_media_type(path)
    if kind not in {"video", "audio"}:
        raise SystemExit(f"Unsupported media file {path.name!r} (type={kind!r}).")


def default_output_path(source: Path, suffix: str, ext: str | None = None) -> Path:
    out_ext = ext or source.suffix or ".mp4"
    return source.with_name(f"{source.stem}-{suffix}{out_ext}")


def trim_video(
    source: str | Path,
    output: str | Path | None = None,
    *,
    start: float = 0.0,
    duration: float | None = None,
    end: float | None = None,
) -> Path:
    """Trim a video (or audio) file to a time range."""
    src = Path(source).expanduser()
    if not src.is_file():
        raise FileNotFoundError(f"Media file not found: {src}")
    _require_media(src)

    if end is not None and duration is not None:
        raise SystemExit("Specify either duration or end, not both.")
    if end is not None:
        duration = max(0.0, end - start)
    if duration is None or duration <= 0:
        raise SystemExit("duration or end is required for trim.")

    dest = Path(output).expanduser() if output else default_output_path(src, "trimmed")
    dest.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg = _require_ffmpeg()
    cmd = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        *ffmpeg_thread_args(),
        "-y",
        "-ss",
        f"{start:.3f}",
        "-i",
        str(src),
        "-t",
        f"{duration:.3f}",
        "-c",
        "copy",
        str(dest),
    ]
    _ffmpeg_run(cmd)
    return dest


def concat_videos(
    sources: list[str | Path],
    output: str | Path,
) -> Path:
    """Concatenate video files in order (same codec/resolution recommended)."""
    if len(sources) < 2:
        raise SystemExit("concat requires at least two input files.")
    clips: list[Path] = []
    for src in sources:
        p = Path(src).expanduser()
        if not p.is_file():
            raise FileNotFoundError(f"Media file not found: {p}")
        _require_video(p)
        clips.append(p)

    dest = Path(output).expanduser()
    dest.parent.mkdir(parents=True, exist_ok=True)
    _concat_videos(clips, dest)
    return dest


def overlay_text(
    source: str | Path,
    text: str,
    output: str | Path | None = None,
    *,
    position: str = "bottom",
    fontsize: int = 48,
    color: str = "white",
    fontfile: str | None = None,
) -> Path:
    """Burn text onto a video using ffmpeg drawtext."""
    src = Path(source).expanduser()
    if not src.is_file():
        raise FileNotFoundError(f"Video file not found: {src}")
    _require_video(src)

    dest = Path(output).expanduser() if output else default_output_path(src, "captioned")
    dest.parent.mkdir(parents=True, exist_ok=True)

    pos_map = {
        "top": "x=(w-text_w)/2:y=40",
        "center": "x=(w-text_w)/2:y=(h-text_h)/2",
        "bottom": "x=(w-text_w)/2:y=h-text_h-40",
    }
    pos_expr = pos_map.get(position.lower(), pos_map["bottom"])

    # Escape drawtext special chars.
    escaped = text.replace("\\", "\\\\").replace(":", "\\:").replace("'", "\\'")

    drawtext = f"drawtext=text='{escaped}':fontsize={fontsize}:fontcolor={color}:{pos_expr}"
    if fontfile:
        drawtext += f":fontfile={fontfile}"

    ffmpeg = _require_ffmpeg()
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
        "-vf",
        drawtext,
        "-c:a",
        "copy",
        str(dest),
    ]
    _ffmpeg_run(cmd)
    return dest


def extract_audio(
    source: str | Path,
    output: str | Path | None = None,
    *,
    format: str = "mp3",
) -> Path:
    """Extract audio track from a video file."""
    src = Path(source).expanduser()
    if not src.is_file():
        raise FileNotFoundError(f"Video file not found: {src}")
    _require_video(src)

    fmt = format.lower().lstrip(".")
    ext_map = {"mp3": ".mp3", "wav": ".wav", "aac": ".aac", "m4a": ".m4a", "flac": ".flac", "ogg": ".ogg"}
    ext = ext_map.get(fmt, f".{fmt}")
    dest = Path(output).expanduser() if output else default_output_path(src, "audio", ext=ext)
    dest.parent.mkdir(parents=True, exist_ok=True)

    codec_map = {
        "mp3": ("libmp3lame", "192k"),
        "wav": ("pcm_s16le", None),
        "aac": ("aac", "192k"),
        "m4a": ("aac", "192k"),
        "flac": ("flac", None),
        "ogg": ("libvorbis", "192k"),
    }
    codec, bitrate = codec_map.get(fmt, ("aac", "192k"))

    ffmpeg = _require_ffmpeg()
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
        "-vn",
        "-c:a",
        codec,
    ]
    if bitrate:
        cmd.extend(["-b:a", bitrate])
    cmd.append(str(dest))
    _ffmpeg_run(cmd)
    return dest


def crop_video(
    source: str | Path,
    output: str | Path | None = None,
    *,
    width: int,
    height: int,
    x: int = 0,
    y: int = 0,
) -> Path:
    """Crop a video to width x height starting at (x, y)."""
    src = Path(source).expanduser()
    if not src.is_file():
        raise FileNotFoundError(f"Video file not found: {src}")
    _require_video(src)

    dest = Path(output).expanduser() if output else default_output_path(src, "cropped")
    dest.parent.mkdir(parents=True, exist_ok=True)

    vf = f"crop={width}:{height}:{x}:{y}"
    ffmpeg = _require_ffmpeg()
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
        "-vf",
        vf,
        "-c:a",
        "copy",
        str(dest),
    ]
    _ffmpeg_run(cmd)
    return dest


def resize_video(
    source: str | Path,
    output: str | Path | None = None,
    *,
    width: int | None = None,
    height: int | None = None,
) -> Path:
    """Resize a video (maintains aspect ratio if only one dimension given)."""
    src = Path(source).expanduser()
    if not src.is_file():
        raise FileNotFoundError(f"Video file not found: {src}")
    _require_video(src)
    if width is None and height is None:
        raise SystemExit("At least one of width or height is required for resize.")

    dest = Path(output).expanduser() if output else default_output_path(src, "resized")
    dest.parent.mkdir(parents=True, exist_ok=True)

    if width and height:
        scale = f"scale={width}:{height}"
    elif width:
        scale = f"scale={width}:-2"
    else:
        scale = f"scale=-2:{height}"

    ffmpeg = _require_ffmpeg()
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
        "-vf",
        scale,
        "-c:a",
        "copy",
        str(dest),
    ]
    _ffmpeg_run(cmd)
    return dest


def mux_audio(
    video: str | Path,
    audio: str | Path,
    output: str | Path | None = None,
    *,
    shortest: bool = True,
) -> Path:
    """Mux an audio track onto a video (replaces or adds audio)."""
    vid = Path(video).expanduser()
    aud = Path(audio).expanduser()
    if not vid.is_file():
        raise FileNotFoundError(f"Video file not found: {vid}")
    if not aud.is_file():
        raise FileNotFoundError(f"Audio file not found: {aud}")
    _require_video(vid)
    if detect_media_type(aud) != "audio":
        raise SystemExit(f"Expected an audio file, got {aud.name!r}.")

    dest = Path(output).expanduser() if output else default_output_path(vid, "muxed")
    dest.parent.mkdir(parents=True, exist_ok=True)

    ffmpeg = _require_ffmpeg()
    cmd = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        *ffmpeg_thread_args(),
        "-y",
        "-i",
        str(vid),
        "-i",
        str(aud),
        "-map",
        "0:v:0",
        "-map",
        "1:a:0",
        "-c:v",
        "copy",
        "-c:a",
        "aac",
        "-b:a",
        "192k",
    ]
    if shortest:
        cmd.append("-shortest")
    cmd.append(str(dest))
    _ffmpeg_run(cmd)
    return dest


def media_info(path: str | Path) -> dict[str, object]:
    src = Path(path).expanduser()
    kind = detect_media_type(src)
    info: dict[str, object] = {
        "input": str(src),
        "media_kind": kind,
        "duration_sec": _ffprobe_duration(src) if kind in {"video", "audio"} else 0.0,
    }
    return info


def edit_video_result(
    action: str,
    *,
    path: str | Path | None = None,
    paths: list[str] | None = None,
    output: str | Path | None = None,
    start: float = 0.0,
    duration: float | None = None,
    end: float | None = None,
    text: str | None = None,
    position: str = "bottom",
    fontsize: int = 48,
    color: str = "white",
    width: int | None = None,
    height: int | None = None,
    x: int = 0,
    y: int = 0,
    format: str = "mp3",
    audio: str | Path | None = None,
    shortest: bool = True,
) -> dict[str, object]:
    """Run an edit action and return structured result."""
    act = action.strip().lower().replace("_", "-")
    if act == "trim":
        if not path:
            raise ValueError("path is required for trim")
        saved = trim_video(path, output, start=start, duration=duration, end=end)
    elif act == "concat":
        inputs = paths or ([path] if path else [])
        if not inputs:
            raise ValueError("paths (or path) is required for concat")
        if not output:
            raise ValueError("output is required for concat")
        saved = concat_videos(inputs, output)
    elif act in {"overlay-text", "overlay"}:
        if not path or not text:
            raise ValueError("path and text are required for overlay-text")
        saved = overlay_text(path, text, output, position=position, fontsize=fontsize, color=color)
    elif act in {"extract-audio", "extract"}:
        if not path:
            raise ValueError("path is required for extract-audio")
        saved = extract_audio(path, output, format=format)
    elif act == "crop":
        if not path or width is None or height is None:
            raise ValueError("path, width, and height are required for crop")
        saved = crop_video(path, output, width=width, height=height, x=x, y=y)
    elif act == "resize":
        if not path:
            raise ValueError("path is required for resize")
        saved = resize_video(path, output, width=width, height=height)
    elif act in {"mux-audio", "mux"}:
        if not path or not audio:
            raise ValueError("path and audio are required for mux-audio")
        saved = mux_audio(path, audio, output, shortest=shortest)
    else:
        raise ValueError(f"Unknown action: {action}")
    return {"action": act, "input": path or paths, "output": str(saved)}


def nl_to_argv(text: str) -> list[str]:
    t = text.strip()
    if not t:
        return []

    # Trim: "trim clip.mp4 from 10 to 30 seconds" / "cut first 5 seconds of video.mp4"
    m = re.search(
        rf"(?i)(?:trim|cut)\s+(?P<input>\S+\.{MEDIA_EXT})\s+(?:from\s+)?(?P<start>\d+(?:\.\d+)?)\s*(?:s|sec|seconds)?\s+to\s+(?P<end>\d+(?:\.\d+)?)",
        t,
    )
    if m:
        start = float(m.group("start"))
        end = float(m.group("end"))
        return ["trim", m.group("input"), "--start", _num_str(start), "--end", _num_str(end)]

    m = re.search(
        rf"(?i)(?:trim|cut)\s+(?:first\s+)?(?P<dur>\d+(?:\.\d+)?)\s*(?:s|sec|seconds)?\s+(?:of\s+|from\s+)?(?P<input>\S+\.{MEDIA_EXT})",
        t,
    )
    if m:
        return ["trim", m.group("input"), "--start", "0", "--duration", m.group("dur")]

    m = re.search(
        rf"(?i)(?:trim|cut)\s+(?P<input>\S+\.{MEDIA_EXT})\s+(?:starting\s+at\s+)?(?P<start>\d+(?:\.\d+)?)\s*(?:for\s+)?(?P<dur>\d+(?:\.\d+)?)\s*(?:s|sec|seconds)?",
        t,
    )
    if m:
        return [
            "trim",
            m.group("input"),
            "--start",
            m.group("start"),
            "--duration",
            m.group("dur"),
        ]

    # Concat: "concat a.mp4 b.mp4 c.mp4" / "join video1.mp4 and video2.mp4"
    m = re.search(rf"(?i)(?:concat|join|merge|combine)\s+(?P<files>(?:\S+\.{MEDIA_EXT}\s*)+)", t)
    if m:
        files = re.findall(rf"\S+\.{MEDIA_EXT}", m.group("files"), flags=re.I)
        if len(files) >= 2:
            return ["concat", *files]

    # Overlay: 'add text "Hello" to video.mp4' / 'overlay "Title" on clip.mp4'
    m = re.search(
        rf"""(?i)(?:add\s+text|overlay|caption)\s+["'](?P<text>[^"']+)["']\s+(?:to|on)\s+(?P<input>\S+\.{MEDIA_EXT})""",
        t,
    )
    if m:
        return ["overlay-text", m.group("input"), "--text", m.group("text")]

    m = re.search(
        rf"""(?i)(?:add\s+text|overlay|caption)\s+(?P<input>\S+\.{MEDIA_EXT})\s+(?:with|text)\s+["'](?P<text>[^"']+)["']""",
        t,
    )
    if m:
        return ["overlay-text", m.group("input"), "--text", m.group("text")]

    # Extract audio
    m = re.search(
        rf"(?i)(?:extract|rip|get)\s+audio\s+(?:from\s+)?(?P<input>\S+\.{MEDIA_EXT})",
        t,
    )
    if m:
        return ["extract-audio", m.group("input")]

    # Crop: "crop video.mp4 to 1920x1080" / "crop clip.mp4 1280x720"
    m = re.search(
        rf"(?i)crop\s+(?P<input>\S+\.{MEDIA_EXT})\s+(?:to\s+)?(?P<w>\d+)x(?P<h>\d+)",
        t,
    )
    if m:
        return ["crop", m.group("input"), "--width", m.group("w"), "--height", m.group("h")]

    # Resize: "resize video.mp4 to 1280x720" / "scale clip.mp4 width 1920"
    m = re.search(
        rf"(?i)(?:resize|scale)\s+(?P<input>\S+\.{MEDIA_EXT})\s+(?:to\s+)?(?P<w>\d+)x(?P<h>\d+)",
        t,
    )
    if m:
        return ["resize", m.group("input"), "--width", m.group("w"), "--height", m.group("h")]

    m = re.search(
        rf"(?i)(?:resize|scale)\s+(?P<input>\S+\.{MEDIA_EXT})\s+width\s+(?P<w>\d+)",
        t,
    )
    if m:
        return ["resize", m.group("input"), "--width", m.group("w")]

    # Mux audio: "add audio narration.mp3 to video.mp4" / "mux voiceover.wav with clip.mp4"
    m = re.search(
        rf"""(?i)(?:add|attach|mux)\s+audio\s+(?P<audio>\S+\.{MEDIA_EXT})\s+(?:to|onto|with)\s+(?P<input>\S+\.{MEDIA_EXT})""",
        t,
    )
    if m:
        return ["mux-audio", m.group("input"), "--audio", m.group("audio")]

    m = re.search(
        rf"""(?i)mux\s+(?P<input>\S+\.{MEDIA_EXT})\s+(?:with|and)\s+(?P<audio>\S+\.{MEDIA_EXT})""",
        t,
    )
    if m:
        return ["mux-audio", m.group("input"), "--audio", m.group("audio")]

    return []


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Basic video editing with ffmpeg — trim, concat, overlay, extract, crop, resize",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  edit_video trim clip.mp4 --start 5 --duration 10\n"
            "  edit_video concat part1.mp4 part2.mp4 -o full.mp4\n"
            "  edit_video overlay-text reel.mp4 --text 'Subscribe!'\n"
            "  edit_video extract-audio talk.mp4\n"
            "  edit_video crop video.mp4 --width 1080 --height 1920\n"
            "  edit_video resize clip.mp4 --width 1280\n"
            "  edit_video mux-audio clip.mp4 --audio narration.mp3\n"
        ),
    )
    sub = p.add_subparsers(dest="command")

    p_trim = sub.add_parser("trim", help="Trim a video or audio file")
    p_trim.add_argument("input", help="Input media file")
    p_trim.add_argument("--start", type=float, default=0.0, help="Start offset in seconds")
    p_trim.add_argument("--duration", type=float, help="Duration in seconds")
    p_trim.add_argument("--end", type=float, help="End time in seconds (alternative to duration)")
    p_trim.add_argument("-o", "--output", help="Output path")
    p_trim.set_defaults(func=cmd_trim)

    p_concat = sub.add_parser("concat", help="Concatenate video files")
    p_concat.add_argument("inputs", nargs="+", help="Input video files in order")
    p_concat.add_argument("-o", "--output", required=True, help="Output path")
    p_concat.set_defaults(func=cmd_concat)

    p_overlay = sub.add_parser("overlay-text", help="Burn text onto a video")
    p_overlay.add_argument("input", help="Input video file")
    p_overlay.add_argument("--text", "-t", required=True, help="Text to overlay")
    p_overlay.add_argument(
        "--position",
        choices=["top", "center", "bottom"],
        default="bottom",
        help="Text position",
    )
    p_overlay.add_argument("--fontsize", type=int, default=48)
    p_overlay.add_argument("--color", default="white")
    p_overlay.add_argument("-o", "--output", help="Output path")
    p_overlay.set_defaults(func=cmd_overlay)

    p_extract = sub.add_parser("extract-audio", help="Extract audio from a video")
    p_extract.add_argument("input", help="Input video file")
    p_extract.add_argument("-o", "--output", help="Output path")
    p_extract.add_argument("--format", default="mp3", help="Output audio format (mp3, wav, aac, …)")
    p_extract.set_defaults(func=cmd_extract)

    p_crop = sub.add_parser("crop", help="Crop a video")
    p_crop.add_argument("input", help="Input video file")
    p_crop.add_argument("--width", type=int, required=True)
    p_crop.add_argument("--height", type=int, required=True)
    p_crop.add_argument("--x", type=int, default=0)
    p_crop.add_argument("--y", type=int, default=0)
    p_crop.add_argument("-o", "--output", help="Output path")
    p_crop.set_defaults(func=cmd_crop)

    p_resize = sub.add_parser("resize", help="Resize a video")
    p_resize.add_argument("input", help="Input video file")
    p_resize.add_argument("--width", type=int)
    p_resize.add_argument("--height", type=int)
    p_resize.add_argument("-o", "--output", help="Output path")
    p_resize.set_defaults(func=cmd_resize)

    p_mux = sub.add_parser("mux-audio", help="Mux an audio track onto a video")
    p_mux.add_argument("input", help="Input video file")
    p_mux.add_argument("--audio", "-a", required=True, help="Audio file to mux")
    p_mux.add_argument("-o", "--output", help="Output path")
    p_mux.add_argument(
        "--no-shortest",
        action="store_true",
        help="Do not trim output to the shorter stream",
    )
    p_mux.set_defaults(func=cmd_mux)

    p_parse = sub.add_parser("parse", help="Parse natural language → edit_video args")
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
    ffprobe = _which("ffprobe")
    if ffprobe:
        print("✓ ffprobe")
    else:
        print("✗ ffprobe — install ffmpeg (bundled with ffprobe)", file=sys.stderr)
        ok = False
    print("Actions: trim, concat, overlay-text, extract-audio, crop, resize, mux-audio")
    return 0 if ok else 1


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def cmd_trim(args: argparse.Namespace) -> int:
    src = Path(args.input).expanduser()
    print(f"Trimming {src.name} (start={args.start}, duration={args.duration}, end={args.end})", file=sys.stderr)
    try:
        saved = trim_video(src, args.output, start=args.start, duration=args.duration, end=args.end)
    except (FileNotFoundError, SystemExit) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(saved)
    return 0


def cmd_concat(args: argparse.Namespace) -> int:
    print(f"Concatenating {len(args.inputs)} clips → {args.output}", file=sys.stderr)
    try:
        saved = concat_videos(args.inputs, args.output)
    except (FileNotFoundError, SystemExit) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(saved)
    return 0


def cmd_overlay(args: argparse.Namespace) -> int:
    src = Path(args.input).expanduser()
    print(f"Adding text overlay to {src.name}", file=sys.stderr)
    try:
        saved = overlay_text(
            src,
            args.text,
            args.output,
            position=args.position,
            fontsize=args.fontsize,
            color=args.color,
        )
    except (FileNotFoundError, SystemExit) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(saved)
    return 0


def cmd_extract(args: argparse.Namespace) -> int:
    src = Path(args.input).expanduser()
    print(f"Extracting audio from {src.name}", file=sys.stderr)
    try:
        saved = extract_audio(src, args.output, format=args.format)
    except (FileNotFoundError, SystemExit) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(saved)
    return 0


def cmd_crop(args: argparse.Namespace) -> int:
    src = Path(args.input).expanduser()
    print(f"Cropping {src.name} to {args.width}x{args.height}", file=sys.stderr)
    try:
        saved = crop_video(src, args.output, width=args.width, height=args.height, x=args.x, y=args.y)
    except (FileNotFoundError, SystemExit) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(saved)
    return 0


def cmd_resize(args: argparse.Namespace) -> int:
    src = Path(args.input).expanduser()
    print(f"Resizing {src.name}", file=sys.stderr)
    try:
        saved = resize_video(src, args.output, width=args.width, height=args.height)
    except (FileNotFoundError, SystemExit) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(saved)
    return 0


def cmd_mux(args: argparse.Namespace) -> int:
    src = Path(args.input).expanduser()
    aud = Path(args.audio).expanduser()
    print(f"Muxing {aud.name} onto {src.name}", file=sys.stderr)
    try:
        saved = mux_audio(src, aud, args.output, shortest=not args.no_shortest)
    except (FileNotFoundError, SystemExit) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(saved)
    return 0


_SUBCOMMANDS = {"trim", "concat", "overlay-text", "extract-audio", "crop", "resize", "mux-audio", "parse", "check"}


def main(argv: list[str] | None = None) -> int:
    from arka.env import load_env

    load_env()
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        build_parser().print_help()
        return 0
    if argv[0] not in _SUBCOMMANDS | {"-h", "--help"}:
        if Path(argv[0]).suffix.lower() in VIDEO_EXTS | AUDIO_EXTS:
            # Bare file path — show help
            build_parser().print_help()
            return 0
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
