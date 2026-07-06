#!/usr/bin/env python3
"""YouTube thumbnails — high-quality Unsplash photo + title overlay (Pillow)."""

from __future__ import annotations

import argparse
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
import textwrap
from datetime import datetime
from pathlib import Path

from arka.media.compose_video import (
    _cover_crop,
    _hex_rgb,
    _load_font,
    _require_pillow,
    load_config,
    topic_label,
)
from arka.media.unsplash import download_photo, search_photos, setup_hint


THUMB_W = 1280
THUMB_H = 720

IMAGE_QUERIES: dict[str, str] = {
    "ai": "artificial intelligence",
    "ml": "machine learning",
    "dl": "deep learning",
    "nlp": "natural language processing",
    "llm": "large language model",
    "python": "python programming",
    "rust": "rust programming",
}

STYLE_WORDS = (
    "anime",
    "cyberpunk",
    "minimalist",
    "retro",
    "cartoon",
    "pixel art",
    "watercolor",
    "cinematic",
    "neon",
    "3d",
)

NO_TEXT = ", no text, no words, no letters, no typography, no watermark"
NO_LOGOS = ", no company logos, no brand names, no signage"
NO_ROBOTS = ", no robots, no androids, no humanoid machines"


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _default_output(topic: str) -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", topic_label(topic).lower())[:40].strip("-") or "thumbnail"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    env_dir = _env("IMAGE_OUTPUT_DIR") or _env("VIDEO_OUTPUT_DIR")
    out_dir = Path(env_dir).expanduser() if env_dir else Path.home() / "Pictures" / "arka-generated"
    out_dir.mkdir(parents=True, exist_ok=True)
    return out_dir / f"thumbnail-{slug}-{ts}.png"


def thumbnail_title(topic: str) -> str:
    label = topic_label(topic)
    key = topic.strip().lower()
    key = re.sub(r"\s+(?:video|clip|movie)$", "", key).strip()
    if key in {"ai", "artificial intelligence"}:
        return "What is AI?"
    if label.isupper() and len(label) <= 6:
        return f"What is {label}?"
    return f"What is {label}?"


def image_query(topic: str) -> str:
    key = topic.strip().lower()
    key = re.sub(r"\s+(?:video|clip|movie)$", "", key).strip()
    if key in IMAGE_QUERIES:
        return f"{IMAGE_QUERIES[key]} technology"
    return f"{topic_label(topic)} technology"


def extract_style(text: str) -> tuple[str, str]:
    """Return (text_without_style, style_slug)."""
    t = text.strip()
    style = ""
    m = re.search(
        rf"(?i)\b({'|'.join(re.escape(s) for s in STYLE_WORDS)})\s+style\b",
        t,
    )
    if m:
        style = re.sub(r"\s+", " ", m.group(1).lower()).strip()
        t = (t[: m.start()] + t[m.end() :]).strip()
    else:
        m = re.search(
            rf"(?i)\bstyle\s+({'|'.join(re.escape(s) for s in STYLE_WORDS)})\b",
            t,
        )
        if m:
            style = re.sub(r"\s+", " ", m.group(1).lower()).strip()
            t = (t[: m.start()] + t[m.end() :]).strip()
    return t, style


def extract_scene(text: str) -> tuple[str, str]:
    """Return (text_without_scene, scene_description)."""
    t = text.strip()
    patterns = [
        r"(?i)\b(?:that\s+)?(?:has|have|with|featuring|showing|including)\s+(.+)$",
        r"(?i)\bcontaining\s+(.+)$",
    ]
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            scene = m.group(1).strip().strip("'\"")
            scene = re.sub(r"(?i)\s+(?:please|thanks)$", "", scene).strip()
            t = t[: m.start()].strip()
            if scene:
                return t, scene
    return t, ""


def _prompt_suffix(*, allow_robots: bool = False) -> str:
    suffix = NO_TEXT + NO_LOGOS
    if not allow_robots:
        suffix += NO_ROBOTS
    return suffix


def styled_background_prompt(topic: str, style: str, scene: str = "") -> str:
    key = topic.strip().lower()
    key = re.sub(r"\s+(?:video|clip|movie)$", "", key).strip()
    subject = IMAGE_QUERIES.get(key, topic_label(topic))
    scene = scene.strip()
    allow_robots = bool(re.search(r"(?i)\brobot", scene))
    suffix = _prompt_suffix(allow_robots=allow_robots)

    if scene:
        return f"{style} style {subject}, {scene}, detailed illustration, wide cinematic background{suffix}"

    if style == "anime":
        return (
            f"anime style abstract {subject} landscape, glowing neural network sky, "
            f"digital aurora, scenic environment, empty atmosphere{suffix}"
        )
    if style == "cyberpunk":
        return (
            f"cyberpunk {subject} cityscape at night, neon ambient glow, "
            f"wide scenic view, no billboards{suffix}"
        )
    if style == "pixel art":
        return f"pixel art {subject} landscape, retro game scenery, colorful sky{suffix}"
    return f"{style} style {subject} scenic landscape, wide background{suffix}"


def parse_thumbnail_nl(text: str) -> dict[str, str]:
    patterns = [
        r"(?i)(?:generate|create|make|design)\s+(?:an?\s+)?(?:youtube\s+)?thumbnail\s+(?:for|of|about|on)\s+(.+)$",
        r"(?i)(?:youtube\s+)?thumbnail\s+(?:for|of|about|on)\s+(.+)$",
    ]
    raw = ""
    for pat in patterns:
        m = re.search(pat, text.strip())
        if m:
            raw = m.group(1).strip().strip("'\"")
            break
    if not raw:
        return {"topic": "", "style": "", "scene": ""}
    raw, style = extract_style(raw)
    raw, scene = extract_scene(raw)
    topic = normalize_topic(raw)
    topic = re.sub(r"(?i)\s+(?:video|clip|movie)$", "", topic).strip()
    return {"topic": topic, "style": style, "scene": scene}


def normalize_topic(raw: str) -> str:
    topic = raw.strip().strip("'\"")
    topic = re.sub(r"(?i)\s+(?:video|clip|please)$", "", topic).strip()
    return topic


def render_thumbnail(image_path: Path, title: str, output: Path) -> None:
    Image, ImageDraw, _ImageFilter, ImageFont = _require_pillow()
    cfg = load_config()
    width, height = THUMB_W, THUMB_H
    title_size = max(72, int(width * 0.085))
    margin = 56
    lines = textwrap.wrap(title, width=16) or [title]

    canvas = Image.new("RGB", (width, height), _hex_rgb(cfg.bg_color))
    photo = Image.open(image_path).convert("RGB")
    photo = _cover_crop(photo, width, height)
    canvas.paste(photo, (0, 0))

    text_block_h = margin + len(lines) * (title_size + 10) + 16
    grad_height = min(text_block_h, int(height * 0.22))
    overlay = Image.new("RGBA", (width, height), (0, 0, 0, 0))
    draw_ov = ImageDraw.Draw(overlay)
    for row in range(grad_height):
        alpha = int(min(150, 40 + 110 * (1 - row / max(1, grad_height))))
        draw_ov.line([(0, row), (width, row)], fill=(15, 23, 42, alpha))
    canvas = Image.alpha_composite(canvas.convert("RGBA"), overlay).convert("RGB")

    draw = ImageDraw.Draw(canvas)
    title_font = _load_font(ImageFont, cfg.font_bold_path or cfg.font_path, title_size)
    y = margin
    accent = _hex_rgb(cfg.accent_color)
    text_color = _hex_rgb(cfg.text_color)
    draw.rectangle([margin - 16, y - 12, margin + 6, y + title_size], fill=accent)
    for line in lines:
        draw.text((margin, y), line, font=title_font, fill=text_color)
        y += title_size + 10

    output.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(output, format="PNG", optimize=True)


def _fetch_background(topic: str, style: str, work: Path, *, scene: str = "") -> tuple[Path, dict]:
    if style:
        from arka.generate.image import generate as gen_image

        prompt = styled_background_prompt(topic, style, scene)
        print(f"Generating {style} background …", file=sys.stderr)
        print(f"  Prompt: {prompt}", file=sys.stderr)
        img_path = work / "background.png"
        gen_image(prompt, img_path, "16:9", "")
        meta: dict = {"background": "ai", "prompt": prompt, "style": style}
        if scene:
            meta["scene"] = scene
        return img_path, meta

    query = image_query(topic)
    print(f"Searching Unsplash: {query!r}", file=sys.stderr)
    photos = search_photos(query, count=5, orientation="landscape", size="full")
    photo = photos[0]
    img_path = work / "photo.jpg"
    download_photo(photo, img_path)
    return img_path, {
        "background": "unsplash",
        "query": query,
        "photographer": photo.photographer,
        "url": photo.photographer_url,
    }


def generate(
    topic: str,
    *,
    title: str = "",
    style: str = "",
    scene: str = "",
    output: Path | None = None,
) -> tuple[Path, dict]:
    topic = normalize_topic(topic)
    style = style.strip().lower()
    scene = scene.strip()
    if not topic:
        raise SystemExit("Topic is required.")
    label = thumbnail_title(topic) if not title else title.strip()
    work = Path(tempfile.mkdtemp(prefix="arka-thumb-"))
    try:
        img_path, bg_meta = _fetch_background(topic, style, work, scene=scene)
        slug = topic
        if style:
            slug = f"{topic}-{style.replace(' ', '-')}"
        out = output or _default_output(slug)
        print(f"Rendering title: {label}", file=sys.stderr)
        render_thumbnail(img_path, label, out)
    finally:
        import shutil

        shutil.rmtree(work, ignore_errors=True)

    credits = {
        "topic": topic,
        "title": label,
        "style": style or None,
        "scene": scene or None,
        "source": "arka-generate-thumbnail",
        **bg_meta,
    }
    meta = out.with_suffix(".json")
    meta.write_text(json.dumps(credits, indent=2), encoding="utf-8")
    return out, credits


def nl_to_argv(text: str) -> list[str]:
    t = text.strip()
    if not t:
        return []
    if not re.search(
        r"(?i)(?:^|\b)(?:generate|create|make|design)\s+(?:an?\s+)?(?:youtube\s+)?thumbnail\b",
        t,
    ):
        return []
    parsed = parse_thumbnail_nl(t)
    if not parsed["topic"]:
        return []
    argv = ["--topic", parsed["topic"]]
    if parsed["style"]:
        argv.extend(["--style", parsed["style"]])
    if parsed.get("scene"):
        argv.extend(["--scene", parsed["scene"]])
    return argv


def cmd_generate(args: argparse.Namespace) -> int:
    out = Path(args.output).expanduser() if args.output else None
    saved, credits = generate(
        args.topic,
        title=args.title or "",
        style=getattr(args, "style", "") or "",
        scene=getattr(args, "scene", "") or "",
        output=out,
    )
    print(f"Saved: {saved}")
    if credits.get("background") == "unsplash":
        print(f"Credits: {saved.with_suffix('.json')} — {credits.get('photographer')} on Unsplash")
    else:
        print(f"Credits: {saved.with_suffix('.json')} — AI background ({credits.get('style')})")
    if _env("OPEN_IMAGE", "1") not in {"0", "false"}:
        _open_image(saved)
    return 0


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def cmd_check(_args: argparse.Namespace) -> int:
    ok = True
    try:
        _require_pillow()
        print("✓ Pillow")
    except SystemExit:
        print("✗ Pillow missing", file=sys.stderr)
        ok = False
    try:
        from arka.media.unsplash import access_key

        if access_key():
            print("✓ Unsplash key set")
        else:
            print(f"✗ {setup_hint()}", file=sys.stderr)
            ok = False
    except ImportError:
        ok = False
    return 0 if ok else 1


def _open_image(path: Path) -> None:
    if sys.platform == "darwin":
        subprocess.Popen(["open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
    elif sys.platform.startswith("linux"):
        import shutil

        if shutil.which("xdg-open"):
            subprocess.Popen(["xdg-open", str(path)], stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(description="YouTube thumbnails — Unsplash photo + title overlay")
    sub = p.add_subparsers(dest="cmd")

    p_gen = sub.add_parser("generate", help="Build thumbnail from topic")
    p_gen.add_argument("--topic", required=True, help="Video topic (e.g. ai, machine learning)")
    p_gen.add_argument("--title", default="", help="Overlay title (default: What is …?)")
    p_gen.add_argument("--style", default="", help="Visual style (anime, cyberpunk, pixel art, …)")
    p_gen.add_argument("--scene", default="", help="Background scene (e.g. 'a robot', 'neon city')")
    p_gen.add_argument("-o", "--output", help="Output PNG path")
    p_gen.set_defaults(func=cmd_generate)

    p_parse = sub.add_parser("parse", help="Parse natural language → generate_thumbnail args")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)

    p_check = sub.add_parser("check", help="Verify Pillow and Unsplash key")
    p_check.set_defaults(func=cmd_check)

    return p


def main(argv: list[str] | None = None) -> int:
    argv = list(argv if argv is not None else sys.argv[1:])
    if not argv:
        build_parser().print_help()
        return 0
    if argv[0] not in {"generate", "parse", "check", "-h", "--help"}:
        nl = nl_to_argv(" ".join(argv))
        if nl:
            argv = ["generate", *nl]
        else:
            build_parser().print_help()
            return 1
    parser = build_parser()
    args = parser.parse_args(argv)
    if not args.cmd:
        parser.print_help()
        return 0
    return args.func(args)


if __name__ == "__main__":
    raise SystemExit(main())
