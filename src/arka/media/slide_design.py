"""Presentation design tokens — style presets, themes, and VideoConfig overrides."""

from __future__ import annotations

import copy
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from arka.media.compose_video import VideoConfig

SLIDE_THEMES = ("dark", "light", "minimal")
SLIDE_KINDS = ("title", "section", "content")

# Per-style default theme when --theme is omitted
STYLE_DEFAULT_THEME = {
    "executive": "dark",
    "pitch": "dark",
    "academic": "light",
}

# (bg, text, accent, muted, surface, bullet)
_PALETTES: dict[str, dict[str, tuple[str, str, str, str, str, str]]] = {
    "executive": {
        "dark": ("#0f172a", "#f8fafc", "#2563eb", "#94a3b8", "#1e293b", "#cbd5e1"),
        "light": ("#f1f5f9", "#0f172a", "#1d4ed8", "#64748b", "#ffffff", "#334155"),
        "minimal": ("#ffffff", "#1e293b", "#334155", "#64748b", "#f8fafc", "#475569"),
    },
    "pitch": {
        "dark": ("#09090b", "#fafafa", "#8b5cf6", "#a1a1aa", "#18181b", "#d4d4d8"),
        "light": ("#faf5ff", "#18181b", "#7c3aed", "#71717a", "#ffffff", "#3f3f46"),
        "minimal": ("#ffffff", "#09090b", "#6d28d9", "#737373", "#fafafa", "#404040"),
    },
    "academic": {
        "dark": ("#1c1917", "#fafaf9", "#78716c", "#a8a29e", "#292524", "#d6d3d1"),
        "light": ("#faf9f7", "#1c1917", "#57534e", "#78716c", "#ffffff", "#44403c"),
        "minimal": ("#ffffff", "#292524", "#57534e", "#a8a29e", "#fafaf9", "#44403c"),
    },
}


@dataclass(frozen=True)
class SlidePalette:
    bg: str
    text: str
    accent: str
    muted: str
    surface: str
    bullet: str


@dataclass(frozen=True)
class SlideTypography:
    title_size: int
    subtitle_size: int
    body_size: int
    bullet_size: int
    section_size: int
    title_lines: int
    body_lines: int
    max_bullets: int
    margin_x: float  # fraction of width
    margin_y: float  # fraction of height
    line_spacing: float


def normalize_slide_theme(name: str | None, *, style: str = "executive") -> str:
    raw = (name or "").strip().lower()
    if raw in SLIDE_THEMES:
        return raw
    return STYLE_DEFAULT_THEME.get(style, "dark")


def slide_palette(style: str, theme: str) -> SlidePalette:
    style = style if style in _PALETTES else "executive"
    theme = normalize_slide_theme(theme, style=style)
    bg, text, accent, muted, surface, bullet = _PALETTES[style][theme]
    return SlidePalette(bg=bg, text=text, accent=accent, muted=muted, surface=surface, bullet=bullet)


def slide_typography(style: str) -> SlideTypography:
    """Style-specific type scale and density limits."""
    if style == "pitch":
        return SlideTypography(
            title_size=52,
            subtitle_size=26,
            body_size=24,
            bullet_size=22,
            section_size=44,
            title_lines=2,
            body_lines=2,
            max_bullets=4,
            margin_x=0.08,
            margin_y=0.10,
            line_spacing=1.35,
        )
    if style == "academic":
        return SlideTypography(
            title_size=44,
            subtitle_size=22,
            body_size=22,
            bullet_size=20,
            section_size=40,
            title_lines=2,
            body_lines=3,
            max_bullets=4,
            margin_x=0.10,
            margin_y=0.12,
            line_spacing=1.45,
        )
    # executive
    return SlideTypography(
        title_size=48,
        subtitle_size=24,
        body_size=22,
        bullet_size=20,
        section_size=42,
        title_lines=2,
        body_lines=2,
        max_bullets=4,
        margin_x=0.09,
        margin_y=0.11,
        line_spacing=1.4,
    )


def apply_slide_design(
    cfg: VideoConfig,
    *,
    style: str = "executive",
    theme: str | None = None,
) -> VideoConfig:
    """Return a copy of VideoConfig with presentation style/theme colors applied."""
    theme = normalize_slide_theme(theme, style=style)
    palette = slide_palette(style, theme)
    typo = slide_typography(style)
    out = copy.copy(cfg)
    out.bg_color = palette.bg
    out.text_color = palette.text
    out.accent_color = palette.accent
    out.title_size = typo.title_size
    out.body_size = typo.body_size
    return out


def infer_slide_kind(scene, *, index: int, total: int) -> str:
    """Resolve slide layout from explicit kind or heuristics."""
    kind = getattr(scene, "slide_kind", "") or ""
    if kind in SLIDE_KINDS:
        return kind
    if index == 0:
        return "title"
    title_lower = (scene.title or "").strip().lower()
    if title_lower.startswith("section:") or title_lower.startswith("part "):
        return "section"
    caps = getattr(scene, "captions", None) or []
    if caps:
        return "content"
    body = (getattr(scene, "body", "") or "").strip()
    if body and index > 0:
        return "content"
    if index == total - 1 and not caps:
        return "content"
    return "content"
