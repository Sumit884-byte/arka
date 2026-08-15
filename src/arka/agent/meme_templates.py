"""Reusable meme layouts — local Pillow compositor, optional stock-photo panels."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import sys
import tempfile
from datetime import datetime
from pathlib import Path

from arka.media.media_styles import (
    MemeStyle,
    extract_style_from_text,
    format_style_catalog,
    list_meme_styles,
    resolve_meme_style,
    styled_stock_query,
    MEME_STYLES,
)

PANEL_WIDTH = 800
PANEL_HEIGHT = 600
HEADER_HEIGHT = 48


def _require_pillow():
    try:
        from PIL import Image, ImageDraw, ImageFont

        return Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError(
            "meme templates require Pillow: pip install Pillow"
        ) from exc


def default_output(template: str, slug: str = "") -> Path:
    name = slug or template
    safe = re.sub(r"[^a-z0-9]+", "-", name.lower())[:40].strip("-") or template
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    env_dir = os.environ.get("IMAGE_OUTPUT_DIR", "").strip()
    out_dir = Path(env_dir).expanduser() if env_dir else Path.home() / "Pictures" / "arka-generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"meme-{safe}-{ts}.png"


def _font(size: int = 24):
    _, _, ImageFont = _require_pillow()
    for path in (
        "/System/Library/Fonts/Supplemental/Impact.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:\\Windows\\Fonts\\impact.ttf",
    ):
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap_text(text: str, font, max_width: int, draw) -> list[str]:
    lines: list[str] = []
    for paragraph in text.splitlines() or [""]:
        words = paragraph.split()
        if not words:
            lines.append("")
            continue
        current: list[str] = []
        for word in words:
            trial = " ".join([*current, word])
            box = draw.textbbox((0, 0), trial, font=font)
            if box[2] - box[0] <= max_width:
                current.append(word)
            else:
                if current:
                    lines.append(" ".join(current))
                current = [word]
        if current:
            lines.append(" ".join(current))
    return lines or [""]


def _draw_centered_text(
    draw,
    text: str,
    box: tuple[int, int, int, int],
    *,
    font,
    style: MemeStyle | None = None,
    fill=None,
    outline=None,
    outline_width: int | None = None,
) -> None:
    meme_style = style or resolve_meme_style(None)
    fill = fill if fill is not None else meme_style.text_color
    outline = outline if outline is not None else meme_style.outline_color
    outline_width = meme_style.outline_width if outline_width is None else outline_width
    x0, y0, x1, y1 = box
    max_width = x1 - x0 - 24
    lines = _wrap_text(text, font, max_width, draw)
    line_height = draw.textbbox((0, 0), "Ay", font=font)[3] + 6
    total_height = line_height * len(lines)
    y = y0 + max(0, (y1 - y0 - total_height) // 2)
    for line in lines:
        box = draw.textbbox((0, 0), line, font=font)
        line_width = box[2] - box[0]
        x = x0 + (x1 - x0 - line_width) // 2
        for dx in range(-outline_width, outline_width + 1):
            for dy in range(-outline_width, outline_width + 1):
                if dx or dy:
                    draw.text((x + dx, y + dy), line, font=font, fill=outline)
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height


def _text_panel(
    text: str,
    width: int,
    height: int,
    bg: tuple[int, int, int],
    *,
    font_size: int = 28,
    style: MemeStyle | None = None,
) -> object:
    Image, ImageDraw, _ = _require_pillow()
    meme_style = style or resolve_meme_style(None)
    panel = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(panel)
    font = _font(font_size or meme_style.body_font_size)
    _draw_centered_text(
        draw,
        text,
        (12, 12, width - 12, height - 12),
        font=font,
        style=meme_style,
        outline_width=max(1, meme_style.outline_width - 1),
    )
    return panel


def _apply_style_overlay(panel, style: MemeStyle):
    if style.overlay_alpha <= 0:
        return panel
    Image, _, _ = _require_pillow()
    overlay = Image.new("RGB", panel.size, style.overlay_color)
    return Image.blend(panel, overlay, style.overlay_alpha)


def _load_image(path: str) -> object:
    Image, _, _ = _require_pillow()
    asset = Path(path).expanduser()
    if not asset.is_file():
        raise ValueError(f"image asset not found: {asset}")
    return Image.open(asset).convert("RGB")


def _fit_image(image, width: int, height: int):
    Image, _, _ = _require_pillow()
    fitted = image.copy()
    fitted.thumbnail((width, height))
    canvas = Image.new("RGB", (width, height), (20, 20, 20))
    x = (width - fitted.width) // 2
    y = (height - fitted.height) // 2
    canvas.paste(fitted, (x, y))
    return canvas


def _use_stock_images(explicit: bool | None = None) -> bool:
    if explicit is not None:
        return explicit
    return os.environ.get("MEME_USE_STOCK_PHOTOS", "1").strip().lower() not in (
        "0",
        "false",
        "no",
        "off",
    )


def _meme_stock_cache_dir() -> Path:
    env_dir = os.environ.get("MEME_STOCK_CACHE_DIR", "").strip()
    if env_dir:
        cache = Path(env_dir).expanduser()
    else:
        try:
            from arka.paths import cache_dir

            cache = cache_dir() / "meme-stock"
        except ImportError:
            cache = Path(tempfile.gettempdir()) / "arka-meme-stock"
    cache.mkdir(parents=True, exist_ok=True)
    return cache


def _fetch_stock_image_path(
    query: str,
    *,
    cache_dir: Path,
    exclude_ids: set[str] | None = None,
    context_terms: list[str] | None = None,
) -> str | None:
    query = (query or "").strip()
    if not query:
        return None
    try:
        from arka.media.stock_photos import (
            any_source_available,
            download_stock_photo,
            photo_uid,
            search_stock_photos,
        )
    except ImportError:
        return None
    if not any_source_available():
        return None
    try:
        photos = search_stock_photos(
            query,
            count=1,
            orientation="landscape",
            context_terms=context_terms,
            exclude_ids=exclude_ids,
        )
    except SystemExit:
        return None
    except Exception as exc:
        print(f"  Meme stock photo skipped ({query!r}): {exc}", file=sys.stderr)
        return None
    if not photos:
        return None
    photo = photos[0]
    dest = cache_dir / f"{photo.source}-{photo.id}.jpg"
    try:
        download_stock_photo(photo, dest)
    except Exception as exc:
        print(f"  Meme stock download failed ({query!r}): {exc}", file=sys.stderr)
        return None
    if exclude_ids is not None:
        exclude_ids.add(photo_uid(photo))
    print(f"  Meme panel photo: {photo.source} — {query!r}", file=sys.stderr)
    return str(dest)


def _stock_query_from_label(label: str, *, title: str = "") -> str:
    try:
        from arka.media.stock_photos import compact_photo_query, stock_search_query
    except ImportError:
        text = f"{title} {label}".strip()
        return text[:80] or "technology office"
    combined = " ".join(part for part in (title, label.replace("\n", " ")) if part).strip()
    return stock_search_query(compact_photo_query(combined))


def _resolve_panel(
    path: str | None,
    label: str | None,
    *,
    width: int,
    height: int,
    bg: tuple[int, int, int],
    stock_query: str | None = None,
    use_stock_images: bool = False,
    cache_dir: Path | None = None,
    exclude_ids: set[str] | None = None,
    overlay_label: bool = True,
    style: MemeStyle | None = None,
) -> tuple[object, str | None]:
    """Return (panel image, resolved image path or None)."""
    meme_style = style or resolve_meme_style(None)
    resolved_path = path
    stock_used: str | None = None
    if not resolved_path and use_stock_images and stock_query:
        if cache_dir is None:
            cache_dir = _meme_stock_cache_dir()
        query = styled_stock_query(stock_query, meme_style.name, for_meme=True)
        stock_used = _fetch_stock_image_path(
            query,
            cache_dir=cache_dir,
            exclude_ids=exclude_ids,
        )
        resolved_path = stock_used
    if resolved_path:
        panel = _fit_image(_load_image(resolved_path), width, height)
        panel = _apply_style_overlay(panel, meme_style)
        if label and overlay_label:
            _, ImageDraw, _ = _require_pillow()
            draw = ImageDraw.Draw(panel)
            _draw_centered_text(
                draw,
                label,
                (12, 12, width - 12, height - 12),
                font=_font(meme_style.body_font_size),
                style=meme_style,
            )
        return panel, resolved_path
    if label:
        return _text_panel(label, width, height, bg, style=meme_style), None
    raise ValueError("each panel needs an image path, stock query, or a text label")


def _save(canvas, output: str | None, template: str, slug: str = "") -> Path:
    target = Path(output).expanduser() if output else default_output(template, slug)
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target)
    return target


def comparison(
    *,
    left: str | None = None,
    right: str | None = None,
    left_title: str = "LEFT",
    right_title: str = "RIGHT",
    left_label: str | None = None,
    right_label: str | None = None,
    left_query: str | None = None,
    right_query: str | None = None,
    use_stock_images: bool | None = None,
    style: str | None = None,
    output: str | None = None,
) -> dict[str, object]:
    Image, ImageDraw, _ = _require_pillow()
    meme_style = resolve_meme_style(style)
    use_stock = _use_stock_images(use_stock_images)
    cache_dir = _meme_stock_cache_dir() if use_stock else None
    exclude_ids: set[str] = set()
    left_stock_query = left_query or (
        _stock_query_from_label(left_label, title=left_title) if left_label else None
    )
    right_stock_query = right_query or (
        _stock_query_from_label(right_label, title=right_title) if right_label else None
    )
    left_panel, left_resolved = _resolve_panel(
        left,
        left_label or (None if left else "LEFT"),
        width=PANEL_WIDTH,
        height=PANEL_HEIGHT,
        bg=meme_style.panel_left,
        stock_query=left_stock_query,
        use_stock_images=use_stock and not left,
        cache_dir=cache_dir,
        exclude_ids=exclude_ids,
        style=meme_style,
    )
    right_panel, right_resolved = _resolve_panel(
        right,
        right_label or (None if right else "RIGHT"),
        width=PANEL_WIDTH,
        height=PANEL_HEIGHT,
        bg=meme_style.panel_right,
        stock_query=right_stock_query,
        use_stock_images=use_stock and not right,
        cache_dir=cache_dir,
        exclude_ids=exclude_ids,
        style=meme_style,
    )
    width = max(left_panel.width, right_panel.width)
    height = max(left_panel.height, right_panel.height) + HEADER_HEIGHT
    canvas = Image.new("RGB", (width * 2, height), "white")
    draw = ImageDraw.Draw(canvas)
    font = _font(meme_style.title_font_size)
    for index, (panel, title) in enumerate(
        zip((left_panel, right_panel), (left_title, right_title))
    ):
        x_offset = index * width
        canvas.paste(panel, (x_offset, HEADER_HEIGHT))
        draw.rectangle((x_offset, 0, x_offset + width, HEADER_HEIGHT), fill=meme_style.header_bg)
        draw.text((x_offset + 18, 14), title, fill=meme_style.header_text, font=font)
    draw.line((width, 0, width, height), fill=meme_style.divider_color, width=3)
    target = _save(canvas, output, "comparison", slug=meme_style.name)
    return {
        "output": str(target),
        "template": "comparison",
        "style": meme_style.name,
        "token_cost": "local-only",
        "left": left_resolved or left,
        "right": right_resolved or right,
        "stock_images": bool(left_resolved or right_resolved),
    }


def drake(
    *,
    reject: str,
    accept: str,
    image: str | None = None,
    use_stock_images: bool | None = None,
    style: str | None = None,
    output: str | None = None,
) -> dict[str, object]:
    Image, ImageDraw, _ = _require_pillow()
    meme_style = resolve_meme_style(style)
    width, half = PANEL_WIDTH, PANEL_HEIGHT // 2
    resolved_image = image
    if not resolved_image and _use_stock_images(use_stock_images):
        resolved_image = _fetch_stock_image_path(
            styled_stock_query("person pointing gesture portrait", meme_style.name, for_meme=True),
            cache_dir=_meme_stock_cache_dir(),
        )
    if resolved_image:
        base = _apply_style_overlay(
            _fit_image(_load_image(resolved_image), width, PANEL_HEIGHT),
            meme_style,
        )
        top = base.crop((0, 0, width, half))
        bottom = base.crop((0, half, width, PANEL_HEIGHT))
    else:
        top = _text_panel(reject, width, half, meme_style.panel_left, font_size=24, style=meme_style)
        bottom = _text_panel(accept, width, half, meme_style.panel_right, font_size=24, style=meme_style)
    canvas = Image.new("RGB", (width, PANEL_HEIGHT), "white")
    canvas.paste(top, (0, 0))
    canvas.paste(bottom, (0, half))
    draw = ImageDraw.Draw(canvas)
    draw.line((0, half, width, half), fill=meme_style.divider_color, width=4)
    font = _font(meme_style.body_font_size + 4)
    if resolved_image:
        _draw_centered_text(draw, reject, (0, 0, width, half), font=font, style=meme_style)
        _draw_centered_text(draw, accept, (0, half, width, PANEL_HEIGHT), font=font, style=meme_style)
    target = _save(canvas, output, "drake", slug=meme_style.name)
    return {
        "output": str(target),
        "template": "drake",
        "style": meme_style.name,
        "token_cost": "local-only",
        "image": resolved_image,
        "stock_images": bool(resolved_image and not image),
    }


def caption(
    *,
    image: str | None = None,
    top: str = "",
    bottom: str = "",
    label: str | None = None,
    stock_query: str | None = None,
    use_stock_images: bool | None = None,
    style: str | None = None,
    output: str | None = None,
) -> dict[str, object]:
    Image, ImageDraw, _ = _require_pillow()
    meme_style = resolve_meme_style(style)
    resolved_image = image
    if not resolved_image and _use_stock_images(use_stock_images):
        query = stock_query or _stock_query_from_label(
            " ".join(part for part in (top, bottom, label or "") if part)
        )
        resolved_image = _fetch_stock_image_path(
            styled_stock_query(query, meme_style.name, for_meme=True),
            cache_dir=_meme_stock_cache_dir(),
        )
    if resolved_image:
        base = _apply_style_overlay(
            _fit_image(_load_image(resolved_image), PANEL_WIDTH, PANEL_HEIGHT),
            meme_style,
        )
    elif label:
        base = _text_panel(label, PANEL_WIDTH, PANEL_HEIGHT, meme_style.panel_neutral, style=meme_style)
    else:
        raise ValueError("caption needs --image, stock query, or --label")
    draw = ImageDraw.Draw(base)
    font = _font(meme_style.body_font_size + 8)
    if top:
        _draw_centered_text(draw, top.upper(), (0, 8, PANEL_WIDTH, PANEL_HEIGHT // 3), font=font, style=meme_style)
    if bottom:
        _draw_centered_text(
            draw,
            bottom.upper(),
            (0, PANEL_HEIGHT * 2 // 3, PANEL_WIDTH, PANEL_HEIGHT - 8),
            font=font,
            style=meme_style,
        )
    target = _save(base, output, "caption", slug=meme_style.name)
    return {
        "output": str(target),
        "template": "caption",
        "style": meme_style.name,
        "token_cost": "local-only",
        "image": resolved_image,
        "stock_images": bool(resolved_image and not image),
    }


def expanding_brain(
    labels: list[str],
    *,
    images: list[str] | None = None,
    use_stock_images: bool | None = None,
    style: str | None = None,
    output: str | None = None,
) -> dict[str, object]:
    if len(labels) != 4:
        raise ValueError("expanding_brain requires exactly 4 labels")
    Image, _, _ = _require_pillow()
    meme_style = resolve_meme_style(style)
    panel_h = PANEL_HEIGHT // 4
    width = PANEL_WIDTH
    colors = [
        meme_style.panel_neutral,
        meme_style.panel_left,
        meme_style.panel_right,
        meme_style.header_bg,
    ]
    panels = []
    image_paths = list(images or [])
    use_stock = _use_stock_images(use_stock_images)
    cache_dir = _meme_stock_cache_dir() if use_stock else None
    exclude_ids: set[str] = set()
    stock_paths: list[str | None] = []
    for index, label in enumerate(labels):
        path = image_paths[index] if index < len(image_paths) else None
        stock_path: str | None = None
        if not path and use_stock:
            stock_path = _fetch_stock_image_path(
                styled_stock_query(_stock_query_from_label(label), meme_style.name, for_meme=True),
                cache_dir=cache_dir,
                exclude_ids=exclude_ids,
            )
            path = stock_path
        stock_paths.append(stock_path)
        if path:
            panel = _apply_style_overlay(_fit_image(_load_image(path), width, panel_h), meme_style)
        else:
            panel = _text_panel(label, width, panel_h, colors[index], font_size=22, style=meme_style)
        panels.append(panel)
    canvas = Image.new("RGB", (width, panel_h * 4), "white")
    for index, panel in enumerate(panels):
        canvas.paste(panel, (0, index * panel_h))
        has_image = (image_paths[index] if index < len(image_paths) else None) or (
            stock_paths[index] if index < len(stock_paths) else None
        )
        if not has_image:
            continue
        _, ImageDraw, _ = _require_pillow()
        draw = ImageDraw.Draw(canvas)
        _draw_centered_text(
            draw,
            labels[index],
            (0, index * panel_h, width, (index + 1) * panel_h),
            font=_font(meme_style.body_font_size - 4),
            style=meme_style,
        )
    target = _save(canvas, output, "expanding-brain", slug=meme_style.name)
    return {
        "output": str(target),
        "template": "expanding_brain",
        "style": meme_style.name,
        "token_cost": "local-only",
        "stock_images": any(stock_paths),
    }


def two_button(
    *,
    dilemma: str,
    left: str,
    right: str,
    image: str | None = None,
    highlight: str | None = None,
    use_stock_images: bool | None = None,
    style: str | None = None,
    output: str | None = None,
) -> dict[str, object]:
    Image, ImageDraw, _ = _require_pillow()
    meme_style = resolve_meme_style(style)
    width = PANEL_WIDTH
    top_h = int(PANEL_HEIGHT * 0.55)
    button_h = PANEL_HEIGHT - top_h
    resolved_image = image
    if not resolved_image and _use_stock_images(use_stock_images):
        resolved_image = _fetch_stock_image_path(
            styled_stock_query(_stock_query_from_label(dilemma), meme_style.name, for_meme=True),
            cache_dir=_meme_stock_cache_dir(),
        )
    if resolved_image:
        top = _apply_style_overlay(_fit_image(_load_image(resolved_image), width, top_h), meme_style)
    else:
        top = _text_panel(dilemma, width, top_h, meme_style.panel_neutral, font_size=26, style=meme_style)
    canvas = Image.new("RGB", (width, PANEL_HEIGHT), meme_style.header_bg)
    canvas.paste(top, (0, 0))
    draw = ImageDraw.Draw(canvas)
    if resolved_image:
        _draw_centered_text(draw, dilemma, (0, 0, width, top_h), font=_font(28), style=meme_style)
    button_w = width // 2 - 24
    positions = ((12, top_h + 16), (width // 2 + 12, top_h + 16))
    labels = (left, right)
    font = _font(22)
    for side, (x, y), label in zip(("left", "right"), positions, labels):
        fill = meme_style.panel_left if side == "left" else meme_style.panel_right
        outline = meme_style.text_color if highlight == side else meme_style.outline_color
        width_px = 4 if highlight == side else 2
        draw.rounded_rectangle(
            (x, y, x + button_w, y + button_h - 32),
            radius=16,
            fill=fill,
            outline=outline,
            width=width_px,
        )
        _draw_centered_text(
            draw,
            label,
            (x + 8, y + 8, x + button_w - 8, y + button_h - 40),
            font=font,
            style=meme_style,
            outline_width=1,
        )
    target = _save(canvas, output, "two-button", slug=meme_style.name)
    return {
        "output": str(target),
        "template": "two_button",
        "style": meme_style.name,
        "token_cost": "local-only",
        "image": resolved_image,
        "stock_images": bool(resolved_image and not image),
    }


def vibe_coding_comparison(
    *,
    output: str | None = None,
    use_stock_images: bool | None = None,
    style: str | None = None,
) -> dict[str, object]:
    return comparison(
        left_title="VIBE CODING",
        right_title="SOFTWARE ENGINEERING",
        left_label=(
            "Ship fast\n"
            "Skip tests\n"
            "Prompt until it compiles\n"
            "\"We'll refactor later\""
        ),
        right_label=(
            "Design first\n"
            "Tests & review\n"
            "Observability\n"
            "Maintainable architecture"
        ),
        left_query="developer laptop messy desk coding fast",
        right_query="software engineer whiteboard architecture planning",
        use_stock_images=use_stock_images,
        style=style,
        output=output,
    )


def _extract_quoted(text: str) -> list[str]:
    return re.findall(r"""['"]([^'"]+)['"]""", text)


_MEME_SUBCOMMANDS = frozenset(
    {
        "comparison",
        "drake",
        "caption",
        "expanding-brain",
        "two-button",
        "vibe-coding",
        "styles",
        "list-styles",
    }
)


def _strip_meme_prefix(text: str) -> str:
    return re.sub(
        r"(?i)^(?:arka\s+)?(?:meme(?:[-_\s]templates?)?)\s+",
        "",
        text.strip(),
    ).strip()


def _parse_explicit_argv(text: str) -> list[str] | None:
    """Parse `meme vibe-coding` / `meme drake --reject X` style invocations."""
    raw = text.strip()
    if not raw:
        return None
    if not re.match(r"(?i)^(?:arka\s+)?meme\b", raw):
        return None
    remainder = _strip_meme_prefix(raw)
    if not remainder:
        return ["--help"]
    try:
        parts = shlex.split(remainder)
    except ValueError:
        parts = remainder.split()
    if not parts:
        return ["--help"]
    head = parts[0].lower()
    if head in _MEME_SUBCOMMANDS or head.startswith("-"):
        return parts
    return None


def nl_to_argv(text: str) -> list[str]:
    t = text.strip()
    if not t:
        return []

    explicit = _parse_explicit_argv(t)
    if explicit is not None:
        return explicit

    t, style = extract_style_from_text(t)

    if not re.search(r"(?i)\bmeme\b", t) and not re.search(
        r"(?i)\bvibe\s+coding\b.*\bsoftware\s+engineering\b", t
    ):
        return []

    style_args = ["--style", style] if style else []

    if re.search(r"(?i)\bvibe\s+coding\b", t) and re.search(
        r"(?i)\bsoftware\s+engineering\b", t
    ):
        return ["vibe-coding", *style_args]

    if re.search(r"(?i)\bvibe[- ]coding\b", t) and re.search(r"(?i)\bmeme\b", t):
        return ["vibe-coding", *style_args]

    if re.search(r"(?i)\bdrake\b", t):
        quotes = _extract_quoted(t)
        argv = ["drake", *style_args]
        if len(quotes) >= 2:
            argv.extend(["--reject", quotes[0], "--accept", quotes[1]])
        elif len(quotes) == 1:
            argv.extend(["--reject", quotes[0]])
        m = re.search(r"(?i)\breject(?:ing)?\s+(.+?)\s+(?:accept|prefer|choose)\s+(.+)$", t)
        if m and len(quotes) < 2:
            argv.extend(["--reject", m.group(1).strip(), "--accept", m.group(2).strip()])
        return argv if len(argv) > 1 else ["drake"]

    if re.search(r"(?i)\bexpanding\s+brain\b", t):
        quotes = _extract_quoted(t)
        if len(quotes) >= 4:
            argv = ["expanding-brain", *style_args]
            for label in quotes[:4]:
                argv.extend(["--label", label])
            return argv
        return ["expanding-brain"]

    if re.search(r"(?i)\btwo\s+button\b", t):
        quotes = _extract_quoted(t)
        if len(quotes) >= 3:
            return [
                "two-button",
                *style_args,
                "--dilemma",
                quotes[0],
                "--left",
                quotes[1],
                "--right",
                quotes[2],
            ]
        return []

    if re.search(r"(?i)\bcomparison\b", t):
        quotes = _extract_quoted(t)
        argv = ["comparison", *style_args]
        if len(quotes) >= 2:
            argv.extend(["--left-title", quotes[0], "--right-title", quotes[1]])
        return argv

    if re.search(r"(?i)\bcaption\b", t):
        quotes = _extract_quoted(t)
        m = re.search(r"(?i)([^\s'\"]+\.(?:png|jpe?g|gif|webp))\b", t)
        argv = ["caption", *style_args]
        if m:
            argv.extend(["--image", m.group(1)])
        if quotes:
            argv.extend(["--top", quotes[0]])
        if len(quotes) > 1:
            argv.extend(["--bottom", quotes[1]])
        return argv if len(argv) > 1 else []

    if re.search(r"(?i)\bmeme\b", t):
        return ["--help"]

    return []


def _print_result(result: dict[str, object], *, as_json: bool) -> None:
    if as_json:
        print(json.dumps(result, indent=2))
    else:
        extra = ""
        if result.get("stock_images"):
            extra = " (stock photos)"
        style_note = f" [{result['style']}]" if result.get("style") else ""
        print(f"Created meme ({result['template']}){style_note}{extra}: {result['output']}")


MEME_CLI_HEADS = frozenset(
    {"meme", "meme_template", "meme-template", "meme_templates"}
)


def is_meme_cli_argv(argv: list[str]) -> bool:
    """True for `arka meme …` style argv (first token is a meme subcommand alias)."""
    return bool(argv) and argv[0] in MEME_CLI_HEADS


def run_meme_cli(argv: list[str]) -> int:
    """Execute `arka meme …` from argv like ['meme', 'vibe-coding', '--output', 'out.png']."""
    return main(argv[1:])


MEME_TEMPLATE_NAMES = frozenset(
    {
        "comparison",
        "drake",
        "caption",
        "expanding-brain",
        "expanding_brain",
        "two-button",
        "two_button",
        "vibe-coding",
        "vibe_coding",
    }
)


def list_meme_templates() -> list[dict[str, str]]:
    return [
        {"name": "comparison", "description": "Side-by-side panels with titles"},
        {"name": "drake", "description": "Reject (top) vs accept (bottom)"},
        {"name": "caption", "description": "Classic top/bottom text meme"},
        {"name": "expanding-brain", "description": "Four escalating panels"},
        {"name": "two-button", "description": "Dilemma with two red buttons"},
        {"name": "vibe-coding", "description": "Built-in vibe coding vs software engineering"},
    ]


def meme_result(
    template: str,
    *,
    style: str | None = None,
    output: str | None = None,
    use_stock_images: bool | None = None,
    left: str | None = None,
    right: str | None = None,
    left_title: str = "LEFT",
    right_title: str = "RIGHT",
    left_label: str | None = None,
    right_label: str | None = None,
    left_query: str | None = None,
    right_query: str | None = None,
    reject: str | None = None,
    accept: str | None = None,
    image: str | None = None,
    top: str = "",
    bottom: str = "",
    label: str | None = None,
    stock_query: str | None = None,
    labels: list[str] | None = None,
    images: list[str] | None = None,
    dilemma: str | None = None,
    button_left: str | None = None,
    button_right: str | None = None,
    highlight: str | None = None,
) -> dict[str, object]:
    """High-level API for MCP and agent integrations."""
    key = (template or "").strip().lower().replace("_", "-")
    stock = use_stock_images
    if key == "comparison":
        return comparison(
            left=left,
            right=right,
            left_title=left_title,
            right_title=right_title,
            left_label=left_label,
            right_label=right_label,
            left_query=left_query,
            right_query=right_query,
            use_stock_images=stock,
            style=style,
            output=output,
        )
    if key == "drake":
        if not reject or not accept:
            raise ValueError("drake template requires reject and accept")
        return drake(
            reject=reject,
            accept=accept,
            image=image,
            use_stock_images=stock,
            style=style,
            output=output,
        )
    if key == "caption":
        return caption(
            image=image,
            top=top,
            bottom=bottom,
            label=label,
            stock_query=stock_query,
            use_stock_images=stock,
            style=style,
            output=output,
        )
    if key == "expanding-brain":
        panel_labels = labels or []
        if len(panel_labels) != 4:
            raise ValueError("expanding-brain requires exactly 4 labels")
        return expanding_brain(
            panel_labels,
            images=images,
            use_stock_images=stock,
            style=style,
            output=output,
        )
    if key == "two-button":
        return two_button(
            dilemma=dilemma or "Pick one:",
            left=button_left or "Option A",
            right=button_right or "Option B",
            image=image,
            highlight=highlight,
            use_stock_images=stock,
            style=style,
            output=output,
        )
    if key == "vibe-coding":
        return vibe_coding_comparison(
            use_stock_images=stock,
            style=style,
            output=output,
        )
    raise ValueError(
        f"unknown meme template {template!r}; choose from "
        + ", ".join(t["name"] for t in list_meme_templates())
    )


def _add_style_args(parser: argparse.ArgumentParser) -> None:
    parser.add_argument(
        "--style",
        choices=sorted(list_meme_styles()),
        default=None,
        help="Visual style preset (default: MEME_STYLE or classic)",
    )


def _add_stock_args(parser: argparse.ArgumentParser) -> None:
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--use-stock-images",
        action="store_true",
        help="Fetch relevant stock photos for panels (default: MEME_USE_STOCK_PHOTOS=1)",
    )
    group.add_argument(
        "--no-stock-images",
        "--text-only",
        action="store_true",
        help="Use text-only panels; skip stock photo lookup",
    )


def _stock_flag_from_args(args: argparse.Namespace) -> bool | None:
    if getattr(args, "no_stock_images", False):
        return False
    if getattr(args, "use_stock_images", None):
        return True
    return None


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="arka meme")
    sub = p.add_subparsers(dest="command", required=True)

    comp = sub.add_parser("comparison", help="Side-by-side comparison panels")
    comp.add_argument("--left")
    comp.add_argument("--right")
    comp.add_argument("--left-title", default="LEFT")
    comp.add_argument("--right-title", default="RIGHT")
    comp.add_argument("--left-label")
    comp.add_argument("--right-label")
    comp.add_argument("--left-query", help="Stock photo search query for left panel")
    comp.add_argument("--right-query", help="Stock photo search query for right panel")
    comp.add_argument("--output")
    comp.add_argument("--json", action="store_true")
    _add_stock_args(comp)
    _add_style_args(comp)

    drk = sub.add_parser("drake", help="Drake hotline bling reject/accept")
    drk.add_argument("--reject", required=True)
    drk.add_argument("--accept", required=True)
    drk.add_argument("--image", help="Optional Drake template image")
    drk.add_argument("--output")
    drk.add_argument("--json", action="store_true")
    _add_stock_args(drk)
    _add_style_args(drk)

    cap = sub.add_parser("caption", help="Top and bottom caption meme")
    cap.add_argument("--image")
    cap.add_argument("--label", help="Solid panel when no image")
    cap.add_argument("--query", help="Stock photo search query when no --image")
    cap.add_argument("--top", default="")
    cap.add_argument("--bottom", default="")
    cap.add_argument("--output")
    cap.add_argument("--json", action="store_true")
    _add_stock_args(cap)
    _add_style_args(cap)

    brain = sub.add_parser("expanding-brain", help="Four-panel escalating brain meme")
    brain.add_argument("--label", action="append", required=True)
    brain.add_argument("--image", action="append")
    brain.add_argument("--output")
    brain.add_argument("--json", action="store_true")
    _add_stock_args(brain)
    _add_style_args(brain)

    buttons = sub.add_parser("two-button", help="Sweating over two choices")
    buttons.add_argument("--dilemma", required=True)
    buttons.add_argument("--left", required=True)
    buttons.add_argument("--right", required=True)
    buttons.add_argument("--image")
    buttons.add_argument("--highlight", choices=("left", "right"))
    buttons.add_argument("--output")
    buttons.add_argument("--json", action="store_true")
    _add_stock_args(buttons)
    _add_style_args(buttons)

    preset = sub.add_parser(
        "vibe-coding",
        help="Preset: vibe coding vs software engineering",
    )
    preset.add_argument("--output")
    preset.add_argument("--json", action="store_true")
    _add_stock_args(preset)
    _add_style_args(preset)

    styles = sub.add_parser("styles", aliases=["list-styles"], help="List meme style presets")
    styles.add_argument("--json", action="store_true")

    args = p.parse_args(argv)
    if args.command in {"styles", "list-styles"}:
        if args.json:
            print(json.dumps({name: MEME_STYLES[name].label for name in list_meme_styles()}, indent=2))
        else:
            print(format_style_catalog(kind="meme"))
        return 0

    stock_flag = _stock_flag_from_args(args)
    style = getattr(args, "style", None)
    try:
        if args.command == "comparison":
            result = comparison(
                left=args.left,
                right=args.right,
                left_title=args.left_title,
                right_title=args.right_title,
                left_label=args.left_label,
                right_label=args.right_label,
                left_query=args.left_query,
                right_query=args.right_query,
                use_stock_images=stock_flag,
                style=style,
                output=args.output,
            )
        elif args.command == "drake":
            result = drake(
                reject=args.reject,
                accept=args.accept,
                image=args.image,
                use_stock_images=stock_flag,
                style=style,
                output=args.output,
            )
        elif args.command == "caption":
            result = caption(
                image=args.image,
                top=args.top,
                bottom=args.bottom,
                label=args.label,
                stock_query=args.query,
                use_stock_images=stock_flag,
                style=style,
                output=args.output,
            )
        elif args.command == "expanding-brain":
            result = expanding_brain(
                args.label,
                images=args.image,
                use_stock_images=stock_flag,
                style=style,
                output=args.output,
            )
        elif args.command == "two-button":
            result = two_button(
                dilemma=args.dilemma,
                left=args.left,
                right=args.right,
                image=args.image,
                highlight=args.highlight,
                use_stock_images=stock_flag,
                style=style,
                output=args.output,
            )
        else:
            result = vibe_coding_comparison(
                output=args.output,
                use_stock_images=stock_flag,
                style=style,
            )
    except (OSError, ValueError, RuntimeError) as exc:
        p.error(str(exc))
        return 2

    _print_result(result, as_json=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
