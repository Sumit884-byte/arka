"""Visual style presets for meme templates and video generation."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from arka.media.compose_video import VideoConfig

StyleName = str


def _rgb(hex_color: str) -> tuple[int, int, int]:
    c = hex_color.lstrip("#")
    if len(c) != 6:
        return (255, 255, 255)
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))


@dataclass(frozen=True)
class MemeStyle:
    name: str
    label: str
    text_color: tuple[int, int, int]
    outline_color: tuple[int, int, int]
    outline_width: int
    header_bg: tuple[int, int, int]
    header_text: tuple[int, int, int]
    panel_left: tuple[int, int, int]
    panel_right: tuple[int, int, int]
    panel_neutral: tuple[int, int, int]
    title_font_size: int
    body_font_size: int
    stock_suffix: str
    overlay_alpha: float = 0.0
    overlay_color: tuple[int, int, int] = (0, 0, 0)
    divider_color: tuple[int, int, int] = (255, 255, 255)


@dataclass(frozen=True)
class VideoStyle:
    name: str
    label: str
    bg_color: str
    text_color: str
    accent_color: str
    title_size: int
    body_size: int
    scene_sec: float
    crf: int
    ffmpeg_preset: str
    stock_suffix: str
    ai_prompt_suffix: str
    ai_video_suffix: str


MEME_STYLES: dict[StyleName, MemeStyle] = {
    "classic": MemeStyle(
        name="classic",
        label="Classic meme",
        text_color=(255, 255, 255),
        outline_color=(0, 0, 0),
        outline_width=2,
        header_bg=(10, 22, 40),
        header_text=(255, 255, 255),
        panel_left=(45, 55, 72),
        panel_right=(26, 54, 93),
        panel_neutral=(55, 65, 81),
        title_font_size=20,
        body_font_size=28,
        stock_suffix="",
        overlay_alpha=0.35,
    ),
    "dark": MemeStyle(
        name="dark",
        label="Dark mode",
        text_color=(248, 250, 252),
        outline_color=(15, 23, 42),
        outline_width=1,
        header_bg=(2, 6, 23),
        header_text=(226, 232, 240),
        panel_left=(30, 41, 59),
        panel_right=(15, 23, 42),
        panel_neutral=(51, 65, 85),
        title_font_size=20,
        body_font_size=26,
        stock_suffix="dark moody",
        overlay_alpha=0.45,
        overlay_color=(2, 6, 23),
    ),
    "neon": MemeStyle(
        name="neon",
        label="Neon cyber",
        text_color=(34, 211, 238),
        outline_color=(88, 28, 135),
        outline_width=3,
        header_bg=(24, 0, 48),
        header_text=(250, 204, 255),
        panel_left=(49, 0, 98),
        panel_right=(22, 0, 44),
        panel_neutral=(39, 0, 78),
        title_font_size=22,
        body_font_size=30,
        stock_suffix="neon lights cyberpunk night",
        overlay_alpha=0.5,
        overlay_color=(15, 0, 30),
    ),
    "retro": MemeStyle(
        name="retro",
        label="Retro 80s",
        text_color=(255, 237, 160),
        outline_color=(127, 29, 29),
        outline_width=2,
        header_bg=(120, 53, 15),
        header_text=(254, 243, 199),
        panel_left=(154, 52, 18),
        panel_right=(124, 45, 18),
        panel_neutral=(180, 83, 9),
        title_font_size=20,
        body_font_size=28,
        stock_suffix="retro vintage 80s film grain",
        overlay_alpha=0.3,
        overlay_color=(69, 26, 3),
    ),
    "corporate": MemeStyle(
        name="corporate",
        label="Corporate clean",
        text_color=(255, 255, 255),
        outline_color=(30, 58, 138),
        outline_width=1,
        header_bg=(30, 64, 175),
        header_text=(239, 246, 255),
        panel_left=(37, 99, 235),
        panel_right=(29, 78, 216),
        panel_neutral=(59, 130, 246),
        title_font_size=20,
        body_font_size=26,
        stock_suffix="professional office business",
        overlay_alpha=0.25,
        overlay_color=(15, 23, 42),
    ),
    "comic": MemeStyle(
        name="comic",
        label="Comic book",
        text_color=(255, 255, 0),
        outline_color=(0, 0, 0),
        outline_width=4,
        header_bg=(220, 38, 38),
        header_text=(255, 255, 255),
        panel_left=(239, 68, 68),
        panel_right=(37, 99, 235),
        panel_neutral=(250, 204, 21),
        title_font_size=24,
        body_font_size=32,
        stock_suffix="comic pop art bold colors",
        overlay_alpha=0.2,
    ),
    "cinematic": MemeStyle(
        name="cinematic",
        label="Cinematic film",
        text_color=(251, 191, 36),
        outline_color=(0, 0, 0),
        outline_width=2,
        header_bg=(17, 24, 39),
        header_text=(253, 230, 138),
        panel_left=(31, 41, 55),
        panel_right=(15, 23, 42),
        panel_neutral=(55, 65, 81),
        title_font_size=20,
        body_font_size=28,
        stock_suffix="cinematic golden hour film",
        overlay_alpha=0.4,
        overlay_color=(0, 0, 0),
    ),
    "minimal": MemeStyle(
        name="minimal",
        label="Minimal flat",
        text_color=(30, 41, 59),
        outline_color=(255, 255, 255),
        outline_width=1,
        header_bg=(241, 245, 249),
        header_text=(15, 23, 42),
        panel_left=(226, 232, 240),
        panel_right=(203, 213, 225),
        panel_neutral=(248, 250, 252),
        title_font_size=18,
        body_font_size=24,
        stock_suffix="minimal clean white space",
        overlay_alpha=0.15,
        overlay_color=(255, 255, 255),
    ),
    "vaporwave": MemeStyle(
        name="vaporwave",
        label="Vaporwave",
        text_color=(244, 114, 182),
        outline_color=(67, 56, 202),
        outline_width=2,
        header_bg=(76, 29, 149),
        header_text=(250, 232, 255),
        panel_left=(109, 40, 217),
        panel_right=(59, 7, 100),
        panel_neutral=(126, 34, 206),
        title_font_size=22,
        body_font_size=28,
        stock_suffix="vaporwave aesthetic pink purple sunset",
        overlay_alpha=0.35,
        overlay_color=(46, 16, 101),
    ),
    "newspaper": MemeStyle(
        name="newspaper",
        label="Newspaper headline",
        text_color=(17, 24, 39),
        outline_color=(255, 255, 255),
        outline_width=1,
        header_bg=(250, 250, 249),
        header_text=(28, 25, 23),
        panel_left=(231, 229, 228),
        panel_right=(214, 211, 209),
        panel_neutral=(245, 245, 244),
        title_font_size=18,
        body_font_size=26,
        stock_suffix="newspaper editorial black white",
        overlay_alpha=0.1,
        overlay_color=(255, 255, 255),
    ),
}

VIDEO_STYLES: dict[StyleName, VideoStyle] = {
    "documentary": VideoStyle(
        name="documentary",
        label="Documentary (default)",
        bg_color="#0f172a",
        text_color="#f8fafc",
        accent_color="#38bdf8",
        title_size=58,
        body_size=34,
        scene_sec=5.0,
        crf=18,
        ffmpeg_preset="medium",
        stock_suffix="documentary professional",
        ai_prompt_suffix="documentary style, photorealistic, natural lighting",
        ai_video_suffix="documentary style, natural lighting, steady camera",
    ),
    "cinematic": VideoStyle(
        name="cinematic",
        label="Cinematic film",
        bg_color="#0c0a09",
        text_color="#fafaf9",
        accent_color="#fbbf24",
        title_size=62,
        body_size=36,
        scene_sec=6.5,
        crf=16,
        ffmpeg_preset="slow",
        stock_suffix="cinematic golden hour film grain",
        ai_prompt_suffix="cinematic widescreen, shallow depth of field, film grain, dramatic lighting",
        ai_video_suffix="cinematic film look, smooth camera motion, golden hour lighting",
    ),
    "tech": VideoStyle(
        name="tech",
        label="Tech / cyber",
        bg_color="#020617",
        text_color="#e2e8f0",
        accent_color="#22d3ee",
        title_size=56,
        body_size=32,
        scene_sec=4.5,
        crf=18,
        ffmpeg_preset="medium",
        stock_suffix="technology futuristic digital",
        ai_prompt_suffix="futuristic tech aesthetic, neon accents, clean UI, high detail",
        ai_video_suffix="tech product video, sleek motion graphics feel, cool blue lighting",
    ),
    "minimal": VideoStyle(
        name="minimal",
        label="Minimal light",
        bg_color="#ffffff",
        text_color="#1e293b",
        accent_color="#334155",
        title_size=52,
        body_size=30,
        scene_sec=4.0,
        crf=20,
        ffmpeg_preset="medium",
        stock_suffix="minimal clean white background",
        ai_prompt_suffix="minimal flat design, soft shadows, lots of whitespace",
        ai_video_suffix="minimal clean aesthetic, soft natural light, simple composition",
    ),
    "neon": VideoStyle(
        name="neon",
        label="Neon nightlife",
        bg_color="#090014",
        text_color="#f5d0fe",
        accent_color="#e879f9",
        title_size=58,
        body_size=34,
        scene_sec=4.0,
        crf=18,
        ffmpeg_preset="medium",
        stock_suffix="neon lights night city cyberpunk",
        ai_prompt_suffix="neon glow, cyberpunk palette, high contrast, vivid colors",
        ai_video_suffix="neon cyberpunk city at night, vibrant lights, dynamic motion",
    ),
    "retro": VideoStyle(
        name="retro",
        label="Retro vintage",
        bg_color="#292524",
        text_color="#fef3c7",
        accent_color="#fb923c",
        title_size=54,
        body_size=32,
        scene_sec=5.5,
        crf=19,
        ffmpeg_preset="medium",
        stock_suffix="retro vintage 80s 90s film",
        ai_prompt_suffix="retro vintage aesthetic, warm tones, slight film grain",
        ai_video_suffix="retro VHS aesthetic, warm colors, nostalgic mood",
    ),
    "news": VideoStyle(
        name="news",
        label="News broadcast",
        bg_color="#1e3a8a",
        text_color="#ffffff",
        accent_color="#ef4444",
        title_size=60,
        body_size=36,
        scene_sec=3.5,
        crf=20,
        ffmpeg_preset="fast",
        stock_suffix="news broadcast studio journalism",
        ai_prompt_suffix="news broadcast graphic style, bold typography zones, high contrast",
        ai_video_suffix="news segment b-roll, professional broadcast look",
    ),
    "social": VideoStyle(
        name="social",
        label="Social / Shorts",
        bg_color="#18181b",
        text_color="#fafafa",
        accent_color="#a855f7",
        title_size=64,
        body_size=38,
        scene_sec=3.0,
        crf=22,
        ffmpeg_preset="fast",
        stock_suffix="social media vertical energetic",
        ai_prompt_suffix="bold social media aesthetic, punchy colors, mobile-first framing",
        ai_video_suffix="short-form social video, fast-paced, vertical-friendly energy",
    ),
    "corporate": VideoStyle(
        name="corporate",
        label="Corporate pitch",
        bg_color="#f8fafc",
        text_color="#0f172a",
        accent_color="#2563eb",
        title_size=54,
        body_size=32,
        scene_sec=5.0,
        crf=18,
        ffmpeg_preset="medium",
        stock_suffix="corporate office professional team",
        ai_prompt_suffix="corporate presentation style, clean professional, trustworthy",
        ai_video_suffix="corporate brand video, polished professional look",
    ),
    "nature": VideoStyle(
        name="nature",
        label="Nature documentary",
        bg_color="#14532d",
        text_color="#ecfdf5",
        accent_color="#86efac",
        title_size=56,
        body_size=34,
        scene_sec=6.0,
        crf=17,
        ffmpeg_preset="slow",
        stock_suffix="nature landscape wildlife outdoors",
        ai_prompt_suffix="nature documentary, lush landscapes, organic colors, serene",
        ai_video_suffix="nature documentary b-roll, sweeping landscapes, calm motion",
    ),
}

_STYLE_WORDS = sorted(set(MEME_STYLES) | set(VIDEO_STYLES), key=len, reverse=True)


def list_meme_styles() -> list[str]:
    return list(MEME_STYLES)


def list_video_styles() -> list[str]:
    return list(VIDEO_STYLES)


def resolve_meme_style(name: str | None) -> MemeStyle:
    key = (name or "").strip().lower()
    env = __import__("os").environ.get("MEME_STYLE", "").strip().lower()
    if not key:
        key = env or "classic"
    return MEME_STYLES.get(key, MEME_STYLES["classic"])


def resolve_video_style(name: str | None) -> VideoStyle:
    key = (name or "").strip().lower()
    env = __import__("os").environ.get("VIDEO_STYLE", "").strip().lower()
    if not key:
        key = env or "documentary"
    return VIDEO_STYLES.get(key, VIDEO_STYLES["documentary"])


def apply_video_style(cfg: VideoConfig, style_name: str | None = None) -> VideoConfig:
    """Return a copy of VideoConfig with style preset colors and pacing applied."""
    style = resolve_video_style(style_name)
    out = copy.copy(cfg)
    out.visual_style = style.name
    out.bg_color = style.bg_color
    out.text_color = style.text_color
    out.accent_color = style.accent_color
    out.title_size = style.title_size
    out.body_size = style.body_size
    out.scene_sec = style.scene_sec
    out.crf = style.crf
    out.preset = style.ffmpeg_preset
    return out


def styled_stock_query(base: str, style_name: str | None, *, for_meme: bool = False) -> str:
    base = (base or "").strip()
    style = resolve_meme_style(style_name) if for_meme else resolve_video_style(style_name)
    suffix = style.stock_suffix.strip()
    if not suffix:
        return base
    if not base:
        return suffix
    if suffix.lower() in base.lower():
        return base
    return f"{base} {suffix}"


def styled_ai_prompt(base: str, style_name: str | None) -> str:
    base = (base or "").strip()
    suffix = resolve_video_style(style_name).ai_prompt_suffix.strip()
    if not suffix or suffix.lower() in base.lower():
        return base
    return f"{base}, {suffix}" if base else suffix


def styled_ai_video_prompt(base: str, style_name: str | None) -> str:
    base = (base or "").strip()
    suffix = resolve_video_style(style_name).ai_video_suffix.strip()
    if not suffix or suffix.lower() in base.lower():
        return base
    return f"{base}, {suffix}" if base else suffix


def extract_style_from_text(text: str) -> tuple[str, str | None]:
    """Return (text_without_style, style_name) when a known style is mentioned."""
    t = (text or "").strip()
    if not t:
        return t, None
    for style in _STYLE_WORDS:
        patterns = (
            rf"(?i)\b{re.escape(style)}\s+style\b",
            rf"(?i)\bstyle\s+{re.escape(style)}\b",
            rf"(?i)\b{re.escape(style)}\s+(?:meme|video|look|aesthetic)\b",
        )
        for pattern in patterns:
            if re.search(pattern, t):
                cleaned = re.sub(pattern, " ", t, count=1)
                cleaned = re.sub(r"\s+", " ", cleaned).strip()
                return cleaned, style.lower()
    return t, None


def format_style_catalog(*, kind: str = "all") -> str:
    lines: list[str] = []
    if kind in ("all", "meme"):
        lines.append("Meme styles:")
        for name, style in MEME_STYLES.items():
            lines.append(f"  {name:12} — {style.label}")
    if kind in ("all", "video"):
        if lines:
            lines.append("")
        lines.append("Video styles:")
        for name, style in VIDEO_STYLES.items():
            lines.append(f"  {name:12} — {style.label}")
    return "\n".join(lines)


def media_styles_catalog(*, kind: str = "all", as_json: bool = False) -> str | dict[str, object]:
    """Return shared meme/video/infographic style presets for MCP and agents."""
    payload: dict[str, object] = {}
    if kind in ("all", "meme"):
        payload["meme"] = {name: style.label for name, style in MEME_STYLES.items()}
    if kind in ("all", "video"):
        payload["video"] = {name: style.label for name, style in VIDEO_STYLES.items()}
    if kind in ("all", "infographic"):
        try:
            from arka.agent.infographic import INFOGRAPHIC_STYLES

            payload["infographic"] = {name: style.label for name, style in INFOGRAPHIC_STYLES.items()}
        except ImportError:
            payload["infographic"] = {}
    if as_json:
        return payload
    lines: list[str] = []
    for section, styles in payload.items():
        if lines:
            lines.append("")
        lines.append(f"{section.title()} styles:")
        if isinstance(styles, dict):
            for name, label in styles.items():
                lines.append(f"  {name:12} — {label}")
    return "\n".join(lines)
