#!/usr/bin/env python3
"""Compose YouTube-style info videos — Unsplash B-roll, custom fonts, ffmpeg (headless)."""

from __future__ import annotations

import argparse
import ast
import asyncio
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
from arka.media.unsplash import UnsplashPhoto, access_key, download_photo, search_photos, setup_hint


@dataclass
class Scene:
    title: str
    narration: str = ""
    body: str = ""
    image_query: str = ""
    duration: float = 0.0
    photo: UnsplashPhoto | None = None


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
    font_path = _env("VIDEO_FONT_PATH")
    font_bold = _env("VIDEO_FONT_BOLD_PATH") or _env("VIDEO_FONT_BOLD")
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
        title_size=_env_int("VIDEO_TITLE_FONT_SIZE", _env_int("VIDEO_FONT_SIZE", 72)),
        body_size=_env_int("VIDEO_BODY_FONT_SIZE", max(28, _env_int("VIDEO_FONT_SIZE", 72) - 30)),
        bg_color=_env("VIDEO_BG_COLOR", "#0f172a"),
        text_color=_env("VIDEO_TEXT_COLOR", "#f8fafc"),
        accent_color=_env("VIDEO_ACCENT_COLOR", "#38bdf8"),
        scene_sec=_env_float("VIDEO_SCENE_SEC", 5.0),
        crf=_env_int("VIDEO_CRF", 18),
        preset=_env("VIDEO_PRESET", "medium") or "medium",
        tts=_env("VIDEO_TTS", "edge").lower() or "edge",
        tts_voice=_env("VIDEO_TTS_VOICE", _env("SPEAK_VOICE", "")),
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


def extract_video_topic(text: str) -> str:
    """Pull the subject out of NL like 'generate an video on ai'."""
    t = text.strip().strip("'\"")
    if not t:
        return ""
    patterns = [
        r"(?i)(?:^|\b)(?:please\s+)?(?:make|create|compose|build|render|produce|generate|arka)\s+"
        r"(?:a\s+|an\s+)?(?:(?:youtube|info|tech|explainer)\s+)?video\s+"
        r"(?:on|about|for|explaining)\s+(.+)$",
        r"(?i)(?:^|\b)(?:please\s+)?(?:make|create|compose|build|render|produce|generate|arka)\s+"
        r"(?:a\s+|an\s+)?video\s+(?:on|about|for|explaining)\s+(.+)$",
        r"(?i)(?:^|\b)(?:youtube|info|tech|explainer)\s+video\s+(?:on|about|for|explaining)\s+(.+)$",
    ]
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            topic = m.group(1).strip().strip("'\"")
            topic = re.sub(r"(?i)\s+(?:with\s+llm|please)$", "", topic).strip()
            if topic:
                return topic
    return t


def normalize_topic(raw: str) -> str:
    topic = extract_video_topic(raw)
    topic = re.sub(r"(?i)\s+(?:video|please)$", "", topic).strip(" '\"")
    if not topic:
        return raw.strip()
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


def _caption_from_narration(narration: str, *, width: int = 42) -> str:
    text = narration.strip()
    if not text:
        return ""
    sents = [s.strip() for s in re.split(r"(?<=[.!?])\s+", text) if s.strip()]
    if len(sents) >= 2:
        return "\n".join(textwrap.fill(s, width=width) for s in sents[:2])
    return textwrap.fill(text, width=width)


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
        narration = scene.narration.strip()
        body = scene.body.strip()
        if narration and (not body or body.lower() in _GENERIC_BODIES or body.lower() in scene.title.lower()):
            scene.body = _caption_from_narration(narration)
        elif narration and not body:
            scene.body = _caption_from_narration(narration)
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
    out_dir = Path(env_dir).expanduser() if env_dir else Path.home() / "Videos" / "arka-generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"{slug}-{ts}.mp4"


def _hex_rgb(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")
    if len(c) == 3:
        c = "".join(ch * 2 for ch in c)
    return int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16)


def _load_font(ImageFont, path: Path | None, size: int):
    if path and path.is_file():
        try:
            return ImageFont.truetype(str(path), size=size)
        except OSError:
            pass
    return ImageFont.load_default()


def render_slide(
    image_path: Path | None,
    scene: Scene,
    output: Path,
    cfg: VideoConfig,
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
    title_font = _load_font(ImageFont, cfg.font_bold_path or cfg.font_path, cfg.title_size)
    body_font = _load_font(ImageFont, cfg.font_path, cfg.body_size)
    margin = 96
    y = cfg.height // 4
    accent = _hex_rgb(cfg.accent_color)
    text = _hex_rgb(cfg.text_color)
    draw.rectangle([margin - 20, y - 16, margin + 8, y + cfg.title_size], fill=accent)
    for line in textwrap.wrap(scene.title, width=24):
        draw.text((margin, y), line, font=title_font, fill=text)
        y += cfg.title_size + 8
    y += 24
    body_text = _slide_body(scene)
    if body_text:
        for block in body_text.split("\n"):
            for line in textwrap.wrap(block.strip(), width=38):
                draw.text((margin, y), line, font=body_font, fill=(226, 232, 240))
                y += cfg.body_size + 10
            y += 6
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


def _scene_clip(slide: Path, duration: float, output: Path, cfg: VideoConfig) -> None:
    ffmpeg = _require_ffmpeg()
    frames = max(int(duration * cfg.fps), cfg.fps)
    zoom = (
        f"scale={cfg.width * 4}:{cfg.height * 4},"
        f"zoompan=z='min(zoom+0.0008,1.08)':x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
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


async def _edge_tts(text: str, voice: str, output: Path) -> None:
    try:
        import edge_tts
    except ImportError as exc:
        raise RuntimeError("edge-tts not installed — pip install edge-tts  or  set VIDEO_TTS=none") from exc
    if not voice:
        voice = os.environ.get("SPEAK_VOICE", "") or "en-US-GuyNeural"
    communicate = edge_tts.Communicate(text.strip(), voice)
    await communicate.save(str(output))


def _synthesize_narration(text: str, output: Path, cfg: VideoConfig) -> bool:
    if not text.strip() or cfg.tts in {"none", "off", "0"}:
        return False
    if cfg.tts in {"edge", "auto", ""}:
        try:
            asyncio.run(_edge_tts(text, cfg.tts_voice, output))
            return output.is_file()
        except Exception as exc:
            print(f"  TTS skipped: {exc}", file=sys.stderr)
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
        if not scene.image_query.strip():
            scene.image_query = scene.title or topic


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
    _attach_photo_queries(scenes, topic)

    work = Path(tempfile.mkdtemp(prefix="arka-video-"))
    clips: list[Path] = []
    audio_tracks: list[Path] = []
    credits: list[dict] = []

    try:
        used_photo_ids: set[str] = set()
        for i, scene in enumerate(scenes):
            print(f"  Scene {i + 1}/{len(scenes)}: {scene.title}", file=sys.stderr)
            query = scene.image_query or scene.title or topic
            photos = search_photos(query, count=5, orientation=cfg.orientation)
            photo = next((p for p in photos if p.id not in used_photo_ids), photos[0])
            used_photo_ids.add(photo.id)
            img_path = work / f"photo-{i:02d}.jpg"
            download_photo(photo, img_path)
            scene.photo = photo
            credits.append(
                {
                    "scene": scene.title,
                    "query": query,
                    "photographer": photo.photographer,
                    "url": photo.photographer_url,
                }
            )

            slide = work / f"slide-{i:02d}.png"
            render_slide(img_path, scene, slide, cfg)

            narration = (scene.narration or scene.body or scene.title).strip()
            audio_path = work / f"narration-{i:02d}.mp3"
            has_audio = _synthesize_narration(narration, audio_path, cfg)
            duration = scene.duration
            if has_audio:
                duration = _ffprobe_duration(audio_path) + 0.35
                audio_tracks.append(audio_path)
            if duration <= 0:
                duration = cfg.scene_sec
            duration = max(duration, 2.5)

            clip = work / f"clip-{i:02d}.mp4"
            _scene_clip(slide, duration, clip, cfg)
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
                            "image_query": s.image_query,
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
        scenes.append(
            Scene(
                title=title,
                narration=_normalize_scene_text(row.get("narration") or row.get("voiceover")),
                body=_normalize_scene_text(row.get("body") or row.get("subtitle")),
                image_query=str(row.get("image_query") or row.get("image") or "").strip(),
                duration=float(row.get("duration") or 0),
            )
        )
    return scenes


def _scene_bounds() -> tuple[int, int]:
    min_s = max(2, _env_int("VIDEO_MIN_SCENES", 3))
    max_s = max(min_s, _env_int("VIDEO_MAX_SCENES", 10))
    return min_s, max_s


def _llm_script(topic: str, *, scenes: int | None = None) -> list[Scene]:
    try:
        from arka.llm.fallback import llm_complete
    except ImportError as exc:
        raise SystemExit("LLM script generation requires arka chat deps (pip install 'arka-agent[chat]')") from exc

    min_scenes, max_scenes = _scene_bounds()
    system = (
        "You write concise YouTube tech/info video scripts. "
        "Return ONLY a JSON array (no markdown). Each item: "
        '{"title":"...", "narration":"2-3 spoken sentences", '
        '"body":"plain on-screen text mirroring narration (not a list or array)", '
        '"image_query":"2-4 word Unsplash search"}'
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
        "The body field must mirror the narration (short phrases the viewer reads while listening)."
    )
    text = llm_complete(system, user, temperature=0.4, task="compose_video")
    text = text.strip()
    if text.startswith("```"):
        text = re.sub(r"^```(?:json)?\s*", "", text)
        text = re.sub(r"\s*```$", "", text)
    parsed = _parse_scenes_json(text)
    if len(parsed) < 2:
        raise SystemExit("LLM did not return a usable scene script.")
    if scenes is None and len(parsed) > max_scenes:
        parsed = parsed[:max_scenes]
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

    compose_intent = re.search(
        r"(?i)(?:^|\b)(?:make|create|compose|build|render|produce|generate|arka)\s+(?:a\s+|an\s+)?"
        r"(?:(?:youtube|info|tech|explainer)\s+)?video\s+(?:on|about|for|explaining)\s+\S",
        t,
    ) or re.search(r"(?i)\b(?:youtube|info|tech|explainer)\s+video\b", t)
    if not compose_intent:
        return []

    topic = normalize_topic(t)
    if not topic or re.search(r"(?i)\b(generate|create|make)\b.*\bvideo\b", topic):
        return []
    argv = ["compose", "--topic", topic]
    if re.search(r"(?i)\b(llm|write script)\b", t):
        argv.append("--llm")
    return argv


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Compose info/YouTube videos with Unsplash images, ffmpeg, and optional TTS"
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
        print(f"✗ {setup_hint()}", file=sys.stderr)
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
            else:
                print("Writing script with LLM (auto scene count) …", file=sys.stderr)
            try:
                scenes = _llm_script(topic, scenes=args.scenes)
                if args.scenes is None:
                    print(f"  LLM chose {len(scenes)} scenes", file=sys.stderr)
            except SystemExit as exc:
                print(f"  LLM script failed ({exc}); using template.", file=sys.stderr)
                scenes = _template_script(topic)
        else:
            scenes = _template_script(topic)

    if not scenes:
        print("Provide --topic or --script", file=sys.stderr)
        return 1
    if not topic:
        topic = scenes[0].title

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
