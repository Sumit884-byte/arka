"""Adaptive infographic compositor — layout picks itself from item count."""

from __future__ import annotations

import argparse
import json
import math
import os
import re
import shlex
import sys
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path

LAYOUTS = frozenset({"auto", "row2", "row3", "grid4", "grid6", "grid9", "radial"})
INFOGRAPHIC_CLI_HEADS = frozenset({"infographic", "infographic-maker", "listicle"})
CANVAS_WIDTH = 1080

# Cycle simple pictographs when no custom image is supplied.
_ITEM_GLYPHS = (
    "●", "◆", "▲", "■", "★", "⬡", "✦", "⬢", "◉", "◎", "◈", "◐",
)


@dataclass(frozen=True)
class InfographicStyle:
    name: str
    label: str
    bg: tuple[int, int, int]
    title_color: tuple[int, int, int]
    title_accent: tuple[int, int, int]
    cell_bg: tuple[int, int, int]
    cell_border: tuple[int, int, int]
    label_color: tuple[int, int, int]
    arrow_color: tuple[int, int, int]
    center_bg: tuple[int, int, int]
    doodle_borders: bool = False


INFOGRAPHIC_STYLES: dict[str, InfographicStyle] = {
    "clean": InfographicStyle(
        name="clean",
        label="Clean social (default)",
        bg=(248, 250, 252),
        title_color=(15, 23, 42),
        title_accent=(220, 38, 38),
        cell_bg=(255, 255, 255),
        cell_border=(203, 213, 225),
        label_color=(30, 41, 59),
        arrow_color=(59, 130, 246),
        center_bg=(255, 255, 255),
    ),
    "doodle": InfographicStyle(
        name="doodle",
        label="Hand-drawn doodle",
        bg=(255, 253, 245),
        title_color=(28, 25, 23),
        title_accent=(234, 88, 12),
        cell_bg=(255, 255, 255),
        cell_border=(87, 83, 78),
        label_color=(41, 37, 36),
        arrow_color=(59, 130, 246),
        center_bg=(255, 255, 255),
        doodle_borders=True,
    ),
    "dark": InfographicStyle(
        name="dark",
        label="Dark mode",
        bg=(15, 23, 42),
        title_color=(248, 250, 252),
        title_accent=(248, 113, 113),
        cell_bg=(30, 41, 59),
        cell_border=(51, 65, 85),
        label_color=(226, 232, 240),
        arrow_color=(56, 189, 248),
        center_bg=(30, 41, 59),
    ),
    "meme": InfographicStyle(
        name="meme",
        label="Bold meme header",
        bg=(255, 255, 255),
        title_color=(0, 0, 0),
        title_accent=(220, 38, 38),
        cell_bg=(245, 245, 245),
        cell_border=(0, 0, 0),
        label_color=(0, 0, 0),
        arrow_color=(0, 0, 0),
        center_bg=(255, 255, 255),
    ),
}


def _require_pillow():
    try:
        from PIL import Image, ImageDraw, ImageFont

        return Image, ImageDraw, ImageFont
    except ImportError as exc:
        raise RuntimeError("infographic requires Pillow: pip install Pillow") from exc


def _font(size: int, *, bold: bool = True):
    _, _, ImageFont = _require_pillow()
    candidates = (
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Impact.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
        "C:\\Windows\\Fonts\\impact.ttf",
    )
    if not bold:
        candidates = (
            "/System/Library/Fonts/Supplemental/Arial.ttf",
            "/usr/share/fonts/truetype/dejavu/DejaVuSans.ttf",
            *candidates,
        )
    for path in candidates:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    return ImageFont.load_default()


def _wrap_text(text: str, font, max_width: int, draw) -> list[str]:
    lines: list[str] = []
    for paragraph in (text or "").splitlines() or [""]:
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


def _draw_centered(
    draw,
    text: str,
    box: tuple[int, int, int, int],
    *,
    font,
    fill: tuple[int, int, int],
) -> None:
    x0, y0, x1, y1 = box
    max_width = x1 - x0 - 8
    lines = _wrap_text(text, font, max_width, draw)
    line_height = draw.textbbox((0, 0), "Ay", font=font)[3] + 6
    total = line_height * len(lines)
    y = y0 + max(0, (y1 - y0 - total) // 2)
    for line in lines:
        box = draw.textbbox((0, 0), line, font=font)
        w = box[2] - box[0]
        x = x0 + (x1 - x0 - w) // 2
        draw.text((x, y), line, font=font, fill=fill)
        y += line_height


def _rounded_rect(draw, box, radius: int, **kwargs) -> None:
    if hasattr(draw, "rounded_rectangle"):
        draw.rounded_rectangle(box, radius=radius, **kwargs)
    else:
        draw.rectangle(box, **kwargs)


def _doodle_rect(draw, box, color: tuple[int, int, int], width: int = 3) -> None:
    x0, y0, x1, y1 = box
    jitter = 4
    points = [
        (x0 + jitter, y0),
        (x1 - jitter, y0 + 2),
        (x1, y1 - jitter),
        (x0 + 2, y1),
        (x0 + jitter, y0),
    ]
    draw.line(points, fill=color, width=width)


def _cell_border(draw, box, style: InfographicStyle) -> None:
    if style.doodle_borders:
        _doodle_rect(draw, box, style.cell_border)
    else:
        _rounded_rect(draw, box, 16, outline=style.cell_border, width=2, fill=style.cell_bg)


def resolve_style(name: str | None) -> InfographicStyle:
    key = (name or os.environ.get("INFOGRAPHIC_STYLE", "") or "clean").strip().lower()
    return INFOGRAPHIC_STYLES.get(key, INFOGRAPHIC_STYLES["clean"])


def list_infographic_styles() -> list[str]:
    return list(INFOGRAPHIC_STYLES)


def choose_layout(count: int, explicit: str | None = None) -> str:
    if explicit and explicit != "auto":
        if explicit not in LAYOUTS - {"auto"}:
            raise ValueError(f"unknown layout {explicit!r}; choose from {sorted(LAYOUTS)}")
        return explicit
    if count <= 2:
        return "row2"
    if count == 3:
        return "row3"
    if count == 4:
        return "grid4"
    if count <= 6:
        return "grid6"
    if count <= 9:
        return "grid9"
    return "radial"


def _split_title(title: str) -> tuple[str, str]:
    """Optional accent on last word group (HEADACHES-style)."""
    words = (title or "Infographic").strip().split()
    if len(words) <= 1:
        return title.strip(), ""
    if len(words) == 2:
        return words[0], words[1]
    mid = max(1, len(words) // 2)
    return " ".join(words[:mid]), " ".join(words[mid:])


def _default_output(title: str, layout: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", title.lower())[:36].strip("-") or "infographic"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    env_dir = os.environ.get("IMAGE_OUTPUT_DIR", "").strip()
    out_dir = Path(env_dir).expanduser() if env_dir else Path.home() / "Pictures" / "arka-generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"infographic-{layout}-{slug}-{ts}.png"


def _draw_title(draw, title: str, width: int, y: int, style: InfographicStyle) -> int:
    line1, line2 = _split_title(title)
    title_font = _font(52 if not line2 else 44)
    accent_font = _font(56 if line2 else 52)
    if line2:
        _draw_centered(
            draw,
            line1.upper(),
            (40, y, width - 40, y + 70),
            font=title_font,
            fill=style.title_color,
        )
        _draw_centered(
            draw,
            line2.upper(),
            (40, y + 64, width - 40, y + 140),
            font=accent_font,
            fill=style.title_accent,
        )
        return y + 150
    _draw_centered(
        draw,
        line1.upper(),
        (40, y, width - 40, y + 100),
        font=accent_font,
        fill=style.title_color,
    )
    return y + 120


def _draw_glyph(draw, center: tuple[int, int], index: int, style: InfographicStyle) -> None:
    cx, cy = center
    glyph = _ITEM_GLYPHS[index % len(_ITEM_GLYPHS)]
    font = _font(72)
    box = draw.textbbox((0, 0), glyph, font=font)
    w, h = box[2] - box[0], box[3] - box[1]
    draw.text((cx - w // 2, cy - h // 2), glyph, font=font, fill=style.title_accent)


def _render_grid(
    title: str,
    items: list[str],
    *,
    cols: int,
    rows: int,
    style: InfographicStyle,
) -> object:
    Image, ImageDraw, _ = _require_pillow()
    margin = 48
    title_h = 150
    cell_gap = 20
    usable_w = CANVAS_WIDTH - margin * 2
    cell_w = (usable_w - cell_gap * (cols - 1)) // cols
    cell_h = cell_w
    height = margin + title_h + rows * cell_h + (rows - 1) * cell_gap + margin + 40
    canvas = Image.new("RGB", (CANVAS_WIDTH, height), style.bg)
    draw = ImageDraw.Draw(canvas)
    _draw_title(draw, title, CANVAS_WIDTH, margin, style)
    label_font = _font(28)
    top = margin + title_h
    for index, label in enumerate(items):
        if index >= cols * rows:
            break
        row, col = divmod(index, cols)
        x0 = margin + col * (cell_w + cell_gap)
        y0 = top + row * (cell_h + cell_gap)
        box = (x0, y0, x0 + cell_w, y0 + cell_h)
        _cell_border(draw, box, style)
        icon_box = (x0 + 16, y0 + 16, x0 + cell_w - 16, y0 + cell_h - 56)
        _draw_glyph(draw, ((icon_box[0] + icon_box[2]) // 2, (icon_box[1] + icon_box[3]) // 2), index, style)
        _draw_centered(
            draw,
            label,
            (x0 + 8, y0 + cell_h - 52, x0 + cell_w - 8, y0 + cell_h - 8),
            font=label_font,
            fill=style.label_color,
        )
    return canvas


def _render_radial(title: str, items: list[str], style: InfographicStyle) -> object:
    Image, ImageDraw, _ = _require_pillow()
    height = max(1400, 980 + len(items) * 20)
    canvas = Image.new("RGB", (CANVAS_WIDTH, height), style.bg)
    draw = ImageDraw.Draw(canvas)
    cx, cy = CANVAS_WIDTH // 2, height // 2
    center_w, center_h = 420, 160
    center_box = (cx - center_w // 2, cy - center_h // 2, cx + center_w // 2, cy + center_h // 2)
    _cell_border(draw, center_box, style)
    title_font = _font(30)
    _draw_centered(
        draw,
        title.upper(),
        (center_box[0] + 12, center_box[1] + 12, center_box[2] - 12, center_box[3] - 12),
        font=title_font,
        fill=style.title_color,
    )
    count = len(items)
    radius_x = min(460, CANVAS_WIDTH // 2 - 120)
    radius_y = min(520, height // 2 - 120)
    label_font = _font(24)
    node_w, node_h = 200, 88
    for index, label in enumerate(items):
        angle = -math.pi / 2 + (2 * math.pi * index / count)
        nx = int(cx + radius_x * math.cos(angle))
        ny = int(cy + radius_y * math.sin(angle))
        draw.line((cx, cy, nx, ny), fill=style.arrow_color, width=3)
        box = (nx - node_w // 2, ny - node_h // 2, nx + node_w // 2, ny + node_h // 2)
        _cell_border(draw, box, style)
        _draw_glyph(draw, (nx, ny - 18), index, style)
        _draw_centered(
            draw,
            label,
            (box[0] + 6, ny + 4, box[2] - 6, box[3] - 6),
            font=label_font,
            fill=style.label_color,
        )
    return canvas


def compose(
    title: str,
    items: list[str],
    *,
    layout: str | None = "auto",
    style: str | None = None,
    output: str | Path | None = None,
) -> dict[str, object]:
    cleaned = [re.sub(r"\s+", " ", x).strip() for x in items if (x or "").strip()]
    if not cleaned:
        raise ValueError("infographic needs at least one item")
    if not (title or "").strip():
        raise ValueError("infographic needs a title")
    style_obj = resolve_style(style)
    layout_name = choose_layout(len(cleaned), layout)
    if layout_name == "row2":
        canvas = _render_grid(title, cleaned, cols=min(2, len(cleaned)), rows=1, style=style_obj)
    elif layout_name == "row3":
        canvas = _render_grid(title, cleaned, cols=3, rows=1, style=style_obj)
    elif layout_name == "grid4":
        canvas = _render_grid(title, cleaned, cols=2, rows=2, style=style_obj)
    elif layout_name == "grid6":
        rows = 2 if len(cleaned) <= 6 else 3
        cols = math.ceil(len(cleaned) / rows)
        canvas = _render_grid(title, cleaned, cols=cols, rows=rows, style=style_obj)
    elif layout_name == "grid9":
        rows = math.ceil(len(cleaned) / 3)
        canvas = _render_grid(title, cleaned, cols=3, rows=rows, style=style_obj)
    else:
        canvas = _render_radial(title, cleaned, style_obj)
    target = Path(output).expanduser() if output else _default_output(title, layout_name)
    target.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(target)
    return {
        "output": str(target),
        "layout": layout_name,
        "style": style_obj.name,
        "items": len(cleaned),
        "token_cost": "local-only",
    }


def _parse_items(raw: str | None, repeated: list[str] | None) -> list[str]:
    if repeated:
        return [x.strip() for x in repeated if x.strip()]
    if not raw:
        return []
    if "\n" in raw:
        return [line.strip() for line in raw.splitlines() if line.strip()]
    return [part.strip() for part in raw.split(",") if part.strip()]


def nl_to_argv(text: str) -> list[str]:
    t = text.strip()
    if not t:
        return []
    if not re.search(r"(?i)\b(?:infographic|listicle|mind\s*map)\b", t):
        return []
    argv: list[str] = []
    style_match = re.search(
        r"(?i)\b(clean|doodle|dark|meme)\s+style\s+(?:infographic|listicle)\b",
        t,
    )
    if style_match:
        argv.extend(["--style", style_match.group(1).lower()])
    quoted = re.findall(r"""['"]([^'"]+)['"]""", t)
    if quoted:
        argv.extend(["--title", quoted[0]])
        for item in quoted[1:]:
            argv.extend(["--item", item])
    title_match = re.search(
        r"(?i)(?:infographic|listicle|mind\s*map)\s+"
        r"(?:about|on|for|titled|called)\s+"
        r"['\"]?([^'\"]+?)['\"]?"
        r"(?:\s+(?:with\s+)?items?\s*:|$)",
        t,
    )
    if title_match and not any(a == "--title" for a in argv):
        argv.extend(["--title", title_match.group(1).strip()])
    elif not any(a == "--title" for a in argv):
        bare = re.search(r"(?i)(?:title|heading)\s+['\"]([^'\"]+)['\"]", t)
        if bare:
            argv.extend(["--title", bare.group(1).strip()])
    list_match = re.search(r"(?i)\bitems?\s*:\s*(.+)$", t)
    if list_match:
        for part in re.split(r",|\band\b", list_match.group(1)):
            part = part.strip(" .")
            if part:
                argv.extend(["--item", part])
    return argv


def is_infographic_cli_argv(argv: list[str]) -> bool:
    return bool(argv) and argv[0] in INFOGRAPHIC_CLI_HEADS


def run_infographic_cli(argv: list[str]) -> int:
    return main(argv[1:])


def infographic_result(
    title: str,
    items: list[str] | str | None = None,
    *,
    layout: str | None = "auto",
    style: str | None = None,
    output: str | Path | None = None,
) -> dict[str, object]:
    """High-level API for MCP and agent integrations."""
    if isinstance(items, str):
        parsed = _parse_items(items, None)
    elif items is None:
        parsed = []
    else:
        parsed = list(items)
    return compose(
        title,
        parsed,
        layout=layout,
        style=style,
        output=output,
    )


def main(argv: list[str] | None = None) -> int:
    raw = list(argv if argv is not None else sys.argv[1:])
    if raw and raw[0] not in {"create", "layouts", "styles", "-h", "--help"}:
        raw = ["create", *raw]
    parser = argparse.ArgumentParser(prog="arka infographic")
    sub = parser.add_subparsers(dest="command")

    gen = sub.add_parser("create", help="Compose an adaptive infographic PNG")
    gen.add_argument("--title", required=True, help="Main headline")
    gen.add_argument("--item", action="append", dest="item_list", help="Item label (repeat)")
    gen.add_argument("--items", dest="items_text", help="Comma- or newline-separated item labels")
    gen.add_argument(
        "--layout",
        choices=sorted(LAYOUTS),
        default="auto",
        help="auto picks row/grid/radial from item count",
    )
    gen.add_argument("--style", choices=list_infographic_styles(), default=None)
    gen.add_argument("-o", "--output")
    gen.add_argument("--json", action="store_true")
    gen.set_defaults(func="create")

    sub.add_parser("layouts", help="Show layout selection rules").set_defaults(func="layouts")
    styles_p = sub.add_parser("styles", help="List visual styles")
    styles_p.add_argument("--json", action="store_true")
    styles_p.set_defaults(func="styles")

    args = parser.parse_args(raw)
    if not args.command:
        parser.print_help()
        return 0

    if args.func == "layouts":
        print(
            "Layout auto-selection:\n"
            "  1-2 items  → row2\n"
            "  3 items    → row3\n"
            "  4 items    → grid4 (2×2)\n"
            "  5-6 items  → grid6\n"
            "  7-9 items  → grid9 (3×3)\n"
            "  10+ items  → radial hub"
        )
        return 0

    if args.func == "styles":
        if args.json:
            print(json.dumps({k: v.label for k, v in INFOGRAPHIC_STYLES.items()}, indent=2))
        else:
            for name, st in INFOGRAPHIC_STYLES.items():
                print(f"  {name:8} — {st.label}")
        return 0

    items = _parse_items(getattr(args, "items_text", None), getattr(args, "item_list", None))
    try:
        result = compose(
            args.title,
            items,
            layout=args.layout,
            style=args.style,
            output=args.output,
        )
    except (OSError, ValueError, RuntimeError) as exc:
        parser.error(str(exc))
        return 2

    if args.json:
        print(json.dumps(result, indent=2))
    else:
        print(
            f"Created infographic ({result['layout']}, {result['items']} items, "
            f"{result['style']}): {result['output']}"
        )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
