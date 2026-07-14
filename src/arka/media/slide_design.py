"""Presentation design tokens — style presets, themes, and VideoConfig overrides."""

from __future__ import annotations

import copy
import re
from dataclasses import dataclass
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from arka.media.compose_video import VideoConfig

SLIDE_THEMES = ("dark", "light", "minimal")
SLIDE_KINDS = ("title", "section", "content")

# 8px spacing grid (relative to 1080p slide height)
GRID_PX = 8
SLIDE_HEIGHT_PX = 1080

# Per-style default theme when --theme is omitted
STYLE_DEFAULT_THEME = {
    "executive": "dark",
    "pitch": "dark",
    "academic": "light",
}

# (bg, text, accent, muted, surface, bullet)
_PALETTES: dict[str, dict[str, tuple[str, str, str, str, str, str]]] = {
    "executive": {
        "dark": ("#0f172a", "#f8fafc", "#2563eb", "#94a3b8", "#1e293b", "#e2e8f0"),
        "light": ("#f1f5f9", "#0f172a", "#1d4ed8", "#475569", "#ffffff", "#334155"),
        "minimal": ("#ffffff", "#1e293b", "#334155", "#64748b", "#f8fafc", "#475569"),
    },
    "pitch": {
        "dark": ("#09090b", "#fafafa", "#8b5cf6", "#a1a1aa", "#18181b", "#e4e4e7"),
        "light": ("#faf5ff", "#18181b", "#7c3aed", "#52525b", "#ffffff", "#3f3f46"),
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
    title_font: str
    body_font: str


def spacing_units(units: int = 1) -> float:
    """Return vertical spacing as a fraction of slide height (8px grid)."""
    return (GRID_PX * units) / SLIDE_HEIGHT_PX


def _hex_to_rgb(color: str) -> tuple[int, int, int]:
    c = color.lstrip("#")
    if len(c) != 6:
        return (0, 0, 0)
    return (int(c[0:2], 16), int(c[2:4], 16), int(c[4:6], 16))


def _relative_luminance(rgb: tuple[int, int, int]) -> float:
    def channel(c: int) -> float:
        s = c / 255.0
        return s / 12.92 if s <= 0.03928 else ((s + 0.055) / 1.055) ** 2.4

    r, g, b = rgb
    return 0.2126 * channel(r) + 0.7152 * channel(g) + 0.0722 * channel(b)


def contrast_ratio(foreground: str, background: str) -> float:
    """WCAG contrast ratio between two hex colors."""
    l1 = _relative_luminance(_hex_to_rgb(foreground))
    l2 = _relative_luminance(_hex_to_rgb(background))
    lighter, darker = max(l1, l2), min(l1, l2)
    return (lighter + 0.05) / (darker + 0.05)


def palette_meets_wcag_aa(palette: SlidePalette, *, min_ratio: float = 4.5) -> bool:
    """True when primary text and bullets meet WCAG AA on the slide background."""
    return (
        contrast_ratio(palette.text, palette.bg) >= min_ratio
        and contrast_ratio(palette.bullet, palette.bg) >= min_ratio
    )


def title_font_family(style: str) -> str:
    return "serif" if style == "academic" else "sans-serif"


def body_font_family(style: str) -> str:
    return "serif" if style == "academic" else "sans-serif"


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
    title_font = title_font_family(style)
    body_font = body_font_family(style)
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
            title_font=title_font,
            body_font=body_font,
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
            title_font=title_font,
            body_font=body_font,
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
        title_font=title_font,
        body_font=body_font,
    )


def is_traction_slide(title: str, *, style: str = "executive") -> bool:
    """Pitch-deck traction slide — render metric callout boxes."""
    if style != "pitch":
        return False
    lower = (title or "").strip().lower()
    return bool(re.search(r"\b(traction|metrics|growth|momentum)\b", lower))


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
