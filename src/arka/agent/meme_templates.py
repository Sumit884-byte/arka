"""Reusable meme layouts — local Pillow compositor, no AI required."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
from datetime import datetime
from pathlib import Path

PANEL_WIDTH = 800
PANEL_HEIGHT = 600
HEADER_HEIGHT = 48
MEME_TEXT_COLOR = (255, 255, 255)
MEME_OUTLINE = (0, 0, 0)


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
    fill=MEME_TEXT_COLOR,
    outline=MEME_OUTLINE,
    outline_width: int = 2,
) -> None:
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
) -> object:
    Image, ImageDraw, _ = _require_pillow()
    panel = Image.new("RGB", (width, height), bg)
    draw = ImageDraw.Draw(panel)
    font = _font(font_size)
    _draw_centered_text(
        draw,
        text,
        (12, 12, width - 12, height - 12),
        font=font,
        outline_width=1,
    )
    return panel


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


def _resolve_panel(
    path: str | None,
    label: str | None,
    *,
    width: int,
    height: int,
    bg: tuple[int, int, int],
) -> object:
    if path:
        return _fit_image(_load_image(path), width, height)
    if label:
        return _text_panel(label, width, height, bg)
    raise ValueError("each panel needs an image path or a text label")


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
    output: str | None = None,
) -> dict[str, object]:
    Image, ImageDraw, _ = _require_pillow()
    left_panel = _resolve_panel(
        left,
        left_label or (None if left else "LEFT"),
        width=PANEL_WIDTH,
        height=PANEL_HEIGHT,
        bg=(45, 55, 72),
    )
    right_panel = _resolve_panel(
        right,
        right_label or (None if right else "RIGHT"),
        width=PANEL_WIDTH,
        height=PANEL_HEIGHT,
        bg=(26, 54, 93),
    )
    width = max(left_panel.width, right_panel.width)
    height = max(left_panel.height, right_panel.height) + HEADER_HEIGHT
    canvas = Image.new("RGB", (width * 2, height), "white")
    draw = ImageDraw.Draw(canvas)
    font = _font(20)
    for index, (panel, title) in enumerate(
        zip((left_panel, right_panel), (left_title, right_title))
    ):
        x_offset = index * width
        canvas.paste(panel, (x_offset, HEADER_HEIGHT))
        draw.rectangle((x_offset, 0, x_offset + width, HEADER_HEIGHT), fill=(10, 22, 40))
        draw.text((x_offset + 18, 14), title, fill="white", font=font)
    draw.line((width, 0, width, height), fill=(20, 30, 45), width=3)
    target = _save(canvas, output, "comparison")
    return {
        "output": str(target),
        "template": "comparison",
        "token_cost": "local-only",
        "left": left,
        "right": right,
    }


def drake(
    *,
    reject: str,
    accept: str,
    image: str | None = None,
    output: str | None = None,
) -> dict[str, object]:
    Image, ImageDraw, _ = _require_pillow()
    width, half = PANEL_WIDTH, PANEL_HEIGHT // 2
    if image:
        base = _fit_image(_load_image(image), width, PANEL_HEIGHT)
        top = base.crop((0, 0, width, half))
        bottom = base.crop((0, half, width, PANEL_HEIGHT))
    else:
        top = _text_panel(reject, width, half, (120, 45, 45), font_size=24)
        bottom = _text_panel(accept, width, half, (34, 84, 61), font_size=24)
    canvas = Image.new("RGB", (width, PANEL_HEIGHT), "white")
    canvas.paste(top, (0, 0))
    canvas.paste(bottom, (0, half))
    draw = ImageDraw.Draw(canvas)
    draw.line((0, half, width, half), fill=(255, 255, 255), width=4)
    font = _font(32)
    if image:
        _draw_centered_text(draw, reject, (0, 0, width, half), font=font)
        _draw_centered_text(draw, accept, (0, half, width, PANEL_HEIGHT), font=font)
    target = _save(canvas, output, "drake")
    return {"output": str(target), "template": "drake", "token_cost": "local-only"}


def caption(
    *,
    image: str | None = None,
    top: str = "",
    bottom: str = "",
    label: str | None = None,
    output: str | None = None,
) -> dict[str, object]:
    Image, ImageDraw, _ = _require_pillow()
    if image:
        base = _fit_image(_load_image(image), PANEL_WIDTH, PANEL_HEIGHT)
    elif label:
        base = _text_panel(label, PANEL_WIDTH, PANEL_HEIGHT, (55, 65, 81))
    else:
        raise ValueError("caption needs --image or --label")
    draw = ImageDraw.Draw(base)
    font = _font(36)
    if top:
        _draw_centered_text(draw, top.upper(), (0, 8, PANEL_WIDTH, PANEL_HEIGHT // 3), font=font)
    if bottom:
        _draw_centered_text(
            draw,
            bottom.upper(),
            (0, PANEL_HEIGHT * 2 // 3, PANEL_WIDTH, PANEL_HEIGHT - 8),
            font=font,
        )
    target = _save(base, output, "caption")
    return {"output": str(target), "template": "caption", "token_cost": "local-only"}


def expanding_brain(
    labels: list[str],
    *,
    images: list[str] | None = None,
    output: str | None = None,
) -> dict[str, object]:
    if len(labels) != 4:
        raise ValueError("expanding_brain requires exactly 4 labels")
    Image, _, _ = _require_pillow()
    panel_h = PANEL_HEIGHT // 4
    width = PANEL_WIDTH
    colors = [(60, 60, 70), (70, 90, 120), (90, 120, 160), (120, 180, 220)]
    panels = []
    image_paths = images or []
    for index, label in enumerate(labels):
        path = image_paths[index] if index < len(image_paths) else None
        if path:
            panel = _fit_image(_load_image(path), width, panel_h)
        else:
            panel = _text_panel(label, width, panel_h, colors[index], font_size=22)
        panels.append(panel)
    canvas = Image.new("RGB", (width, panel_h * 4), "white")
    for index, panel in enumerate(panels):
        canvas.paste(panel, (0, index * panel_h))
        if not (image_paths[index] if index < len(image_paths) else None):
            continue
        _, ImageDraw, _ = _require_pillow()
        draw = ImageDraw.Draw(canvas)
        _draw_centered_text(
            draw,
            label,
            (0, index * panel_h, width, (index + 1) * panel_h),
            font=_font(24),
        )
    target = _save(canvas, output, "expanding-brain")
    return {"output": str(target), "template": "expanding_brain", "token_cost": "local-only"}


def two_button(
    *,
    dilemma: str,
    left: str,
    right: str,
    image: str | None = None,
    highlight: str | None = None,
    output: str | None = None,
) -> dict[str, object]:
    Image, ImageDraw, _ = _require_pillow()
    width = PANEL_WIDTH
    top_h = int(PANEL_HEIGHT * 0.55)
    button_h = PANEL_HEIGHT - top_h
    if image:
        top = _fit_image(_load_image(image), width, top_h)
    else:
        top = _text_panel(dilemma, width, top_h, (40, 44, 52), font_size=26)
    canvas = Image.new("RGB", (width, PANEL_HEIGHT), (30, 30, 30))
    canvas.paste(top, (0, 0))
    draw = ImageDraw.Draw(canvas)
    if image:
        _draw_centered_text(draw, dilemma, (0, 0, width, top_h), font=_font(28))
    button_w = width // 2 - 24
    positions = ((12, top_h + 16), (width // 2 + 12, top_h + 16))
    labels = (left, right)
    font = _font(22)
    for side, (x, y), label in zip(("left", "right"), positions, labels):
        fill = (180, 40, 40)
        outline = (255, 220, 80) if highlight == side else (120, 20, 20)
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
            outline_width=1,
        )
    target = _save(canvas, output, "two-button")
    return {"output": str(target), "template": "two_button", "token_cost": "local-only"}


def vibe_coding_comparison(*, output: str | None = None) -> dict[str, object]:
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

    if not re.search(r"(?i)\bmeme\b", t) and not re.search(
        r"(?i)\bvibe\s+coding\b.*\bsoftware\s+engineering\b", t
    ):
        return []

    if re.search(r"(?i)\bvibe\s+coding\b", t) and re.search(
        r"(?i)\bsoftware\s+engineering\b", t
    ):
        return ["vibe-coding"]

    if re.search(r"(?i)\bvibe[- ]coding\b", t) and re.search(r"(?i)\bmeme\b", t):
        return ["vibe-coding"]

    if re.search(r"(?i)\bdrake\b", t):
        quotes = _extract_quoted(t)
        argv = ["drake"]
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
            argv = ["expanding-brain"]
            for label in quotes[:4]:
                argv.extend(["--label", label])
            return argv
        return ["expanding-brain"]

    if re.search(r"(?i)\btwo\s+button\b", t):
        quotes = _extract_quoted(t)
        if len(quotes) >= 3:
            return [
                "two-button",
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
        argv = ["comparison"]
        if len(quotes) >= 2:
            argv.extend(["--left-title", quotes[0], "--right-title", quotes[1]])
        return argv

    if re.search(r"(?i)\bcaption\b", t):
        quotes = _extract_quoted(t)
        m = re.search(r"(?i)([^\s'\"]+\.(?:png|jpe?g|gif|webp))\b", t)
        argv = ["caption"]
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
        print(f"Created meme ({result['template']}): {result['output']}")


MEME_CLI_HEADS = frozenset(
    {"meme", "meme_template", "meme-template", "meme_templates"}
)


def is_meme_cli_argv(argv: list[str]) -> bool:
    """True for `arka meme …` style argv (first token is a meme subcommand alias)."""
    return bool(argv) and argv[0] in MEME_CLI_HEADS


def run_meme_cli(argv: list[str]) -> int:
    """Execute `arka meme …` from argv like ['meme', 'vibe-coding', '--output', 'out.png']."""
    return main(argv[1:])


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
    comp.add_argument("--output")
    comp.add_argument("--json", action="store_true")

    drk = sub.add_parser("drake", help="Drake hotline bling reject/accept")
    drk.add_argument("--reject", required=True)
    drk.add_argument("--accept", required=True)
    drk.add_argument("--image", help="Optional Drake template image")
    drk.add_argument("--output")
    drk.add_argument("--json", action="store_true")

    cap = sub.add_parser("caption", help="Top and bottom caption meme")
    cap.add_argument("--image")
    cap.add_argument("--label", help="Solid panel when no image")
    cap.add_argument("--top", default="")
    cap.add_argument("--bottom", default="")
    cap.add_argument("--output")
    cap.add_argument("--json", action="store_true")

    brain = sub.add_parser("expanding-brain", help="Four-panel escalating brain meme")
    brain.add_argument("--label", action="append", required=True)
    brain.add_argument("--image", action="append")
    brain.add_argument("--output")
    brain.add_argument("--json", action="store_true")

    buttons = sub.add_parser("two-button", help="Sweating over two choices")
    buttons.add_argument("--dilemma", required=True)
    buttons.add_argument("--left", required=True)
    buttons.add_argument("--right", required=True)
    buttons.add_argument("--image")
    buttons.add_argument("--highlight", choices=("left", "right"))
    buttons.add_argument("--output")
    buttons.add_argument("--json", action="store_true")

    preset = sub.add_parser(
        "vibe-coding",
        help="Preset: vibe coding vs software engineering",
    )
    preset.add_argument("--output")
    preset.add_argument("--json", action="store_true")

    args = p.parse_args(argv)
    try:
        if args.command == "comparison":
            result = comparison(
                left=args.left,
                right=args.right,
                left_title=args.left_title,
                right_title=args.right_title,
                left_label=args.left_label,
                right_label=args.right_label,
                output=args.output,
            )
        elif args.command == "drake":
            result = drake(
                reject=args.reject,
                accept=args.accept,
                image=args.image,
                output=args.output,
            )
        elif args.command == "caption":
            result = caption(
                image=args.image,
                top=args.top,
                bottom=args.bottom,
                label=args.label,
                output=args.output,
            )
        elif args.command == "expanding-brain":
            result = expanding_brain(
                args.label,
                images=args.image,
                output=args.output,
            )
        elif args.command == "two-button":
            result = two_button(
                dilemma=args.dilemma,
                left=args.left,
                right=args.right,
                image=args.image,
                highlight=args.highlight,
                output=args.output,
            )
        else:
            result = vibe_coding_comparison(output=args.output)
    except (OSError, ValueError, RuntimeError) as exc:
        p.error(str(exc))
        return 2

    _print_result(result, as_json=args.json)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
