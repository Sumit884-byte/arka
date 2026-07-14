#!/usr/bin/env python3
"""Compose YouTube-style info videos — Unsplash B-roll, custom fonts, ffmpeg (headless)."""

from __future__ import annotations

import argparse
import ast
import json
import os
import re
import shlex
import shutil
import subprocess
import sys
import tempfile
import textwrap
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from arka.core.compute import ffmpeg_thread_args
from arka.media.stock_photos import (
    StockPhoto,
    any_source_available,
    compact_photo_query,
    diverse_photo_queries,
    download_stock_photo,
    photo_uid,
    search_stock_photos,
    setup_hint as stock_setup_hint,
    stock_search_query,
)
from arka.media.unsplash import access_key


@dataclass
class Scene:
    title: str
    narration: str = ""
    body: str = ""
    captions: list[str] = field(default_factory=list)
    image_query: str = ""
    image_keywords: list[str] = field(default_factory=list)
    duration: float = 0.0
    photo: StockPhoto | None = None
    chart: dict | None = None
    chart_path: str = ""
    slide_image: str = ""


@dataclass
class VideoConfig:
    width: int = 1920
    height: int = 1080
    fps: int = 30
    font_path: Path | None = None
    font_bold_path: Path | None = None
    title_size: int = 72
    body_size: int = 42
    bg_color: str = "#0f172a"
    text_color: str = "#f8fafc"
    accent_color: str = "#38bdf8"
    scene_sec: float = 5.0
    crf: int = 18
    preset: str = "medium"
    tts: str = "edge"
    tts_voice: str = ""
    orientation: str = "landscape"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _env_int(name: str, default: int) -> int:
    raw = _env(name)
    if not raw:
        return default
    try:
        return int(raw)
    except ValueError:
        return default


def _env_float(name: str, default: float) -> float:
    raw = _env(name)
    if not raw:
        return default
    try:
        return float(raw)
    except ValueError:
        return default


def load_config() -> VideoConfig:
    from arka.voice.edge_speak import resolve_voice

    font_path = _env("VIDEO_FONT_PATH")
    font_bold = _env("VIDEO_FONT_BOLD_PATH") or _env("VIDEO_FONT_BOLD")
    explicit_voice = _env("VIDEO_TTS_VOICE") or _env("SPEAK_VOICE") or None
    return VideoConfig(
        width=_env_int("VIDEO_WIDTH", 1920),
        height=_env_int("VIDEO_HEIGHT", 1080),
        fps=_env_int("VIDEO_FPS", 30),
        font_path=_resolve_font(_env("VIDEO_FONT", "Inter"), explicit=font_path),
        font_bold_path=_resolve_font(
            font_bold or _env("VIDEO_FONT", "Inter-Bold"),
            explicit=_env("VIDEO_FONT_BOLD_PATH"),
            bold=True,
        ),
        title_size=_env_int("VIDEO_TITLE_FONT_SIZE", _env_int("VIDEO_FONT_SIZE", 58)),
        body_size=_env_int("VIDEO_BODY_FONT_SIZE", 34),
        bg_color=_env("VIDEO_BG_COLOR", "#0f172a"),
        text_color=_env("VIDEO_TEXT_COLOR", "#f8fafc"),
        accent_color=_env("VIDEO_ACCENT_COLOR", "#38bdf8"),
        scene_sec=_env_float("VIDEO_SCENE_SEC", 5.0),
        crf=_env_int("VIDEO_CRF", 18),
        preset=_env("VIDEO_PRESET", "medium") or "medium",
        tts=_env("VIDEO_TTS", "edge").lower() or "edge",
        tts_voice=resolve_voice(voice=explicit_voice),
        orientation=_env("VIDEO_ORIENTATION", "landscape") or "landscape",
    )


def _resolve_font(name: str, *, explicit: str = "", bold: bool = False) -> Path | None:
    if explicit:
        path = Path(explicit).expanduser()
        if path.is_file():
            return path
    if not name:
        name = "Inter-Bold" if bold else "Inter"
    roots = [
        Path.home() / "Library/Fonts",
        Path("/System/Library/Fonts/Supplemental"),
        Path("/System/Library/Fonts"),
        Path("/Library/Fonts"),
        Path("/usr/share/fonts/truetype/dejavu"),
        Path("/usr/share/fonts/truetype/liberation"),
        Path("/usr/share/fonts/truetype/noto"),
    ]
    names = [name, f"{name}.ttf", f"{name}.otf", name.replace(" ", "")]
    for root in roots:
        if not root.is_dir():
            continue
        for candidate in names:
            hit = root / candidate
            if hit.is_file():
                return hit
        for hit in root.rglob("*.ttf"):
            if name.lower().replace(" ", "") in hit.stem.lower().replace(" ", ""):
                return hit
    fallback = Path("/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf" if bold else "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf")
    if fallback.is_file():
        return fallback
    mac = Path("/System/Library/Fonts/Supplemental/Arial Bold.ttf" if bold else "/System/Library/Fonts/Supplemental/Arial.ttf")
    return mac if mac.is_file() else None


def _which(name: str) -> str | None:
    return shutil.which(name)


def _require_ffmpeg() -> str:
    ffmpeg = _which("ffmpeg")
    if not ffmpeg:
        raise SystemExit("ffmpeg is required — install: brew install ffmpeg  or  sudo apt install ffmpeg")
    return ffmpeg


def _require_pillow():
    try:
        from PIL import Image, ImageDraw, ImageFilter, ImageFont
    except ImportError as exc:
        raise SystemExit(
            "Pillow is required for video slides.\nInstall: pip install Pillow  or  pip install 'arka-agent[drawings]'"
        ) from exc
    return Image, ImageDraw, ImageFilter, ImageFont


TOPIC_ALIASES: dict[str, str] = {
    "ai": "Artificial Intelligence",
    "ml": "Machine Learning",
    "dl": "Deep Learning",
    "nlp": "Natural Language Processing",
    "llm": "Large Language Models",
    "api": "APIs",
    "gpu": "GPUs",
    "cpu": "CPUs",
}

_GENERIC_BODIES = frozenset(
    {
        "intro",
        "summary",
        "core concepts",
        "real-world impact",
        "takeaways",
        "key ideas",
        "why it matters",
    }
)

_BROLL_STOPWORDS = frozenset(
    {
        "a",
        "an",
        "the",
        "and",
        "or",
        "of",
        "in",
        "on",
        "for",
        "with",
        "to",
        "at",
        "by",
        "from",
        "into",
        "about",
        "over",
        "under",
        "via",
        "what",
        "when",
        "where",
        "which",
        "that",
        "this",
        "your",
        "their",
        "have",
        "has",
        "will",
        "should",
        "would",
        "could",
        "also",
        "more",
        "most",
        "very",
        "make",
        "made",
        "buy",
        "best",
        "good",
        "better",
        "versus",
        "vs",
    }
)

_DURATION_UNIT_SECONDS = {
    "s": 1,
    "sec": 1,
    "secs": 1,
    "second": 1,
    "seconds": 1,
    "m": 60,
    "min": 60,
    "mins": 60,
    "minute": 60,
    "minutes": 60,
    "h": 3600,
    "hr": 3600,
    "hrs": 3600,
    "hour": 3600,
    "hours": 3600,
}

_DURATION_PHRASE = re.compile(
    r"(?i)\b(\d+(?:\.\d+)?)\s*"
    r"(?:hours?|hrs?|h|minutes?|mins?|min|seconds?|secs?|sec)\b"
    r"(?:\s*(?:long|runtime|run\s*time))?"
)


def _words_per_minute() -> int:
    return max(100, _env_int("VIDEO_WORDS_PER_MIN", 150))


def parse_duration_value(raw: str) -> float:
    """Parse CLI duration: 19m, 1h30m, 90s, or bare minutes (19 → 19 min)."""
    text = raw.strip().lower()
    if not text:
        raise ValueError("empty duration")

    total = 0.0
    for match in re.finditer(
        r"(\d+(?:\.\d+)?)\s*(hours?|hrs?|h|minutes?|mins?|min|seconds?|secs?|sec|s)\b",
        text,
    ):
        value = float(match.group(1))
        unit = match.group(2)
        multiplier = _DURATION_UNIT_SECONDS.get(unit, 60)
        total += value * multiplier
    if total > 0:
        return total

    compact = re.fullmatch(r"(\d+(?:\.\d+)?)([smh]|min|mins|minute|minutes|hour|hours|hr|hrs)?", text)
    if compact:
        value = float(compact.group(1))
        unit = compact.group(2) or "m"
        if unit == "s" and value > 180:
            return value
        if unit in {"m", "min", "mins", "minute", "minutes"} or (unit is None and value <= 180):
            return value * 60
        if unit in {"h", "hr", "hrs", "hour", "hours"}:
            return value * 3600
        return value

    if re.fullmatch(r"\d+(?:\.\d+)?", text):
        value = float(text)
        return value * 60 if value <= 180 else value
    raise ValueError(f"invalid duration: {raw}")


def parse_duration_seconds(text: str) -> float | None:
    """Extract target runtime from natural language (e.g. '19 minute video on AI')."""
    total = 0.0
    for match in _DURATION_PHRASE.finditer(text):
        chunk = match.group(0)
        try:
            total += parse_duration_value(chunk)
        except ValueError:
            continue
    return total if total > 0 else None


def format_duration_arg(seconds: float) -> str:
    seconds = int(round(seconds))
    if seconds >= 3600 and seconds % 3600 == 0:
        return f"{seconds // 3600}h"
    if seconds >= 60 and seconds % 60 == 0:
        return f"{seconds // 60}m"
    return f"{seconds}s"


def strip_duration_phrases(text: str) -> str:
    cleaned = _DURATION_PHRASE.sub(" ", text)
    cleaned = re.sub(
        r"(?i)\b(?:for|lasting|length\s+of|runtime\s+of|duration\s+of)\s+",
        " ",
        cleaned,
    )
    cleaned = re.sub(r"\s+", " ", cleaned).strip(" ,.-")
    return cleaned


def _scenes_for_duration(seconds: float) -> int:
    min_s, max_s = _scene_bounds()
    # ~2.5 minutes per scene by default
    per_scene = max(120.0, _env_float("VIDEO_SCENE_TARGET_SEC", 150.0))
    return min(max_s, max(min_s, int(round(seconds / per_scene))))


def _apply_target_duration(scenes: list[Scene], total_seconds: float) -> None:
    if total_seconds <= 0 or not scenes:
        return
    per_scene = total_seconds / len(scenes)
    for scene in scenes:
        scene.duration = max(scene.duration, per_scene)


def _pad_audio_to_duration(input_path: Path, target_duration: float, output_path: Path) -> None:
    ffmpeg = _require_ffmpeg()
    current = _ffprobe_duration(input_path)
    if current >= target_duration - 0.05:
        shutil.copy2(input_path, output_path)
        return
    proc = subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            "-y",
            "-i",
            str(input_path),
            "-af",
            f"apad=pad_dur={target_duration - current:.3f}",
            "-t",
            f"{target_duration:.3f}",
            str(output_path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"ffmpeg audio pad failed: {(proc.stderr or proc.stdout).strip()}")


def extract_video_topic(text: str) -> str:
    """Pull the subject out of NL like 'generate a 19 minute video on ai'."""
    t = text.strip().strip("'\"")
    if not t:
        return ""
    duration_gap = r"(?:(?:\d+(?:\.\d+)?\s*(?:hours?|hrs?|h|minutes?|mins?|min|seconds?|secs?|sec)\s+)+)?"
    patterns = [
        rf"(?i)(?:^|\b)(?:please\s+)?(?:make|create|compose|build|render|produce|generate|arka)\s+"
        rf"(?:a\s+|an\s+)?{duration_gap}(?:(?:youtube|info|tech|explainer)\s+)?video\s+"
        r"(?:on|about|for|explaining)\s+(.+)$",
        rf"(?i)(?:^|\b)(?:please\s+)?(?:make|create|compose|build|render|produce|generate|arka)\s+"
        rf"(?:a\s+|an\s+)?{duration_gap}video\s+(?:on|about|for|explaining)\s+(.+)$",
        r"(?i)(?:^|\b)(?:youtube|info|tech|explainer)\s+video\s+(?:on|about|for|explaining)\s+(.+)$",
        rf"(?i)(?:^|\b)(?:make|create|compose|build|render|produce|generate|arka)\s+"
        rf"{duration_gap}video\s+(?:on|about|for|explaining)\s+(.+)$",
        rf"(?i)^compose\s+{duration_gap}video\s+(?:on|about|for|explaining)\s+(.+)$",
    ]
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            topic = m.group(1).strip().strip("'\"")
            topic = re.sub(r"(?i)\s+(?:with\s+llm|please)$", "", topic).strip()
            topic = strip_duration_phrases(topic)
            if topic:
                return topic
    return t


def normalize_topic(raw: str) -> str:
    topic = extract_video_topic(raw)
    topic = strip_duration_phrases(topic)
    topic = re.sub(r"(?i)\s+(?:video|please)$", "", topic).strip(" '\"")
    if not topic:
        return strip_duration_phrases(raw.strip())
    return topic


def topic_label(topic: str) -> str:
    key = topic.strip().lower()
    if key in TOPIC_ALIASES:
        return TOPIC_ALIASES[key]
    if re.fullmatch(r"[a-z]{2,5}", key):
        return key.upper()
    return topic.strip().title()


def _normalize_scene_text(value: object) -> str:
    """Turn body/narration fields into plain slide text (never a list repr)."""
    if value is None:
        return ""
    if isinstance(value, list):
        parts = [str(v).strip() for v in value if str(v).strip()]
        if not parts:
            return ""
        if len(parts) == 1:
            return parts[0]
        return "\n".join(f"• {p}" for p in parts)
    if isinstance(value, dict):
        return ""
    text = str(value).strip()
    if text.startswith("[") and text.endswith("]"):
        for loader in (json.loads, ast.literal_eval):
            try:
                parsed = loader(text)
            except (json.JSONDecodeError, ValueError, SyntaxError):
                continue
            if isinstance(parsed, list):
                return _normalize_scene_text(parsed)
    return text


def _slide_title_max_lines() -> int:
    return max(1, _env_int("VIDEO_TITLE_MAX_LINES", 2))


def _slide_body_max_lines() -> int:
    return max(0, _env_int("VIDEO_BODY_MAX_LINES", 2))


def _slide_body_max_chars() -> int:
    return max(20, _env_int("VIDEO_BODY_MAX_CHARS", 100))


def _slide_title_wrap_width() -> int:
    return max(12, _env_int("VIDEO_TITLE_WRAP_WIDTH", 28))


def _slide_body_wrap_width() -> int:
    return max(12, _env_int("VIDEO_BODY_WRAP_WIDTH", 32))


def _truncate_slide_text(text: str, max_chars: int) -> str:
    text = text.strip()
    if len(text) <= max_chars:
        return text
    cut = text[: max_chars + 1].rsplit(" ", 1)[0].strip()
    if not cut:
        cut = text[:max_chars].strip()
    return cut.rstrip(".,;:") + "…"


def prepare_slide_title(title: str) -> list[str]:
    title = _normalize_scene_text(title).strip()
    if not title:
        return []
    lines = textwrap.wrap(title, width=_slide_title_wrap_width())
    return lines[: _slide_title_max_lines()]


def prepare_slide_body(body: str) -> list[str]:
    body = _normalize_scene_text(body).strip()
    if not body:
        return []
    body = _truncate_slide_text(body, _slide_body_max_chars())
    lines: list[str] = []
    for paragraph in body.split("\n"):
        paragraph = paragraph.strip()
        if not paragraph:
            continue
        for line in textwrap.wrap(paragraph, width=_slide_body_wrap_width()):
            lines.append(line)
            if len(lines) >= _slide_body_max_lines():
                return lines
    return lines


def _caption_beat_fits(text: str) -> bool:
    text = text.strip()
    if not text:
        return False
    if len(text) > _slide_body_max_chars():
        return False
    return len(prepare_slide_body(text)) <= _slide_body_max_lines()


def _split_long_caption(text: str) -> list[str]:
    max_chars = _slide_body_max_chars()
    parts = re.split(r"[,;:\-—]\s+", text.strip())
    beats: list[str] = []
    current = ""
    for part in parts:
        if not part.strip():
            continue
        candidate = f"{current}, {part}".strip() if current else part.strip()
        if _caption_beat_fits(candidate):
            current = candidate
            continue
        if current:
            beats.append(current)
            current = ""
        if _caption_beat_fits(part):
            current = part.strip()
            continue
        words = part.split()
        chunk = ""
        for word in words:
            candidate = f"{chunk} {word}".strip() if chunk else word
            if len(candidate) <= max_chars:
                chunk = candidate
            else:
                if chunk:
                    beats.append(chunk)
                chunk = word
        current = chunk
    if current:
        beats.append(current)
    return beats


def _split_caption_beats(text: str) -> list[str]:
    text = _normalize_scene_text(text).strip()
    if not text:
        return []
    if _caption_beat_fits(text):
        return [text]
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()] or [text]
    beats: list[str] = []
    current = ""
    for sent in sents:
        candidate = f"{current} {sent}".strip() if current else sent
        if _caption_beat_fits(candidate):
            current = candidate
            continue
        if current:
            beats.append(current)
            current = ""
        if _caption_beat_fits(sent):
            current = sent
        else:
            beats.extend(_split_long_caption(sent))
    if current:
        beats.append(current)
    return [beat for beat in beats if beat.strip()]


def caption_beats_for_scene(scene: Scene) -> list[str]:
    if scene.captions:
        return [caption.strip() for caption in scene.captions if caption.strip()]
    narration = scene.narration.strip()
    if narration:
        beats = _split_caption_beats(narration)
        if beats:
            return beats
    body = scene.body.strip()
    if body and body.lower() not in _GENERIC_BODIES:
        return _split_caption_beats(body) or [body]
    return []


def _max_caption_beats() -> int:
    return max(2, _env_int("VIDEO_MAX_CAPTION_BEATS", 6))


def _estimate_caption_beats(scene: Scene) -> int:
    beats = caption_beats_for_scene(scene)
    return max(1, len(beats))


def _script_needs_shortening(scenes: list[Scene]) -> bool:
    limit = _max_caption_beats()
    return any(_estimate_caption_beats(scene) > limit for scene in scenes)


def _active_segment_value(segments: list[tuple[float, str]], time_offset: float) -> str:
    if not segments:
        return ""
    active = segments[0][1]
    elapsed = 0.0
    for duration, value in segments:
        if time_offset >= elapsed - 0.001:
            active = value
        elapsed += duration
    return active


def _schedule_caption_beats(narration: str, beats: list[str], total_duration: float) -> list[tuple[float, str]]:
    if total_duration <= 0:
        return [(total_duration, beats[0] if beats else "")]
    if not beats:
        return [(total_duration, "")]
    if len(beats) == 1:
        return [(total_duration, beats[0])]

    min_segment = _broll_min_segment_sec()
    total_chars = sum(len(beat) for beat in beats) or 1
    segments = [
        (max(min_segment, (len(beat) / total_chars) * total_duration), beat) for beat in beats
    ]
    assigned = sum(duration for duration, _ in segments)
    if assigned > 0 and abs(assigned - total_duration) > 0.05:
        scale = total_duration / assigned
        segments = [(duration * scale, beat) for duration, beat in segments]
    tail = total_duration - sum(duration for duration, _ in segments)
    if segments and abs(tail) > 0.05:
        last_d, last_b = segments[-1]
        segments[-1] = (last_d + tail, last_b)
    return _merge_short_segments(segments, min_segment)


def _schedule_scene_timeline(
    narration: str,
    image_query: str,
    total_duration: float,
    *,
    fallback_query: str,
    captions: list[str] | None = None,
    image_keywords: list[str] | None = None,
) -> list[tuple[float, str, str]]:
    """Return (duration, search_query, body_text) segments."""
    beats = captions if captions else _split_caption_beats(narration)
    if not beats and narration.strip():
        beats = [_caption_from_narration(narration)]
    cap_segments = _schedule_caption_beats(narration, beats, total_duration)
    broll_segments = _schedule_broll_segments(
        narration,
        image_query,
        total_duration,
        fallback_query=fallback_query,
        image_keywords=image_keywords,
    )

    cuts = {0.0, total_duration}
    elapsed = 0.0
    for duration, _ in cap_segments:
        elapsed += duration
        cuts.add(min(elapsed, total_duration))
    elapsed = 0.0
    for duration, _ in broll_segments:
        elapsed += duration
        cuts.add(min(elapsed, total_duration))
    ordered = sorted(cuts)

    timeline: list[tuple[float, str, str]] = []
    for idx in range(len(ordered) - 1):
        start = ordered[idx]
        end = ordered[idx + 1]
        seg_duration = end - start
        if seg_duration <= 0.01:
            continue
        body = _active_segment_value(cap_segments, start)
        query = _active_segment_value(broll_segments, start)
        timeline.append((seg_duration, query, body))
    if not timeline:
        default_query = image_query.strip() or fallback_query or "technology"
        timeline = [(total_duration, default_query, beats[0] if beats else "")]
    return timeline


def _caption_from_narration(narration: str) -> str:
    text = narration.strip()
    if not text:
        return ""
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    hook = sents[0] if sents else text
    return _truncate_slide_text(hook, _slide_body_max_chars())


def _slide_body(scene: Scene) -> str:
    body = _normalize_scene_text(scene.body)
    narration = scene.narration.strip()
    if body and body.lower() not in _GENERIC_BODIES and not re.search(
        r"(?i)\b(generate|create|make)\b.*\bvideo\b", body
    ):
        return body
    return _caption_from_narration(narration) if narration else body


def _enrich_scenes(scenes: list[Scene]) -> list[Scene]:
    out: list[Scene] = []
    for scene in scenes:
        scene.narration = _normalize_scene_text(scene.narration)
        scene.body = _normalize_scene_text(scene.body)
        if scene.captions:
            scene.captions = [str(caption).strip() for caption in scene.captions if str(caption).strip()]
        beats = caption_beats_for_scene(scene)
        if beats:
            scene.body = beats[0]
        elif scene.narration.strip() and (
            not scene.body.strip()
            or scene.body.lower() in _GENERIC_BODIES
            or scene.body.lower() in scene.title.lower()
        ):
            scene.body = _caption_from_narration(scene.narration)
        out.append(scene)
    return out


def _llm_available() -> bool:
    for name in ("GOOGLE_API_KEY", "GEMINI_API_KEY", "GROQ_API_KEY"):
        if os.environ.get(name, "").strip():
            return True
    return False


def _script_mode(args: argparse.Namespace) -> str:
    if args.llm:
        return "llm"
    mode = _env("VIDEO_COMPOSE_SCRIPT", "auto").lower()
    if mode in {"llm", "template"}:
        return mode
    return "llm" if _llm_available() else "template"


def _default_output(topic: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", topic_label(topic).lower())[:40].strip("-") or "info-video"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    env_dir = _env("VIDEO_OUTPUT_DIR") or _env("IMAGE_OUTPUT_DIR")
    candidates = []
    if env_dir:
        candidates.append(Path(env_dir).expanduser())
    else:
        candidates.extend(
            [
                Path.home() / "Videos" / "arka-generated",
                Path.cwd() / "arka-generated-videos",
                Path(tempfile.gettempdir()) / "arka-generated-videos",
            ]
        )
    out_dir: Path | None = None
    for candidate in candidates:
        try:
            candidate.mkdir(parents=True, exist_ok=True)
        except OSError:
            continue
        out_dir = candidate
        break
    if out_dir is None:
        out_dir = Path(tempfile.gettempdir()) / "arka-generated-videos"
        out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{slug}-{ts}.mp4"


def _hex_rgb(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _load_font(ImageFont, path: Path | None, size: int, *, bold: bool = False):
    if path and path.is_file():
        try:
            return ImageFont.truetype(str(path), size=size)
        except OSError:
            pass
    fallback = _resolve_font("Inter-Bold" if bold else "Inter", bold=bold)
    if fallback and fallback.is_file():
        try:
            return ImageFont.truetype(str(fallback), size=size)
        except OSError:
            pass
    return ImageFont.load_default()


def render_slide(
    image_path: Path | None,
    scene: Scene,
    output: Path,
    cfg: VideoConfig,
    *,
    body_override: str | None = None,
) -> None:
    Image, ImageDraw, ImageFilter, ImageFont = _require_pillow()
    canvas = Image.new("RGB", (cfg.width, cfg.height), _hex_rgb(cfg.bg_color))
    if image_path and image_path.is_file():
        photo = Image.open(image_path).convert("RGB")
        photo = _cover_crop(photo, cfg.width, cfg.height)
        photo = photo.filter(ImageFilter.GaussianBlur(radius=0.5))
        canvas.paste(photo, (0, 0))
        overlay = Image.new("RGBA", (cfg.width, cfg.height), (15, 23, 42, 170))
        canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")

    draw = ImageDraw.Draw(canvas)
    body_source = body_override if body_override is not None else _slide_body(scene)
    body_size = cfg.body_size
    title_font = _load_font(ImageFont, cfg.font_bold_path or cfg.font_path, cfg.title_size, bold=True)
    body_font = _load_font(ImageFont, cfg.font_path, body_size)
    accent = _hex_rgb(cfg.accent_color)
    text_color = _hex_rgb(cfg.text_color)
    body_color = (226, 232, 240)

    title_lines = prepare_slide_title(scene.title)
    body_lines = prepare_slide_body(body_source)
    title_gap = 10
    block_gap = 28
    accent_h = 6
    accent_gap = 18
    pad_x = 48
    pad_y = 28

    def _line_height(line: str, font, fallback: int) -> int:
        bbox = draw.textbbox((0, 0), line, font=font)
        return max(fallback, bbox[3] - bbox[1])

    def _line_width(line: str, font) -> int:
        bbox = draw.textbbox((0, 0), line, font=font)
        return bbox[2] - bbox[0]

    def _measure_block() -> tuple[list[int], list[int], int]:
        title_heights = [_line_height(line, title_font, cfg.title_size) for line in title_lines]
        body_heights = [_line_height(line, body_font, body_size) for line in body_lines]
        total_h = sum(title_heights) + title_gap * max(0, len(title_lines) - 1)
        if body_lines:
            total_h += block_gap + sum(body_heights) + title_gap * max(0, len(body_lines) - 1)
        if title_lines:
            total_h += accent_gap + accent_h
        return title_heights, body_heights, total_h

    title_heights, body_heights, total_h = _measure_block()
    if total_h > int(cfg.height * 0.45) and body_size > 24:
        body_size = max(24, int(body_size * 0.9))
        body_font = _load_font(ImageFont, cfg.font_path, body_size)
        title_heights, body_heights, total_h = _measure_block()

    y = max(48, (cfg.height - total_h) // 2)
    block_top = y - pad_y
    block_bottom = y + total_h + pad_y
    max_text_w = 0
    for line in title_lines:
        max_text_w = max(max_text_w, _line_width(line, title_font))
    for line in body_lines:
        max_text_w = max(max_text_w, _line_width(line, body_font))
    block_left = max(24, (cfg.width - max_text_w) // 2 - pad_x)
    block_right = min(cfg.width - 24, (cfg.width + max_text_w) // 2 + pad_x)
    backdrop = Image.new("RGBA", canvas.size, (0, 0, 0, 0))
    backdrop_draw = ImageDraw.Draw(backdrop)
    backdrop_draw.rounded_rectangle(
        [block_left, block_top, block_right, block_bottom],
        radius=18,
        fill=(15, 23, 42, 150),
    )
    canvas = Image.alpha_composite(canvas.convert("RGBA"), backdrop).convert("RGB")
    draw = ImageDraw.Draw(canvas)

    if title_lines:
        accent_w = min(140, max((_line_width(line, title_font) for line in title_lines), default=80))
        accent_x = (cfg.width - accent_w) // 2
        draw.rectangle([accent_x, y, accent_x + accent_w, y + accent_h], fill=accent)
        y += accent_gap

    for idx, line in enumerate(title_lines):
        x = (cfg.width - _line_width(line, title_font)) // 2
        draw.text((x, y), line, font=title_font, fill=text_color)
        y += title_heights[idx] + (title_gap if idx < len(title_lines) - 1 else 0)

    if body_lines:
        y += block_gap
        for idx, line in enumerate(body_lines):
            x = (cfg.width - _line_width(line, body_font)) // 2
            draw.text((x, y), line, font=body_font, fill=body_color)
            y += body_heights[idx] + (title_gap if idx < len(body_lines) - 1 else 0)

    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, format="PNG", optimize=True)


def _cover_crop(img, target_w: int, target_h: int):
    from PIL import Image

    src_w, src_h = img.size
    scale = max(target_w / src_w, target_h / src_h)
    resized = img.resize((int(src_w * scale), int(src_h * scale)), Image.Resampling.LANCZOS)
    left = (resized.width - target_w) // 2
    top = (resized.height - target_h) // 2
    return resized.crop((left, top, left + target_w, top + target_h))


def _ffprobe_duration(path: Path) -> float:
    ffprobe = _which("ffprobe")
    if not ffprobe or not path.is_file():
        return 0.0
    proc = subprocess.run(
        [
            ffprobe,
            "-v",
            "error",
            "-show_entries",
            "format=duration",
            "-of",
            "default=noprint_wrappers=1:nokey=1",
            str(path),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        return max(0.5, float((proc.stdout or "0").strip()))
    except ValueError:
        return 0.0


def _chart_hold_sec() -> float:
    return max(5.0, _env_float("VIDEO_CHART_SEC", _env_float("VIDEO_CHART_MIN_SEC", 15.0)))


def _chart_min_duration() -> float:
    return _chart_hold_sec()


def _broll_min_segment_sec() -> float:
    return max(1.5, _env_float("VIDEO_BROLL_MIN_SEGMENT_SEC", 2.5))


def _broll_fallback_switch_sec() -> float:
    return max(2.0, _env_float("VIDEO_BROLL_FALLBACK_SWITCH_SEC", 4.0))


def _topic_photo_keywords(topic: str) -> list[str]:
    words = [w.lower() for w in re.findall(r"[A-Za-z']+", topic) if len(w) >= 3]
    picked = [w for w in words if w not in _BROLL_STOPWORDS]
    if not picked:
        return []
    compact = compact_photo_query(" ".join(picked[:5]))
    search = stock_search_query(compact)
    out: list[str] = []
    for item in (compact, search):
        if item and item not in out and item != "technology":
            out.append(item)
    return out


def _scene_image_keywords(scene: Scene, topic: str) -> list[str]:
    if scene.image_keywords:
        raw = [kw.strip() for kw in scene.image_keywords if kw.strip()]
    else:
        parsed = _image_query_keywords(scene.image_query)
        if parsed:
            raw = parsed
        else:
            fallback = scene.image_query.strip() or scene.title.strip() or topic
            raw = _image_query_keywords(fallback) or _topic_photo_keywords(topic) or [stock_search_query(topic)]
    out: list[str] = []
    seen: set[str] = set()
    for kw in raw:
        compact = stock_search_query(kw)
        if compact and compact not in seen:
            seen.add(compact)
            out.append(compact)
    return out or _topic_photo_keywords(topic) or [stock_search_query(topic)]


def _scene_search_query(scene: Scene, topic: str) -> str:
    keywords = _scene_image_keywords(scene, topic)
    if scene.image_query.strip():
        return compact_photo_query(scene.image_query.strip())
    if keywords:
        return keywords[0]
    return compact_photo_query(scene.title or topic or "technology")


def _image_query_keywords(query: str) -> list[str]:
    words = [w.lower() for w in re.findall(r"[A-Za-z']+", query)]
    seen: set[str] = set()
    out: list[str] = []
    for word in words:
        if len(word) < 3 or word in _BROLL_STOPWORDS or word in seen:
            continue
        seen.add(word)
        out.append(word)
    return out


def _narration_words(narration: str) -> list[str]:
    return [w.lower() for w in re.findall(r"[A-Za-z']+", narration)]


def _word_matches_keyword(word: str, keyword: str) -> bool:
    if word == keyword:
        return True
    if len(keyword) >= 4 and keyword in word:
        return True
    if len(word) >= 4 and word in keyword:
        return True
    return False


def _merge_short_segments(segments: list[tuple[float, str]], min_segment: float) -> list[tuple[float, str]]:
    if not segments:
        return segments
    merged = list(segments)
    idx = 0
    while idx < len(merged):
        duration, query = merged[idx]
        if duration >= min_segment or len(merged) == 1:
            idx += 1
            continue
        if idx + 1 < len(merged):
            next_d, next_q = merged[idx + 1]
            merged[idx + 1] = (duration + next_d, next_q)
            merged.pop(idx)
            continue
        if idx > 0:
            prev_d, prev_q = merged[idx - 1]
            merged[idx - 1] = (prev_d + duration, prev_q)
            merged.pop(idx)
            continue
        idx += 1
    return merged


def _schedule_broll_segments(
    narration: str,
    image_query: str,
    total_duration: float,
    *,
    fallback_query: str,
    image_keywords: list[str] | None = None,
) -> list[tuple[float, str]]:
    """Return (segment_duration, search_query) pairs for keyword-synced B-roll."""
    if total_duration <= 0:
        return [(total_duration, fallback_query or image_query or "technology")]

    min_segment = _broll_min_segment_sec()
    keywords = image_keywords or _image_query_keywords(image_query)
    keywords = [compact_photo_query(kw) for kw in keywords if kw.strip()]
    default_query = stock_search_query(
        image_query.strip() or (keywords[0] if keywords else "") or fallback_query or "computer desk"
    )
    query_pool: list[str] = []
    for kw in keywords or [default_query]:
        query_pool.extend(diverse_photo_queries(kw, limit=4))
    if default_query not in query_pool:
        query_pool.insert(0, default_query)
    words = _narration_words(narration)

    events: list[tuple[float, str]] = [(0.0, query_pool[0])]
    if words and keywords:
        variant_idx = 0
        for idx, word in enumerate(words):
            for keyword in keywords:
                if _word_matches_keyword(word, keyword):
                    variants = diverse_photo_queries(keyword, limit=4)
                    pick = variants[variant_idx % len(variants)]
                    variant_idx += 1
                    events.append(((idx / len(words)) * total_duration, pick))
                    break

    if len(events) == 1:
        switch_every = _broll_fallback_switch_sec()
        count = max(2, int(total_duration / switch_every))
        seg_len = total_duration / count
        rotation = query_pool or [default_query]
        segments = []
        for i in range(count):
            query = rotation[i % len(rotation)]
            end = total_duration if i == count - 1 else (i + 1) * seg_len
            start = i * seg_len
            segments.append((end - start, query))
        return _merge_short_segments(segments, min_segment)

    events.sort(key=lambda item: item[0])
    deduped: list[tuple[float, str]] = []
    for event_time, query in events:
        if deduped and event_time - deduped[-1][0] < min_segment * 0.5:
            deduped[-1] = (deduped[-1][0], query)
        else:
            deduped.append((event_time, query))

    segments: list[tuple[float, str]] = []
    for i, (start, query) in enumerate(deduped):
        end = deduped[i + 1][0] if i + 1 < len(deduped) else total_duration
        segments.append((end - start, query))

    assigned = sum(duration for duration, _ in segments)
    if segments and assigned < total_duration - 0.05:
        last_d, last_q = segments[-1]
        segments[-1] = (last_d + (total_duration - assigned), last_q)
    elif segments and assigned > total_duration + 0.05:
        scale = total_duration / assigned
        segments = [(duration * scale, query) for duration, query in segments]

    return _merge_short_segments(segments, min_segment)


def _fetch_scene_photo(
    query: str,
    used_photo_ids: set[str],
    *,
    orientation: str,
    context_terms: list[str] | None = None,
    segment_idx: int = 0,
) -> StockPhoto:
    variants = diverse_photo_queries(query, limit=8)
    if segment_idx:
        offset = segment_idx % len(variants)
        variants = variants[offset:] + variants[:offset]

    for try_query in variants:
        photos = search_stock_photos(
            try_query,
            count=12,
            orientation=orientation,
            context_terms=context_terms,
            exclude_ids=used_photo_ids,
        )
        if photos:
            photo = photos[0]
            used_photo_ids.add(photo_uid(photo))
            return photo

    raise SystemExit(f"No unused stock photos found for query: {query!r}")


def _render_photo_slide(
    scene: Scene,
    photo: StockPhoto,
    *,
    work: Path,
    scene_idx: int,
    segment_idx: int,
    slide: Path,
    cfg: VideoConfig,
    body_override: str | None = None,
) -> None:
    img_path = work / f"photo-{scene_idx:02d}-{segment_idx:02d}.jpg"
    download_stock_photo(photo, img_path)
    render_slide(img_path, scene, slide, cfg, body_override=body_override)


def _build_broll_slides(
    scene: Scene,
    *,
    topic: str,
    narration: str,
    duration: float,
    work: Path,
    scene_idx: int,
    cfg: VideoConfig,
    used_photo_ids: set[str],
    credits: list[dict],
    captions: list[str] | None = None,
    segment_offset: int = 0,
) -> list[tuple[Path, float]]:
    query = _scene_search_query(scene, topic)
    keywords = _scene_image_keywords(scene, topic)
    context_terms = list(
        dict.fromkeys(
            keywords
            + _topic_photo_keywords(topic)
            + [word for word in re.findall(r"[a-z']+", query.lower()) if len(word) >= 3]
        )
    )
    timeline = _schedule_scene_timeline(
        narration,
        query,
        duration,
        fallback_query=topic,
        captions=captions,
        image_keywords=keywords,
    )
    slides: list[tuple[Path, float]] = []
    for seg_idx, (seg_duration, seg_query, seg_body) in enumerate(timeline):
        photo = _fetch_scene_photo(
            seg_query,
            used_photo_ids,
            orientation=cfg.orientation,
            context_terms=context_terms,
            segment_idx=seg_idx,
        )
        if seg_idx == 0 and segment_offset == 0:
            scene.photo = photo
        out_idx = segment_offset + seg_idx
        seg_slide = work / f"slide-{scene_idx:02d}-{out_idx:02d}.png"
        _render_photo_slide(
            scene,
            photo,
            work=work,
            scene_idx=scene_idx,
            segment_idx=out_idx,
            slide=seg_slide,
            cfg=cfg,
            body_override=seg_body,
        )
        credits.append(
            {
                "scene": scene.title,
                "query": seg_query,
                "source": photo.source,
                "photographer": photo.photographer,
                "url": photo.photographer_url,
            }
        )
        slides.append((seg_slide, seg_duration))
    return slides


def _multi_segment_clip(
    slides: list[tuple[Path, float]],
    output: Path,
    cfg: VideoConfig,
    *,
    work: Path,
    scene_idx: int,
    static: bool = False,
) -> None:
    if len(slides) == 1:
        slide, duration = slides[0]
        if static:
            _static_scene_clip(slide, duration, output, cfg)
        else:
            _scene_clip(slide, duration, output, cfg, variant=0)
        return
    parts: list[Path] = []
    for segment_idx, (slide, duration) in enumerate(slides):
        part = work / f"clip-{scene_idx:02d}-part-{segment_idx:02d}.mp4"
        if static:
            _static_scene_clip(slide, duration, part, cfg)
        else:
            _scene_clip(slide, duration, part, cfg, variant=segment_idx)
        parts.append(part)
    _concat_videos(parts, output)


def _photo_broll_clip(
    slides: list[tuple[Path, float]],
    output: Path,
    cfg: VideoConfig,
    *,
    work: Path,
    scene_idx: int,
) -> None:
    _multi_segment_clip(slides, output, cfg, work=work, scene_idx=scene_idx, static=False)


def _static_scene_clip(slide: Path, duration: float, output: Path, cfg: VideoConfig) -> None:
    """Hold chart/slide frames without Ken Burns zoom (keeps labels readable)."""
    from arka.media.chart_slide import static_scene_clip_filter

    ffmpeg = _require_ffmpeg()
    proc = subprocess.run(
        [
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
            str(slide),
            "-vf",
            static_scene_clip_filter(cfg),
            "-r",
            str(cfg.fps),
            "-c:v",
            "libx264",
            "-tune",
            "stillimage",
            "-t",
            f"{duration:.3f}",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"ffmpeg static scene failed: {(proc.stderr or proc.stdout or proc.returncode).strip()}")


def _scene_clip(
    slide: Path,
    duration: float,
    output: Path,
    cfg: VideoConfig,
    *,
    variant: int = 0,
) -> None:
    ffmpeg = _require_ffmpeg()
    frames = max(int(duration * cfg.fps), cfg.fps)
    pan_modes = (
        ("iw/2-(iw/zoom/2)", "ih/2-(ih/zoom/2)"),
        ("iw/zoom/4", "ih/2-(ih/zoom/2)"),
        ("iw*3/4-iw/zoom/2", "ih/2-(ih/zoom/2)"),
        ("iw/2-(iw/zoom/2)", "ih/zoom/4"),
    )
    x_expr, y_expr = pan_modes[variant % len(pan_modes)]
    zoom_rate = 0.0008 + (variant % 3) * 0.0003
    zoom_max = 1.08 + (variant % 2) * 0.04
    zoom = (
        f"scale={cfg.width * 4}:{cfg.height * 4},"
        f"zoompan=z='min(zoom+{zoom_rate:.4f},{zoom_max:.2f})':"
        f"x='{x_expr}':y='{y_expr}':"
        f"d={frames}:s={cfg.width}x{cfg.height}:fps={cfg.fps}"
    )
    proc = subprocess.run(
        [
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
            str(slide),
            "-vf",
            zoom,
            "-t",
            f"{duration:.3f}",
            "-pix_fmt",
            "yuv420p",
            "-an",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"ffmpeg scene failed: {(proc.stderr or proc.stdout or proc.returncode).strip()}")


def _synthesize_narration(text: str, output: Path, cfg: VideoConfig) -> bool:
    if not text.strip() or cfg.tts in {"none", "off", "0"}:
        return False
    if cfg.tts in {"edge", "auto", ""}:
        try:
            from arka.voice.edge_speak import synthesize_to_file

            synthesize_to_file(text, output, voice=cfg.tts_voice or None)
            if output.is_file():
                print(f"  TTS voice: {cfg.tts_voice}", file=sys.stderr)
            return output.is_file()
        except Exception as exc:
            print(f"  TTS failed: {exc}", file=sys.stderr)
    return False


def _concat_videos(clips: list[Path], output: Path) -> None:
    ffmpeg = _require_ffmpeg()
    with tempfile.NamedTemporaryFile("w", suffix=".txt", delete=False, encoding="utf-8") as tmp:
        for clip in clips:
            tmp.write(f"file '{clip.as_posix()}'\n")
        list_path = Path(tmp.name)
    proc = subprocess.run(
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
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    list_path.unlink(missing_ok=True)
    if proc.returncode != 0:
        raise SystemExit(f"ffmpeg concat failed: {(proc.stderr or proc.stdout).strip()}")


def _concat_audio(tracks: list[Path], output: Path) -> None:
    ffmpeg = _require_ffmpeg()
    if len(tracks) == 1:
        shutil.copy2(tracks[0], output)
        return
    inputs: list[str] = []
    for track in tracks:
        inputs.extend(["-i", str(track)])
    filt = "".join(f"[{i}:a]" for i in range(len(tracks))) + f"concat=n={len(tracks)}:v=0:a=1[aout]"
    proc = subprocess.run(
        [
            ffmpeg,
            "-nostdin",
            "-hide_banner",
            "-loglevel",
            "error",
            *ffmpeg_thread_args(),
            "-y",
            *inputs,
            "-filter_complex",
            filt,
            "-map",
            "[aout]",
            "-c:a",
            "aac",
            "-b:a",
            "192k",
            str(output),
        ],
        capture_output=True,
        text=True,
        check=False,
    )
    if proc.returncode != 0:
        raise SystemExit(f"ffmpeg audio concat failed: {(proc.stderr or proc.stdout).strip()}")


def _mux_av(video: Path, audio: Path | None, output: Path, cfg: VideoConfig) -> None:
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
        str(video),
    ]
    if audio and audio.is_file():
        cmd.extend(["-i", str(audio), "-c:a", "aac", "-b:a", "192k", "-shortest"])
    else:
        cmd.append("-an")
    cmd.extend(
        [
            "-c:v",
            "libx264",
            "-preset",
            cfg.preset,
            "-crf",
            str(cfg.crf),
            "-pix_fmt",
            "yuv420p",
            "-movflags",
            "+faststart",
            str(output),
        ]
    )
    proc = subprocess.run(cmd, capture_output=True, text=True, check=False)
    if proc.returncode != 0:
        raise SystemExit(f"ffmpeg mux failed: {(proc.stderr or proc.stdout).strip()}")


def _attach_photo_queries(scenes: list[Scene], topic: str) -> None:
    for scene in scenes:
        if not scene.image_query.strip() and not scene.image_keywords:
            scene.image_query = scene.title or topic


def _llm_enrich_image_keywords(topic: str, scenes: list[Scene]) -> list[Scene]:
    missing = [scene for scene in scenes if not scene.image_keywords]
    if not missing:
        return scenes
    try:
        from arka.llm.fallback import llm_complete
    except ImportError:
        return scenes

    payload = [
        {
            "title": scene.title,
            "narration": scene.narration[:400],
            "image_query": scene.image_query,
        }
        for scene in missing
    ]
    system = (
        "You pick stock-photo search keywords for a YouTube video. "
        "Return ONLY JSON array: "
        '[{"title":"same as input", "image_keywords":["desktop monitor", "laptop keyboard", "home office"]}]. '
        "Provide 3-6 image_keywords per scene. Each keyword must be 2-3 visual nouns max (no sentences)."
    )
    user = f"Topic: {topic_label(topic)}\n\n{json.dumps(payload, indent=2)}"
    text = llm_complete(system, user, temperature=0.2, task="compose_video")
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        rows = json.loads(text)
    except json.JSONDecodeError:
        return scenes
    by_title = {str(row.get("title") or "").strip(): row for row in rows if isinstance(row, dict)}
    for scene in scenes:
        row = by_title.get(scene.title.strip())
        if not row:
            continue
        raw = row.get("image_keywords") or row.get("keywords") or row.get("images")
        if isinstance(raw, list):
            scene.image_keywords = [
                compact_photo_query(str(item).strip())
                for item in raw
                if str(item).strip()
            ]
            scene.image_keywords = [kw for kw in scene.image_keywords if kw]
        if not scene.image_query.strip():
            query = row.get("image_query") or row.get("image_search")
            if isinstance(query, str) and query.strip():
                scene.image_query = compact_photo_query(query.strip())
    return scenes


def compose(
    scenes: list[Scene],
    *,
    output: Path,
    topic: str,
    cfg: VideoConfig | None = None,
) -> Path:
    if not scenes:
        raise SystemExit("No scenes to render.")
    cfg = cfg or load_config()
    from arka.media.chart_slide import render_scene_visual, scene_has_chart_visual

    needs_photos = bool(scenes)
    if needs_photos:
        _attach_photo_queries(scenes, topic)
        if not any_source_available():
            raise SystemExit(stock_setup_hint("compose_video"))

    work = Path(tempfile.mkdtemp(prefix="arka-video-"))
    clips: list[Path] = []
    audio_tracks: list[Path] = []
    credits: list[dict] = []

    try:
        used_photo_ids: set[str] = set()
        for i, scene in enumerate(scenes):
            print(f"  Scene {i + 1}/{len(scenes)}: {scene.title}", file=sys.stderr)
            is_chart = scene_has_chart_visual(scene)
            narration = (scene.narration or scene.body or scene.title).strip()
            audio_path = work / f"narration-{i:02d}.mp3"
            has_audio = _synthesize_narration(narration, audio_path, cfg)
            duration = scene.duration
            if has_audio:
                audio_dur = _ffprobe_duration(audio_path) + 0.35
                duration = max(audio_dur, scene.duration) if scene.duration > 0 else audio_dur
            if duration <= 0:
                duration = cfg.scene_sec
            duration = max(duration, 2.5)
            if has_audio:
                audio_dur = _ffprobe_duration(audio_path) + 0.35
                if duration > audio_dur + 0.05:
                    padded_audio = work / f"narration-{i:02d}-padded.mp3"
                    _pad_audio_to_duration(audio_path, duration, padded_audio)
                    audio_path = padded_audio
                audio_tracks.append(audio_path)

            clip = work / f"clip-{i:02d}.mp4"
            beats = caption_beats_for_scene(scene)
            if is_chart:
                chart_hold = min(_chart_hold_sec(), duration)
                chart_slide = render_scene_visual(scene, work, cfg, index=i)
                chart_body = beats[0] if beats else (scene.body or scene.title)
                chart_overlay = work / f"slide-{i:02d}-chart.png"
                render_slide(chart_slide, scene, chart_overlay, cfg, body_override=chart_body)
                segments: list[tuple[Path, float]] = [(chart_overlay, chart_hold)]
                remainder = max(0.0, duration - chart_hold)
                if remainder > 0.5:
                    broll_beats = beats[1:] if len(beats) > 1 else beats
                    broll_slides = _build_broll_slides(
                        scene,
                        topic=topic,
                        narration=narration,
                        duration=remainder,
                        work=work,
                        scene_idx=i,
                        cfg=cfg,
                        used_photo_ids=used_photo_ids,
                        credits=credits,
                        captions=broll_beats or None,
                        segment_offset=1,
                    )
                    segments.extend(broll_slides)
                    print(
                        f"    Chart: {chart_hold:.0f}s, then B-roll: {len(broll_slides)} segments",
                        file=sys.stderr,
                    )
                else:
                    print(f"    Chart: {chart_hold:.0f}s", file=sys.stderr)
                static_segments = len(segments)
                mixed = static_segments > 1 or remainder <= 0.5
                if mixed and len(segments) > 1:
                    parts: list[Path] = []
                    for seg_idx, (slide, seg_duration) in enumerate(segments):
                        part = work / f"clip-{i:02d}-part-{seg_idx:02d}.mp4"
                        if seg_idx == 0:
                            _static_scene_clip(slide, seg_duration, part, cfg)
                        else:
                            _scene_clip(slide, seg_duration, part, cfg, variant=seg_idx)
                        parts.append(part)
                    _concat_videos(parts, clip)
                else:
                    _static_scene_clip(chart_overlay, chart_hold, clip, cfg)
            else:
                broll_slides = _build_broll_slides(
                    scene,
                    topic=topic,
                    narration=narration,
                    duration=duration,
                    work=work,
                    scene_idx=i,
                    cfg=cfg,
                    used_photo_ids=used_photo_ids,
                    credits=credits,
                    captions=beats or None,
                )
                if len(broll_slides) > 1:
                    print(
                        f"    Captions/B-roll: {len(broll_slides)} segments (keyword-synced)",
                        file=sys.stderr,
                    )
                _photo_broll_clip(broll_slides, clip, cfg, work=work, scene_idx=i)
            clips.append(clip)

        silent = work / "silent.mp4"
        _concat_videos(clips, silent)
        final = work / "final.mp4"
        audio_merged: Path | None = None
        if audio_tracks:
            audio_merged = work / "narration-full.m4a"
            _concat_audio(audio_tracks, audio_merged)
        _mux_av(silent, audio_merged, final, cfg)
        output.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(final, output)

        sidecar = output.with_suffix(".json")
        sidecar.write_text(
            json.dumps(
                {
                    "topic": topic,
                    "scenes": [
                        {
                            "title": s.title,
                            "narration": s.narration,
                            "body": s.body,
                            "captions": s.captions,
                            "image_query": s.image_query,
                            "image_keywords": s.image_keywords,
                            "chart": s.chart,
                            "chart_path": s.chart_path,
                            "slide_image": s.slide_image,
                            "duration": s.duration,
                        }
                        for s in scenes
                    ],
                    "unsplash_credits": credits,
                    "output": str(output),
                    "source": "arka-compose-video",
                },
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        return output
    finally:
        shutil.rmtree(work, ignore_errors=True)


def _parse_scenes_json(raw: str) -> list[Scene]:
    data = json.loads(raw)
    rows = data if isinstance(data, list) else data.get("scenes") or []
    scenes: list[Scene] = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        title = str(row.get("title") or "").strip()
        if not title:
            continue
        chart_raw = row.get("chart")
        chart = chart_raw if isinstance(chart_raw, dict) else None
        captions_raw = row.get("captions")
        captions: list[str] = []
        if isinstance(captions_raw, list):
            captions = [str(item).strip() for item in captions_raw if str(item).strip()]
        keywords_raw = row.get("image_keywords") or row.get("image_keys") or row.get("broll_keywords")
        image_keywords: list[str] = []
        if isinstance(keywords_raw, list):
            image_keywords = [
                compact_photo_query(str(item).strip())
                for item in keywords_raw
                if str(item).strip()
            ]
            image_keywords = [kw for kw in image_keywords if kw]
        scenes.append(
            Scene(
                title=title,
                narration=_normalize_scene_text(row.get("narration") or row.get("voiceover")),
                body=_normalize_scene_text(row.get("body") or row.get("subtitle")),
                captions=captions,
                image_query=str(row.get("image_query") or row.get("image") or "").strip(),
                image_keywords=image_keywords,
                duration=float(row.get("duration") or 0),
                chart=chart,
                chart_path=str(row.get("chart_path") or row.get("chart_png") or "").strip(),
                slide_image=str(row.get("slide_image") or row.get("slide") or "").strip(),
            )
        )
    return scenes


def _scene_bounds() -> tuple[int, int]:
    min_s = max(2, _env_int("VIDEO_MIN_SCENES", 3))
    max_s = max(min_s, _env_int("VIDEO_MAX_SCENES", 10))
    return min_s, max_s


def _llm_script(
    topic: str,
    *,
    scenes: int | None = None,
    target_duration_sec: float | None = None,
) -> list[Scene]:
    try:
        from arka.llm.fallback import llm_complete
    except ImportError as exc:
        raise SystemExit("LLM script generation requires arka chat deps (pip install 'arka-agent[chat]')") from exc

    min_scenes, max_scenes = _scene_bounds()
    if target_duration_sec and scenes is None:
        scenes = _scenes_for_duration(target_duration_sec)
    system = (
        "You write YouTube tech/info video scripts. "
        "Return ONLY a JSON array (no markdown). Each item: "
        '{"title":"...", "narration":"spoken voiceover text", '
        '"body":"very short on-screen headline (max 12 words)", '
        '"captions":["short line 1","short line 2"] (2-6 lines, max 12 words each, synced on screen), '
        '"image_keywords":["desktop monitor","laptop keyboard","home office"] (3-6 short visual phrases, 2-3 words each), '
        '"image_query":"optional fallback 2-4 word search OR omit when using chart", '
        '"chart":{"type":"bar|barh|pie|line|grouped_bar", "title":"...", '
        '"data":"Label:10,Other:20 or Label:$4.7T,Other:$1.2T", "ylabel":"...", "source":"..."}}'
    )
    if scenes is not None:
        scene_hint = f"Scenes: exactly {scenes}"
    else:
        scene_hint = (
            f"Choose an appropriate number of scenes ({min_scenes}-{max_scenes}) "
            "based on topic depth — intro, core ideas, examples, and takeaway."
        )
    user = (
        f"Topic: {topic_label(topic)}\n{scene_hint}\n"
        "Style: clear tech explainer for YouTube. "
        "Provide captions as 2-6 short on-screen lines per scene (max 12 words each). "
        "Provide image_keywords as 3-6 short visual search phrases (2-3 words each, e.g. desktop tower, laptop desk). "
        "Narration can be longer; captions are what viewers read while listening."
    )
    if target_duration_sec:
        minutes = target_duration_sec / 60
        scene_count = scenes or _scenes_for_duration(target_duration_sec)
        words_total = int(minutes * _words_per_minute())
        words_per_scene = max(80, words_total // max(1, scene_count))
        user += (
            f"\nTarget runtime: about {minutes:.0f} minutes total across {scene_count} scenes. "
            f"Write roughly {words_per_scene} spoken words of narration per scene. "
            "Use chart objects on data-heavy scenes when numbers help."
        )
    text = llm_complete(system, user, temperature=0.4, task="compose_video")
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = _parse_scenes_json(text)
    except (json.JSONDecodeError, ValueError) as exc:
        raise SystemExit(f"LLM returned invalid scene JSON: {exc}") from exc
    if len(parsed) < 2:
        raise SystemExit("LLM did not return a usable scene script.")
    if scenes is None and len(parsed) > max_scenes:
        parsed = parsed[:max_scenes]
    return _enrich_scenes(parsed)


def _llm_summarize_script(
    topic: str,
    scenes: list[Scene],
    *,
    target_duration_sec: float | None = None,
) -> list[Scene]:
    try:
        from arka.llm.fallback import llm_complete
    except ImportError as exc:
        raise SystemExit("LLM script generation requires arka chat deps (pip install 'arka-agent[chat]')") from exc

    payload = [
        {
            "title": scene.title,
            "narration": scene.narration,
            "body": scene.body,
            "captions": scene.captions,
            "image_query": scene.image_query,
            "image_keywords": scene.image_keywords,
            "chart": scene.chart,
            "duration": scene.duration,
        }
        for scene in scenes
    ]
    system = (
        "Shorten each scene's narration by 30-50% so on-screen captions stay readable. "
        "Return ONLY a JSON array with: title, narration, body, captions, image_query, chart. "
        "Keep titles, charts, and image_query unchanged. "
        "Provide 2-6 captions per scene (max 12 words each)."
    )
    user = f"Topic: {topic_label(topic)}\n\n{json.dumps(payload, indent=2)}"
    if target_duration_sec:
        user += f"\nTarget total runtime: about {target_duration_sec / 60:.0f} minutes."
    text = llm_complete(system, user, temperature=0.3, task="compose_video")
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    try:
        parsed = _parse_scenes_json(text)
    except (json.JSONDecodeError, ValueError):
        return scenes
    if len(parsed) < 1:
        return scenes
    for idx, scene in enumerate(parsed):
        if idx < len(scenes):
            scene.chart_path = scenes[idx].chart_path
            scene.slide_image = scenes[idx].slide_image
            if scene.duration <= 0:
                scene.duration = scenes[idx].duration
    return _enrich_scenes(parsed)


def _template_script(topic: str) -> list[Scene]:
    label = topic_label(topic)
    key = topic.strip().lower()
    if key in {"ai", "artificial intelligence", "machine learning", "ml"}:
        return _enrich_scenes(
            [
                Scene(
                    title=f"What is {label}?",
                    narration=(
                        f"{label} is software that learns from data, recognizes patterns, "
                        "and helps people make decisions faster."
                    ),
                    body="",
                    image_query="artificial intelligence neural network",
                ),
                Scene(
                    title="Why it matters",
                    narration=(
                        f"{label} powers search, recommendations, coding assistants, and automation. "
                        "It is reshaping every industry."
                    ),
                    body="",
                    image_query="technology business innovation",
                ),
                Scene(
                    title="How it works",
                    narration=(
                        "Models train on examples, improve with feedback, and deploy through APIs and apps. "
                        "Start with a clear problem, good data, and simple benchmarks."
                    ),
                    body="",
                    image_query="developer coding laptop",
                ),
                Scene(
                    title="Key takeaways",
                    narration=(
                        f"Use {label} to augment your work—not replace judgment. "
                        "Experiment, measure results, and keep learning."
                    ),
                    body="",
                    image_query="team collaboration office",
                ),
            ]
        )
    return _enrich_scenes(
        [
            Scene(
                title=f"What is {label}?",
                narration=f"In this video, we explain {label} in plain language with practical examples.",
                body="",
                image_query=f"{label} technology",
            ),
            Scene(
                title="Why it matters",
                narration=f"Understanding {label} helps you make better decisions and build useful products.",
                body="",
                image_query="professional workspace technology",
            ),
            Scene(
                title="Core ideas",
                narration=f"Here are the essential concepts behind {label} that you can apply right away.",
                body="",
                image_query="abstract network data",
            ),
            Scene(
                title="Takeaways",
                narration=f"Start small with {label}, measure what works, and keep iterating.",
                body="",
                image_query="success planning team",
            ),
        ]
    )


def nl_to_argv(text: str) -> list[str]:
    t = text.strip()
    if not t:
        return []

    duration_gap = r"(?:(?:\d+(?:\.\d+)?\s*(?:hours?|hrs?|h|minutes?|mins?|min|seconds?|secs?|sec)\s+)+)?"
    intent_prefix = r"(?i)(?:^|\b)(?:arka\s+)?(?:please\s+)?(?:make|create|compose|build|render|produce|generate)\s+"
    compose_intent = re.search(
        intent_prefix
        + rf"(?:a\s+|an\s+)?{duration_gap}(?:(?:youtube|info|tech|explainer)\s+)?video\s+(?:on|about|for|explaining)\s+\S",
        t,
    ) or re.search(
        rf"(?i){duration_gap}(?:youtube|info|tech|explainer)\s+video\b",
        t,
    ) or re.search(
        rf"(?i)(?:^|\b)(?:arka\s+)?compose\s+{duration_gap}video\s+(?:on|about|for|explaining)\s+\S",
        t,
    )
    if not compose_intent:
        return []

    topic = normalize_topic(t)
    if not topic:
        return []
    argv = ["compose", "--topic", topic]
    duration = parse_duration_seconds(t)
    if duration:
        argv.extend(["--duration", format_duration_arg(duration)])
    if re.search(r"(?i)\b(llm|write script)\b", t):
        argv.append("--llm")
    return argv


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Compose info/YouTube videos — stock B-roll (Unsplash/Pexels/Pixabay), charts, TTS, ffmpeg"
    )
    sub = p.add_subparsers(dest="cmd")

    p_compose = sub.add_parser("compose", help="Build video from topic or script")
    p_compose.add_argument("--topic", help="Video topic (uses template or --llm script)")
    p_compose.add_argument("--script", help="JSON script file or inline JSON")
    p_compose.add_argument("--llm", action="store_true", help="Generate script via LLM")
    p_compose.add_argument(
        "--scenes",
        type=int,
        default=None,
        metavar="N",
        help="Scene count for --llm (default: let the LLM choose)",
    )
    p_compose.add_argument(
        "--duration",
        metavar="TIME",
        help="Target runtime (e.g. 19m, 1h30m, 90s). NL: '19 minute video on …'",
    )
    p_compose.add_argument("-o", "--output", help="Output .mp4 path")
    p_compose.set_defaults(func=cmd_compose)

    p_parse = sub.add_parser("parse", help="Parse natural language → compose args")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)

    p_check = sub.add_parser("check", help="Verify ffmpeg, Pillow, Unsplash key")
    p_check.set_defaults(func=cmd_check)

    return p


def cmd_check(_args: argparse.Namespace) -> int:
    ok = True
    if not _which("ffmpeg"):
        print("✗ ffmpeg missing", file=sys.stderr)
        ok = False
    else:
        print("✓ ffmpeg")
    try:
        _require_pillow()
        print("✓ Pillow")
    except SystemExit:
        print("✗ Pillow missing", file=sys.stderr)
        ok = False
    if access_key():
        print("✓ Unsplash key set")
    else:
        print("  Unsplash key not set")
    from arka.media.stock_photos import pexels_key, pixabay_key

    if pexels_key():
        print("✓ Pexels key set")
    if pixabay_key():
        print("✓ Pixabay key set")
    if not any_source_available():
        print(f"✗ {stock_setup_hint()}", file=sys.stderr)
        ok = False
    cfg = load_config()
    print(f"  Font: {cfg.font_path or 'default'}")
    print(f"  Bold: {cfg.font_bold_path or 'default'}")
    print(f"  Size: title={cfg.title_size} body={cfg.body_size}")
    return 0 if ok else 1


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def cmd_compose(args: argparse.Namespace) -> int:
    scenes: list[Scene] = []
    topic = normalize_topic((args.topic or "").strip())
    target_duration_sec: float | None = None
    if getattr(args, "duration", None):
        try:
            target_duration_sec = parse_duration_value(str(args.duration))
        except ValueError as exc:
            print(f"Invalid --duration: {exc}", file=sys.stderr)
            return 1

    if args.script:
        raw = Path(args.script).expanduser().read_text(encoding="utf-8") if Path(args.script).is_file() else args.script
        scenes = _enrich_scenes(_parse_scenes_json(raw))
        if not topic and scenes:
            topic = scenes[0].title

    if not scenes and topic:
        mode = _script_mode(args)
        if mode == "llm":
            if args.scenes is not None:
                print(f"Writing script with LLM ({args.scenes} scenes) …", file=sys.stderr)
            elif target_duration_sec:
                auto_scenes = _scenes_for_duration(target_duration_sec)
                print(
                    f"Writing script with LLM (~{target_duration_sec / 60:.0f} min target, "
                    f"{auto_scenes} scenes) …",
                    file=sys.stderr,
                )
            else:
                print("Writing script with LLM (auto scene count) …", file=sys.stderr)
            try:
                scenes = _llm_script(
                    topic,
                    scenes=args.scenes,
                    target_duration_sec=target_duration_sec,
                )
                if _script_needs_shortening(scenes):
                    print(
                        "Script too dense for on-screen captions — summarizing and retrying …",
                        file=sys.stderr,
                    )
                    scenes = _llm_summarize_script(
                        topic,
                        scenes,
                        target_duration_sec=target_duration_sec,
                    )
                if args.scenes is None:
                    print(f"  LLM chose {len(scenes)} scenes", file=sys.stderr)
            except SystemExit as exc:
                print(f"  LLM script failed ({exc}); using template.", file=sys.stderr)
                scenes = _template_script(topic)
        else:
            scenes = _template_script(topic)

    if target_duration_sec:
        _apply_target_duration(scenes, target_duration_sec)
        print(
            f"Target duration: {target_duration_sec / 60:.1f} min "
            f"({format_duration_arg(target_duration_sec)}, {len(scenes)} scenes)",
            file=sys.stderr,
        )

    if not scenes:
        print("Provide --topic or --script", file=sys.stderr)
        return 1
    if not topic:
        topic = scenes[0].title

    if _llm_available() and any(not s.image_keywords for s in scenes):
        print("Choosing stock photo keywords with LLM …", file=sys.stderr)
        scenes = _llm_enrich_image_keywords(topic, scenes)

    label = topic_label(topic)
    print(f"Topic: {label}", file=sys.stderr)
    out = Path(args.output).expanduser() if args.output else _default_output(topic)
    print(f"Composing {len(scenes)} scenes → {out}", file=sys.stderr)
    saved = compose(scenes, output=out, topic=topic)
    print(f"Saved video: {saved}")
    print(f"Credits: {saved.with_suffix('.json')}")
    if _env("OPEN_VIDEO", "1") not in {"0", "false"}:
        _open_video(saved)
    return 0


def _open_video(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif _which("xdg-open"):
        subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def main(argv: list[str] | None = None) -> int:
    from arka.env import load_env

    load_env()
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        build_parser().print_help()
        return 0
    if argv[0] not in {"compose", "parse", "check", "-h", "--help"}:
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
