#!/usr/bin/env python3
"""Create videos locally with ffmpeg — slideshows, image+audio, and text slides."""

from __future__ import annotations

import argparse
import json
import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

from arka.core.compute import ffmpeg_thread_args
from arka.media.compose_video import _ffprobe_duration, _require_ffmpeg, _which
from arka.media.convert_media import IMAGE_EXTS

DEFAULT_FPS = 30
DEFAULT_WIDTH = 1920
DEFAULT_HEIGHT = 1080
DEFAULT_SLIDE_SEC = 3.0
DEFAULT_CRF = 23
DEFAULT_PRESET = "medium"

# Transparent outputs need ffmpeg built with libvpx-vp9 (webm), prores_ks (mov), or apng.
TRANSPARENT_FORMATS: dict[str, dict[str, object]] = {
    "webm-alpha": {
        "ext": ".webm",
        "vcodec": "libvpx-vp9",
        "pix_fmt": "yuva420p",
        "audio_codec": "libopus",
        "audio_bitrate": "128k",
        "extra_v": ["-auto-alt-ref", "0"],
        "crf": 30,
    },
    "mov-prores": {
        "ext": ".mov",
        "vcodec": "prores_ks",
        "pix_fmt": "yuva444p10le",
        "profile": "4444",
        "audio_codec": "aac",
        "audio_bitrate": "192k",
        "extra_v": [],
    },
    "mov-png": {
        "ext": ".mov",
        "vcodec": "png",
        "pix_fmt": "rgba",
        "audio_codec": "aac",
        "audio_bitrate": "192k",
        "extra_v": [],
    },
    "apng": {
        "ext": ".apng",
        "vcodec": "apng",
        "pix_fmt": "rgba",
        "audio_codec": None,
        "extra_v": [],
    },
    "gif": {
        "ext": ".gif",
        "vcodec": "gif",
        "pix_fmt": "rgb8",
        "audio_codec": None,
        "extra_v": [],
        "palette": True,
    },
}

OPAQUE_FORMAT: dict[str, object] = {
    "ext": ".mp4",
    "vcodec": "libx264",
    "pix_fmt": "yuv420p",
    "audio_codec": "aac",
    "audio_bitrate": "192k",
    "extra_v": [],
}

FORMAT_ALIASES = {
    "mp4": "mp4",
    "webm": "webm-alpha",
    "webm-alpha": "webm-alpha",
    "webm_alpha": "webm-alpha",
    "mov-prores": "mov-prores",
    "mov_prores": "mov-prores",
    "prores4444": "mov-prores",
    "mov-png": "mov-png",
    "mov_png": "mov-png",
    "apng": "apng",
    "gif": "gif",
}


@dataclass
class VideoSettings:
    width: int = DEFAULT_WIDTH
    height: int = DEFAULT_HEIGHT
    fps: int = DEFAULT_FPS
    crf: int = DEFAULT_CRF
    preset: str = DEFAULT_PRESET
    transparent: bool = False
    format: str = "mp4"


def _normalize_format_name(raw: str | None) -> str:
    key = (raw or "mp4").strip().lower()
    return FORMAT_ALIASES.get(key, key)


def resolve_output_format(
    *,
    transparent: bool = False,
    format_name: str | None = None,
    output: Path | None = None,
) -> tuple[str, dict[str, object]]:
    """Return (format_key, spec). Raises SystemExit on unsupported combinations."""
    fmt = _normalize_format_name(format_name)
    if output is not None:
        ext = output.suffix.lower()
        ext_map = {
            ".webm": "webm-alpha",
            ".mov": "mov-prores",
            ".apng": "apng",
            ".gif": "gif",
            ".mp4": "mp4",
        }
        if ext in ext_map and fmt == "mp4" and not transparent:
            fmt = ext_map[ext]
        elif ext in {".webm", ".apng", ".gif"} or (ext == ".mov" and fmt == "mp4"):
            transparent = True
            if fmt == "mp4":
                fmt = ext_map.get(ext, "webm-alpha")

    if transparent and fmt == "mp4":
        fmt = "webm-alpha"

    if fmt == "mp4":
        return "mp4", dict(OPAQUE_FORMAT)

    if fmt not in TRANSPARENT_FORMATS:
        supported = ", ".join(sorted(set(TRANSPARENT_FORMATS) | {"mp4"}))
        raise SystemExit(
            f"Unsupported output format {format_name!r}. "
            f"Transparent-capable formats: {supported}. "
            "Use --transparent with --format webm-alpha (default), mov-prores, mov-png, apng, or gif."
        )
    return fmt, dict(TRANSPARENT_FORMATS[fmt])


def _image_has_alpha(path: Path) -> bool:
    if path.suffix.lower() not in {".png", ".webp", ".gif", ".tiff", ".tif", ".apng"}:
        return False
    try:
        from PIL import Image
    except ImportError:
        return path.suffix.lower() == ".png"
    try:
        with Image.open(path) as im:
            return im.mode in ("RGBA", "LA", "PA") or "transparency" in im.info
    except OSError:
        return False


def _effective_settings(cfg: VideoSettings, images: list[Path] | None = None) -> VideoSettings:
    """Auto-enable transparency when PNG/WebP inputs carry alpha."""
    if cfg.transparent or cfg.format != "mp4":
        return cfg
    if images and any(_image_has_alpha(p) for p in images):
        return VideoSettings(
            width=cfg.width,
            height=cfg.height,
            fps=cfg.fps,
            crf=cfg.crf,
            preset=cfg.preset,
            transparent=True,
            format="webm-alpha",
        )
    return cfg


def _ffmpeg_run(cmd: list[str]) -> None:
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or str(proc.returncode)).strip()
        raise SystemExit(f"ffmpeg failed: {detail}")


def _scale_pad_filter(cfg: VideoSettings) -> str:
    scale = f"scale={cfg.width}:{cfg.height}:force_original_aspect_ratio=decrease"
    if cfg.transparent or cfg.format != "mp4":
        return (
            f"format=rgba,{scale},"
            f"pad={cfg.width}:{cfg.height}:(ow-iw)/2:(oh-ih)/2:color=0x00000000"
        )
    return f"{scale},pad={cfg.width}:{cfg.height}:(ow-iw)/2:(oh-ih)/2:color=black"


def _video_encode_args(cfg: VideoSettings, spec: dict[str, object]) -> list[str]:
    fmt_key = cfg.format if cfg.format != "mp4" else "mp4"
    args: list[str] = ["-c:v", str(spec["vcodec"])]
    profile = spec.get("profile")
    if profile:
        args.extend(["-profile:v", str(profile)])
    pix_fmt = spec.get("pix_fmt")
    if pix_fmt:
        args.extend(["-pix_fmt", str(pix_fmt)])
    if fmt_key == "mp4":
        args.extend(["-preset", cfg.preset, "-crf", str(cfg.crf)])
    elif spec.get("crf") is not None:
        args.extend(["-crf", str(spec["crf"])])
    for flag in spec.get("extra_v") or []:
        args.append(str(flag))
    if fmt_key == "mp4":
        args.extend(["-movflags", "+faststart"])
    return args


def _clip_suffix(spec: dict[str, object]) -> str:
    return str(spec.get("ext") or ".mp4")


def _is_image(path: Path) -> bool:
    return path.suffix.lower() in IMAGE_EXTS and path.is_file()


def collect_images(*sources: str | Path) -> list[Path]:
    """Collect image paths from files, directories, or globs."""
    found: list[Path] = []
    seen: set[str] = set()
    for raw in sources:
        path = Path(raw).expanduser()
        if path.is_dir():
            entries = sorted(
                p for p in path.iterdir() if _is_image(p)
            )
            if not entries:
                raise SystemExit(f"No images found in {path}")
            for entry in entries:
                key = str(entry.resolve())
                if key not in seen:
                    seen.add(key)
                    found.append(entry)
            continue
        if path.is_file() and _is_image(path):
            key = str(path.resolve())
            if key not in seen:
                seen.add(key)
                found.append(path)
            continue
        matches = sorted(Path().glob(str(path)) if not path.is_absolute() else path.parent.glob(path.name))
        hits = [m for m in matches if _is_image(m)]
        if hits:
            for entry in hits:
                key = str(entry.resolve())
                if key not in seen:
                    seen.add(key)
                    found.append(entry)
            continue
        raise FileNotFoundError(f"Image source not found: {raw}")
    if not found:
        raise SystemExit("No images to build video from.")
    return found


def default_output_path(*, mode: str = "slideshow", stem: str = "video", ext: str = ".mp4") -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", stem.lower())[:40].strip("-") or mode
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    candidates = [
        Path.home() / "Videos" / "arka-created",
        Path.cwd() / "arka-created-videos",
        Path(tempfile.gettempdir()) / "arka-created-videos",
    ]
    out_dir: Path | None = None
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        out_dir = candidate
        break
    if out_dir is None:
        out_dir = Path(tempfile.gettempdir()) / "arka-created-videos"
        out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{slug}-{ts}{ext}"


def _image_clip(
    image: Path,
    duration: float,
    output: Path,
    cfg: VideoSettings,
    spec: dict[str, object],
) -> None:
    ffmpeg = _require_ffmpeg()
    vf = _scale_pad_filter(cfg)
    if spec.get("palette"):
        filter_complex = (
            f"[0:v]{vf},split[s0][s1];[s0]palettegen=reserve_transparency=1[p];"
            f"[s1][p]paletteuse=alpha_threshold=128"
        )
        cmd = [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            *ffmpeg_thread_args(),
            "-y",
            "-loop",
            "1",
            "-i",
            str(image),
            "-filter_complex",
            filter_complex,
            "-r",
            str(cfg.fps),
            "-t",
            f"{duration:.3f}",
            "-an",
            *_video_encode_args(cfg, spec),
            str(output),
        ]
        _ffmpeg_run(cmd)
        return

    cmd = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        *ffmpeg_thread_args(),
        "-y",
        "-loop",
        "1",
        "-i",
        str(image),
        "-vf",
        vf,
        "-r",
        str(cfg.fps),
        "-t",
        f"{duration:.3f}",
        "-an",
    ]
    if cfg.format == "mp4":
        cmd.extend(["-tune", "stillimage"])
    cmd.extend(_video_encode_args(cfg, spec))
    cmd.append(str(output))
    _ffmpeg_run(cmd)


def _concat_videos(clips: list[Path], output: Path) -> None:
    ffmpeg = _require_ffmpeg()
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tmp:
        for clip in clips:
            tmp.write(f"file '{clip.as_posix()}'\n")
        list_path = Path(tmp.name)
    _ffmpeg_run(
        [
            ffmpeg,
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
            str(list_path),
            "-c",
            "copy",
            str(output),
        ]
    )
    list_path.unlink(missing_ok=True)


def _mux_av(
    video: Path,
    audio: Path | None,
    output: Path,
    cfg: VideoSettings,
    spec: dict[str, object],
) -> None:
    ffmpeg = _require_ffmpeg()
    audio_codec = spec.get("audio_codec")
    if audio_codec is None and audio and audio.is_file():
        raise SystemExit(
            f"Format {cfg.format!r} does not support audio tracks. "
            "Use webm-alpha, mov-prores, mov-png, or mp4 instead."
        )
    cmd = [
        ffmpeg,
        "-nostdin",
        "-hide_banner",
        "-loglevel",
        "error",
        *ffmpeg_thread_args(),
        "-y",
        "-i",
        str(video),
    ]
    if audio and audio.is_file():
        cmd.extend(["-i", str(audio), "-shortest"])
        if audio_codec:
            cmd.extend(["-c:a", str(audio_codec)])
            br = spec.get("audio_bitrate")
            if br:
                cmd.extend(["-b:a", str(br)])
    else:
        cmd.append("-an")
    cmd.extend(_video_encode_args(cfg, spec))
    cmd.append(str(output))
    _ffmpeg_run(cmd)


def create_slideshow(
    *sources: str | Path,
    output: str | Path | None = None,
    slide_duration: float = DEFAULT_SLIDE_SEC,
    audio: str | Path | None = None,
    cfg: VideoSettings | None = None,
) -> Path:
    """Build a video from one or more images or an image directory."""
    cfg = cfg or VideoSettings()
    images = collect_images(*sources)
    cfg = _effective_settings(cfg, images)
    fmt_key, spec = resolve_output_format(
        transparent=cfg.transparent,
        format_name=cfg.format,
        output=Path(output).expanduser() if output else None,
    )
    cfg = VideoSettings(
        width=cfg.width,
        height=cfg.height,
        fps=cfg.fps,
        crf=cfg.crf,
        preset=cfg.preset,
        transparent=cfg.transparent or fmt_key != "mp4",
        format=fmt_key,
    )
    dest = (
        Path(output).expanduser()
        if output
        else default_output_path(mode="slideshow", stem=images[0].stem, ext=str(spec["ext"]))
    )
    dest.parent.mkdir(parents=True, exist_ok=True)

    audio_path = Path(audio).expanduser() if audio else None
    if audio_path and not audio_path.is_file():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    clip_ext = _clip_suffix(spec)
    with tempfile.TemporaryDirectory(prefix="arka-create-video-") as tmpdir:
        work = Path(tmpdir)
        clips: list[Path] = []
        for idx, image in enumerate(images):
            clip = work / f"clip-{idx:03d}{clip_ext}"
            _image_clip(image, slide_duration, clip, cfg, spec)
            clips.append(clip)
        silent = work / f"silent{clip_ext}"
        _concat_videos(clips, silent)
        _mux_av(silent, audio_path, dest, cfg, spec)
    return dest


def create_image_audio(
    image: str | Path,
    audio: str | Path,
    output: str | Path | None = None,
    *,
    cfg: VideoSettings | None = None,
) -> Path:
    """Build a video from a single still image and an audio track."""
    cfg = cfg or VideoSettings()
    img = Path(image).expanduser()
    aud = Path(audio).expanduser()
    if not img.is_file():
        raise FileNotFoundError(f"Image not found: {img}")
    if not aud.is_file():
        raise FileNotFoundError(f"Audio not found: {aud}")

    cfg = _effective_settings(cfg, [img])
    fmt_key, spec = resolve_output_format(
        transparent=cfg.transparent,
        format_name=cfg.format,
        output=Path(output).expanduser() if output else None,
    )
    cfg = VideoSettings(
        width=cfg.width,
        height=cfg.height,
        fps=cfg.fps,
        crf=cfg.crf,
        preset=cfg.preset,
        transparent=cfg.transparent or fmt_key != "mp4",
        format=fmt_key,
    )

    duration = max(_ffprobe_duration(aud), 0.5)
    dest = (
        Path(output).expanduser()
        if output
        else default_output_path(mode="image-audio", stem=img.stem, ext=str(spec["ext"]))
    )
    dest.parent.mkdir(parents=True, exist_ok=True)

    clip_ext = _clip_suffix(spec)
    with tempfile.TemporaryDirectory(prefix="arka-create-video-") as tmpdir:
        work = Path(tmpdir)
        silent = work / f"silent{clip_ext}"
        _image_clip(img, duration, silent, cfg, spec)
        _mux_av(silent, aud, dest, cfg, spec)
    return dest


def _require_pillow():
    try:
        from PIL import Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise SystemExit(
            "Pillow is required for text slides.\n"
            "Install: pip install Pillow  or  pip install 'arka-agent[drawings]'"
        ) from exc
    return Image, ImageDraw, ImageFont


def _parse_text_slides(raw: str) -> list[dict[str, object]]:
    data = json.loads(raw)
    rows = data if isinstance(data, list) else data.get("slides") or []
    slides: list[dict[str, object]] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        body = str(row.get("body") or row.get("text") or "").strip()
        if not title and not body:
            continue
        duration = float(row.get("duration") or DEFAULT_SLIDE_SEC)
        slides.append({"title": title, "body": body, "duration": max(0.5, duration)})
    if not slides:
        raise SystemExit("Text slide script contains no usable slides.")
    return slides


def _render_text_slide(slide: dict[str, object], output: Path, cfg: VideoSettings) -> None:
    Image, ImageDraw, ImageFont = _require_pillow()
    if cfg.transparent or cfg.format != "mp4":
        canvas = Image.new("RGBA", (cfg.width, cfg.height), (0, 0, 0, 0))
        title_fill = (248, 250, 252, 255)
        body_fill = (226, 232, 240, 255)
    else:
        canvas = Image.new("RGB", (cfg.width, cfg.height), (15, 23, 42))
        title_fill = (248, 250, 252)
        body_fill = (226, 232, 240)
    draw = ImageDraw.Draw(canvas)
    title_font = ImageFont.load_default()
    body_font = ImageFont.load_default()
    y = cfg.height // 3
    title = str(slide.get("title") or "")
    body = str(slide.get("body") or "")
    if title:
        draw.text((cfg.width // 10, y), title, font=title_font, fill=title_fill)
        y += 48
    if body:
        draw.text((cfg.width // 10, y), body, font=body_font, fill=body_fill)
    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, format="PNG")


def create_text_slides(
    script: str | Path,
    output: str | Path | None = None,
    *,
    audio: str | Path | None = None,
    cfg: VideoSettings | None = None,
) -> Path:
    """Build a video from a JSON slide script."""
    cfg = cfg or VideoSettings()
    raw = Path(script).expanduser().read_text(encoding="utf-8") if Path(script).is_file() else str(script)
    slides = _parse_text_slides(raw)
    fmt_key, spec = resolve_output_format(
        transparent=cfg.transparent,
        format_name=cfg.format,
        output=Path(output).expanduser() if output else None,
    )
    cfg = VideoSettings(
        width=cfg.width,
        height=cfg.height,
        fps=cfg.fps,
        crf=cfg.crf,
        preset=cfg.preset,
        transparent=cfg.transparent or fmt_key != "mp4",
        format=fmt_key,
    )
    dest = (
        Path(output).expanduser()
        if output
        else default_output_path(mode="text-slides", ext=str(spec["ext"]))
    )
    dest.parent.mkdir(parents=True, exist_ok=True)
    audio_path = Path(audio).expanduser() if audio else None
    if audio_path and not audio_path.is_file():
        raise FileNotFoundError(f"Audio file not found: {audio_path}")

    clip_ext = _clip_suffix(spec)
    with tempfile.TemporaryDirectory(prefix="arka-create-video-") as tmpdir:
        work = Path(tmpdir)
        clips: list[Path] = []
        for idx, slide in enumerate(slides):
            png = work / f"slide-{idx:03d}.png"
            _render_text_slide(slide, png, cfg)
            clip = work / f"clip-{idx:03d}{clip_ext}"
            _image_clip(png, float(slide["duration"]), clip, cfg, spec)
            clips.append(clip)
        silent = work / f"silent{clip_ext}"
        _concat_videos(clips, silent)
        _mux_av(silent, audio_path, dest, cfg, spec)
    return dest


def _settings_from_args(args: argparse.Namespace) -> VideoSettings:
    transparent = bool(getattr(args, "transparent", False))
    fmt_raw = getattr(args, "format", None)
    if fmt_raw:
        fmt = _normalize_format_name(fmt_raw)
        transparent = transparent or fmt != "mp4"
    elif transparent:
        fmt = "webm-alpha"
    else:
        fmt = "mp4"
    return VideoSettings(transparent=transparent, format=fmt)


def create_video_result(
    mode: str,
    *,
    sources: list[str] | None = None,
    image: str | None = None,
    audio: str | None = None,
    script: str | None = None,
    output: str | None = None,
    slide_duration: float = DEFAULT_SLIDE_SEC,
    transparent: bool = False,
    alpha: bool = False,
    format_name: str | None = None,
) -> dict[str, object]:
    cfg = VideoSettings(
        transparent=transparent or alpha,
        format=_normalize_format_name(format_name or ("webm-alpha" if (transparent or alpha) else "mp4")),
    )
    mode = mode.strip().lower()
    if mode in {"slideshow", "slides", "images"}:
        if not sources:
            raise ValueError("sources is required for slideshow mode")
        saved = create_slideshow(
            *sources,
            output=output,
            slide_duration=slide_duration,
            audio=audio,
            cfg=cfg,
        )
    elif mode in {"image-audio", "image_audio", "still"}:
        if not image or not audio:
            raise ValueError("image and audio are required for image-audio mode")
        saved = create_image_audio(image, audio, output=output, cfg=cfg)
    elif mode in {"text", "text-slides", "text_slides"}:
        if not script:
            raise ValueError("script is required for text mode")
        saved = create_text_slides(script, output=output, audio=audio, cfg=cfg)
    else:
        raise ValueError(f"unsupported mode: {mode}")
    return {
        "mode": mode,
        "output": str(saved),
        "sources": sources or [],
        "image": image,
        "audio": audio,
        "script": script,
        "transparent": cfg.transparent or cfg.format != "mp4",
        "format": cfg.format,
    }


def _nl_output_flags(t: str, argv: list[str]) -> list[str]:
    out = list(argv)
    if re.search(r"(?i)\b(?:transparent|with alpha|alpha channel)\b", t):
        out.append("--transparent")
    fmt = re.search(
        r"(?i)\b(?:as|to|format)\s+(webm(?:-alpha)?|mov-prores|mov-png|apng|gif)\b",
        t,
    )
    if fmt:
        out.extend(["--format", fmt.group(1).lower()])
    return out


def nl_to_argv(text: str) -> list[str]:
    t = text.strip()
    if not t:
        return []

    # Avoid compose_video topic intents ("video on/about X").
    if re.search(r"(?i)\bvideo\s+(?:on|about|for|explaining)\s+\S", t):
        return []
    if re.search(r"(?i)\b(?:youtube|info|tech|explainer)\s+video\b", t):
        return []

    image_ext = r"(?:png|jpe?g|webp|gif|bmp|tiff?)"
    audio_ext = r"(?:mp3|wav|aac|m4a|flac|ogg|opus)"
    media_ext = rf"(?:{image_ext}|{audio_ext}|mp4)"

    image_audio = re.search(
        rf"(?i)(?:create|make|build|render|generate)\s+(?:a\s+)?video\s+from\s+"
        rf"(?P<image>\S+\.{image_ext})\s+(?:with|and|using)\s+(?:audio\s+)?(?P<audio>\S+\.{audio_ext})\b",
        t,
    )
    if image_audio:
        return [
            "image-audio",
            "--image",
            image_audio.group("image"),
            "--audio",
            image_audio.group("audio"),
        ]

    slideshow_dir = re.search(
        r"(?i)(?:create|make|build|render|generate)\s+(?:a\s+)?(?:slideshow|video)\s+from\s+"
        r"(?:images?\s+in\s+)?(?P<dir>[^\s]+/?)\b",
        t,
    )
    if slideshow_dir:
        target = slideshow_dir.group("dir").rstrip("/")
        if not re.search(rf"\.{image_ext}$", target, re.I):
            argv = ["slideshow", target]
            dur = re.search(r"(?i)\b(\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds?)\s+(?:per\s+)?(?:slide|image)\b", t)
            if dur:
                argv.extend(["--duration", dur.group(1)])
            audio = re.search(rf"(?i)\bwith\s+(?:audio|music|track)\s+(?P<audio>\S+\.{audio_ext})\b", t)
            if audio:
                argv.extend(["--audio", audio.group("audio")])
            return argv

    if re.search(r"(?i)\bslideshow\b", t):
        paths = re.findall(rf"\S+\.{image_ext}\b", t, flags=re.I)
        if paths:
            argv = ["slideshow", *paths]
            dur = re.search(r"(?i)\b(\d+(?:\.\d+)?)\s*(?:s|sec|secs|seconds?)\b", t)
            if dur:
                argv.extend(["--duration", dur.group(1)])
            audio = re.search(rf"(?i)\bwith\s+(?:audio|music|track)\s+(?P<audio>\S+\.{audio_ext})\b", t)
            if audio:
                argv.extend(["--audio", audio.group("audio")])
            return argv

    text_slides = re.search(
        r"(?i)(?:create|make|build|render|generate)\s+(?:a\s+)?video\s+from\s+(?:text\s+)?slides?\s+(?P<script>\S+\.(?:json|md))\b",
        t,
    )
    if text_slides:
        return ["text", "--script", text_slides.group("script")]

    single_image = re.search(
        rf"(?i)(?:create|make|build|render|generate)\s+(?:a\s+)?(?:transparent\s+)?video\s+from\s+"
        rf"(?P<image>\S+\.{image_ext})\b",
        t,
    )
    if single_image:
        return _nl_output_flags(t, ["slideshow", single_image.group("image")])

    tail_image = re.search(rf"(?i)(\S+\.{image_ext})\s*$", t)
    if tail_image and re.search(r"(?i)\b(?:create|make|build|render|generate)\b.*\bvideo\b", t):
        return _nl_output_flags(t, ["slideshow", tail_image.group(1)])

    if re.search(r"(?i)\bcreate[\s_-]?video\b|\bmake[\s_-]?video\b|\bvideo[\s_-]?create\b", t):
        paths = re.findall(rf"\S+\.{media_ext}\b", t, flags=re.I)
        images = [p for p in paths if re.search(rf"\.{image_ext}$", p, re.I)]
        audios = [p for p in paths if re.search(rf"\.{audio_ext}$", p, re.I)]
        argv: list[str] = []
        if len(images) == 1 and audios:
            argv = ["image-audio", "--image", images[0], "--audio", audios[0]]
        elif len(images) >= 2:
            argv = ["slideshow", *images]
            if audios:
                argv.extend(["--audio", audios[0]])
        elif len(images) == 1:
            argv = ["slideshow", images[0]]
        if argv:
            return _nl_output_flags(t, argv)

    return []


def _add_output_flags(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "-o",
        "--output",
        help="Output path (.mp4, .webm, .mov, .apng, .gif)",
    )
    parser.add_argument(
        "--transparent",
        "--alpha",
        action="store_true",
        dest="transparent",
        help="Preserve alpha — defaults to webm-alpha (VP9 + yuva420p)",
    )
    parser.add_argument(
        "--format",
        choices=sorted(set(TRANSPARENT_FORMATS) | {"mp4"}),
        help="Output container/codec (webm-alpha, mov-prores, mov-png, apng, gif, mp4)",
    )


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Create videos with ffmpeg — slideshows, image+audio, text slides, alpha output",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=(
            "Examples:\n"
            "  create_video slideshow ./photos/ -o out.mp4 --duration 4\n"
            "  create_video slideshow logo.png --transparent -o logo.webm\n"
            "  create_video slideshow frames/ --format mov-prores -o out.mov\n"
            "  create_video image-audio cover.png --audio narration.mp3\n"
            "  create_video text --script slides.json\n"
            "  create_video check\n"
            "\n"
            "Transparent formats: webm-alpha (VP9/yuva420p), mov-prores (ProRes 4444), "
            "mov-png, apng, gif. PNG inputs with alpha auto-select webm-alpha.\n"
        ),
    )
    sub = p.add_subparsers(dest="command")

    p_show = sub.add_parser("slideshow", help="Build a video from images or a folder")
    p_show.add_argument("sources", nargs="+", help="Image files or a directory of images")
    _add_output_flags(p_show)
    p_show.add_argument(
        "-d",
        "--duration",
        type=float,
        default=DEFAULT_SLIDE_SEC,
        help=f"Seconds per slide (default: {DEFAULT_SLIDE_SEC})",
    )
    p_show.add_argument("--audio", help="Optional background audio track")
    p_show.set_defaults(func=cmd_slideshow)

    p_ia = sub.add_parser("image-audio", help="Single image with an audio track")
    p_ia.add_argument("--image", required=True, help="Still image path")
    p_ia.add_argument("--audio", required=True, help="Audio path")
    _add_output_flags(p_ia)
    p_ia.set_defaults(func=cmd_image_audio)

    p_text = sub.add_parser("text", help="Build a video from a JSON slide script")
    p_text.add_argument("--script", required=True, help="JSON file or inline JSON")
    p_text.add_argument("--audio", help="Optional narration audio")
    _add_output_flags(p_text)
    p_text.set_defaults(func=cmd_text)

    p_parse = sub.add_parser("parse", help="Parse natural language → create_video args")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)

    p_check = sub.add_parser("check", help="Verify ffmpeg is installed")
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
    if _which("ffprobe"):
        print("✓ ffprobe")
    else:
        print("  ffprobe not found (optional for image+audio duration)")
    try:
        _require_pillow()
        print("✓ Pillow (text slides)")
    except SystemExit:
        print("  Pillow not installed (needed for text slides only)")
    print("Modes: slideshow, image-audio, text")
    print("Transparent: --transparent / --format webm-alpha|mov-prores|mov-png|apng|gif")
    return 0 if ok else 1


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def cmd_slideshow(args: argparse.Namespace) -> int:
    print(
        f"Creating slideshow from {len(args.sources)} source(s), "
        f"{args.duration:g}s per slide",
        file=sys.stderr,
    )
    cfg = _settings_from_args(args)
    try:
        saved = create_slideshow(
            *args.sources,
            output=args.output,
            slide_duration=args.duration,
            audio=args.audio,
            cfg=cfg,
        )
    except (FileNotFoundError, SystemExit) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(saved)
    return 0


def cmd_image_audio(args: argparse.Namespace) -> int:
    print(f"Creating video from {args.image} + {args.audio}", file=sys.stderr)
    cfg = _settings_from_args(args)
    try:
        saved = create_image_audio(args.image, args.audio, output=args.output, cfg=cfg)
    except (FileNotFoundError, SystemExit) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    print(saved)
    return 0


def cmd_text(args: argparse.Namespace) -> int:
    print("Creating video from text slides", file=sys.stderr)
    cfg = _settings_from_args(args)
    try:
        saved = create_text_slides(args.script, output=args.output, audio=args.audio, cfg=cfg)
    except (FileNotFoundError, SystemExit) as exc:
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
    if argv[0] not in {"slideshow", "image-audio", "text", "parse", "check", "-h", "--help"}:
        if argv[0] == "check":
            argv = ["check"]
        else:
            nl = nl_to_argv(" ".join(argv))
            if nl:
                argv = nl
            elif Path(argv[0]).is_dir() or (
                Path(argv[0]).suffix.lower() in IMAGE_EXTS and Path(argv[0]).is_file()
            ):
                argv = ["slideshow", *argv]
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
