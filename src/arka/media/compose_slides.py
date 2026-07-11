#!/usr/bin/env python3
"""Compose presentation slide decks — stock photos, charts, LLM scripts (like compose_video)."""

from __future__ import annotations

import argparse
import base64
import html as html_module
import json
import os
import re
import shlex
import subprocess
import sys
import tempfile
from dataclasses import dataclass, field
from datetime import datetime
from pathlib import Path

from arka.media.compose_video import (
    Scene,
    VideoConfig,
    _attach_photo_queries,
    _enrich_scenes,
    _fetch_scene_photo,
    _llm_available,
    _llm_enrich_image_keywords,
    _llm_script,
    _llm_summarize_script,
    _parse_scenes_json,
    _render_photo_slide,
    _scene_search_query,
    _script_mode,
    _script_needs_shortening,
    _template_script,
    _which,
    load_config,
    normalize_topic,
    topic_label,
)
from arka.media.stock_photos import any_source_available, setup_hint as stock_setup_hint

SLIDE_FORMATS = ("pptx", "pdf", "html", "md", "json")
FORMAT_EXTENSIONS = {
    "pptx": ".pptx",
    "pdf": ".pdf",
    "html": ".html",
    "md": ".md",
    "json": ".json",
}
FORMAT_ALIASES = {
    "pptx": "pptx",
    "ppt": "pptx",
    "powerpoint": "pptx",
    "pdf": "pdf",
    "html": "html",
    "htm": "html",
    "md": "md",
    "markdown": "md",
    "marp": "md",
    "json": "json",
}


def _env(name: str, default: str = "") -> str:
    return os.environ.get(name, default).strip()


def _default_format() -> str:
    raw = (_env("SLIDES_DEFAULT_FORMAT") or "pptx").lower()
    return normalize_format(raw) or "pptx"


def normalize_format(name: str) -> str:
    return FORMAT_ALIASES.get((name or "").strip().lower(), "")


def parse_formats_arg(value: str | None) -> list[str]:
    raw = (value or "auto").strip().lower()
    if raw in {"", "auto"}:
        return [_default_format()]
    if raw == "all":
        return list(SLIDE_FORMATS)
    formats: list[str] = []
    for token in re.split(r"[,+\s]+", raw):
        token = token.strip()
        if not token:
            continue
        fmt = normalize_format(token)
        if not fmt:
            known = ", ".join(SLIDE_FORMATS + ("all", "auto"))
            raise SystemExit(f"Unknown slide format {token!r}. Choose: {known}")
        if fmt not in formats:
            formats.append(fmt)
    return formats or [_default_format()]


def _output_paths(output: Path, formats: list[str]) -> dict[str, Path]:
    stem = output.with_suffix("")
    if len(formats) == 1:
        fmt = formats[0]
        return {fmt: stem.with_suffix(FORMAT_EXTENSIONS[fmt])}
    return {fmt: stem.with_suffix(FORMAT_EXTENSIONS[fmt]) for fmt in formats}


def _default_output(topic: str, fmt: str = "pptx") -> Path:
    slug = re.sub(r"[^a-z0-9]+", "-", topic_label(topic).lower())[:40].strip("-") or "slides"
    ts = datetime.now().strftime("%Y%m%d-%H%M%S")
    env_dir = _env("SLIDES_OUTPUT_DIR") or _env("VIDEO_OUTPUT_DIR") or _env("IMAGE_OUTPUT_DIR")
    out_dir = Path(env_dir).expanduser() if env_dir else Path.home() / "Documents" / "arka-slides"
    out_dir.mkdir(parents=True, exist_ok=True)
    ext = FORMAT_EXTENSIONS.get(fmt, ".pptx")
    return out_dir / f"{slug}-{ts}{ext}"


def _strip_format_from_text(text: str) -> tuple[str, str | None]:
    """Remove format hints from NL; return (cleaned, format or None)."""
    t = text.strip()
    if not t:
        return "", None

    alias_pat = "|".join(re.escape(k) for k in sorted(FORMAT_ALIASES, key=len, reverse=True))

    def _alias(word: str) -> str:
        return FORMAT_ALIASES.get(word.lower(), "")

    found: str | None = None

    m = re.search(rf"(?i)\b(?:as|in|to|into|export(?:ed)?)\s+({alias_pat})\s*$", t)
    if m:
        found = _alias(m.group(1)) or found
        t = t[: m.start()].strip()

    m = re.search(rf"(?i)^({alias_pat})\s+(?=(?:slide|slides|presentation|deck|slideshow)\b)", t)
    if m:
        found = found or _alias(m.group(1))
        t = (t[: m.start()] + t[m.end() :]).strip()

    m = re.search(rf"(?i)\b({alias_pat})\s+(?=(?:slide|slides|presentation|deck|slideshow)\b)", t)
    if m:
        found = found or _alias(m.group(1))
        t = (t[: m.start()] + t[m.end() :]).strip()

    t = re.sub(r"\s{2,}", " ", t).strip(" ,;")
    return t, found


def _extract_format_from_nl(text: str) -> str | None:
    _, fmt = _strip_format_from_text(text)
    return fmt


def _require_pptx():
    try:
        from pptx import Presentation
        from pptx.util import Emu
    except ImportError as exc:
        raise SystemExit(
            "python-pptx is required for slide decks.\n"
            "Install: pip install 'arka-agent[video]'  or  pip install python-pptx Pillow"
        ) from exc
    return Presentation, Emu


def extract_slides_topic(text: str) -> str:
    """Pull the subject out of NL like 'make slides about kubernetes'."""
    t = text.strip().strip("'\"")
    if not t:
        return ""
    t, _ = _strip_format_from_text(t)
    patterns = [
        r"(?i)(?:^|\b)(?:make|create|compose|build|render|produce|generate|arka)\s+"
        r"(?:a\s+|an\s+)?(?:\d+\s+)?(?:slide|slides|presentation|deck|powerpoint|pptx?|pdf|html|markdown|marp)\s+"
        r"(?:on|about|for|explaining|covering)\s+(.+)$",
        r"(?i)(?:^|\b)(?:slide|slides|presentation|deck)\s+(?:on|about|for|explaining|covering)\s+(.+)$",
        r"(?i)^compose\s+(?:a\s+)?(?:slide|slides|presentation|deck)\s+"
        r"(?:on|about|for|explaining|covering)\s+(.+)$",
        r"(?i)(?:^|\b)(?:pdf|html|markdown|marp)\s+(?:slide|slides|presentation|deck)\s+"
        r"(?:on|about|for|explaining|covering)\s+(.+)$",
    ]
    for pat in patterns:
        m = re.search(pat, t)
        if m:
            topic = m.group(1).strip().strip("'\"")
            topic = re.sub(r"(?i)\s+(?:with\s+llm|please)$", "", topic).strip()
            topic, _ = _strip_format_from_text(topic)
            if topic:
                return topic
    cleaned, _ = _strip_format_from_text(t)
    return normalize_topic(cleaned)


def nl_to_argv_convert(text: str) -> list[str]:
    """Parse NL like 'convert slides.pptx to pdf' → convert argv."""
    t = text.strip().strip("'\"")
    if not t:
        return []

    alias_pat = "|".join(re.escape(k) for k in sorted(FORMAT_ALIASES, key=len, reverse=True))

    if not re.search(
        r"(?i)\b(?:convert|export|transform)\s+(?:my\s+)?(?:presentation|slides|deck|slideshow)\b",
        t,
    ) and not re.search(
        r"(?i)\bconvert\s+\S+\.(?:pptx|pdf|html|md|json|markdown|marp|ppt|htm)\b",
        t,
    ):
        if not re.search(
            r"(?i)\bconvert\s+['\"]?.+\.(?:pptx|pdf|html|md|json|markdown|marp|ppt|htm)",
            t,
        ):
            return []

    fmt: str | None = None
    for pat in (
        rf"(?i)(?:-+\s*)?(?:format|output)\s+(?:is\s+)?({alias_pat}|all)\b",
        rf"(?i)\b(?:to|into|as)\s+(?:a\s+)?({alias_pat}|all)\b",
    ):
        m = re.search(pat, t)
        if m:
            token = m.group(1).lower()
            fmt = "all" if token == "all" else normalize_format(token)
            t = (t[: m.start()] + t[m.end() :]).strip()

    input_path = ""
    for pat in (
        r"(?i)\bconvert\s+(.+?)\s+(?:to|into|as)\s+",
        r"(?i)\b(?:convert|export|transform)\s+(?:my\s+)?(?:presentation|slides|deck|slideshow)\s+(?:to|into|as)\s+",
        r"(?i)\bconvert\s+(.+)$",
        r"(?i)\b(?:export|transform)\s+(.+?)\s+(?:to|into|as)\s+",
    ):
        m = re.search(pat, t)
        if m:
            candidate = m.group(1).strip().strip("'\"")
            if candidate and not normalize_format(candidate):
                input_path = candidate
                break

    if not input_path:
        file_m = re.search(
            r"(?i)(['\"]?[\w./~-]+\.(?:pptx|pdf|html|htm|md|markdown|marp|json|ppt)['\"]?)",
            t,
        )
        if file_m:
            input_path = file_m.group(1).strip("'\"")

    if not input_path:
        return []

    argv = ["convert", input_path]
    if fmt:
        argv.extend(["--format", fmt])
    return argv


def nl_to_argv(text: str) -> list[str]:
    t = text.strip()
    if not t:
        return []

    convert_argv = nl_to_argv_convert(t)
    if convert_argv:
        return convert_argv

    slide_intent = re.search(
        r"(?i)(?:^|\b)(?:make|create|compose|build|render|produce|generate|arka)\s+"
        r"(?:a\s+|an\s+)?(?:\d+\s+)?(?:slide|slides|presentation|deck|powerpoint|pptx?|pdf|html|markdown|marp)\s+"
        r"(?:on|about|for|explaining|covering)\s+\S",
        t,
    ) or re.search(
        r"(?i)(?:^|\b)(?:slide|slides|presentation|deck)\s+(?:on|about|for|explaining|covering)\s+\S",
        t,
    ) or re.search(
        r"(?i)^compose\s+(?:a\s+)?(?:slide|slides|presentation|deck)\s+"
        r"(?:on|about|for|explaining|covering)\s+\S",
        t,
    ) or re.search(
        r"(?i)(?:^|\b)(?:pdf|html|markdown|marp)\s+(?:slide|slides|presentation|deck)\s+"
        r"(?:on|about|for|explaining|covering)\s+\S",
        t,
    )
    if not slide_intent:
        return []

    topic = extract_slides_topic(t)
    if not topic:
        return []
    argv = ["compose", "--topic", topic]
    fmt = _extract_format_from_nl(t)
    if fmt:
        argv.extend(["--format", fmt])
    if re.search(r"(?i)\b(llm|write script)\b", t):
        argv.append("--llm")
    return argv


def _render_scene_png(
    scene: Scene,
    *,
    topic: str,
    work: Path,
    index: int,
    cfg: VideoConfig,
    used_photo_ids: set[str],
    credits: list[dict],
) -> Path:
    from arka.media.chart_slide import render_scene_visual, render_title_slide, scene_has_chart_visual

    out = work / f"slide-{index:02d}.png"
    if scene_has_chart_visual(scene):
        return render_scene_visual(scene, work, cfg, index=index)

    if any_source_available():
        query = _scene_search_query(scene, topic)
        try:
            photo = _fetch_scene_photo(
                query,
                used_photo_ids,
                orientation=cfg.orientation,
                segment_idx=0,
            )
            scene.photo = photo
            credits.append(
                {
                    "title": scene.title,
                    "query": query,
                    "source": getattr(photo, "source", ""),
                    "author": getattr(photo, "author", ""),
                    "url": getattr(photo, "url", ""),
                }
            )
            _render_photo_slide(
                scene,
                photo,
                work=work,
                scene_idx=index,
                segment_idx=0,
                slide=out,
                cfg=cfg,
            )
            return out
        except SystemExit:
            pass

    return render_title_slide(scene, out, cfg)


def _build_pptx(
    slide_images: list[tuple[Path, Scene]],
    output: Path,
    *,
    topic: str,
    cfg: VideoConfig,
) -> Path:
    Presentation, Emu = _require_pptx()
    prs = Presentation()
    prs.slide_width = Emu(cfg.width * 9525)
    prs.slide_height = Emu(cfg.height * 9525)
    blank_layout = prs.slide_layouts[6]

    for png_path, scene in slide_images:
        slide = prs.slides.add_slide(blank_layout)
        slide.shapes.add_picture(
            str(png_path),
            left=0,
            top=0,
            width=prs.slide_width,
            height=prs.slide_height,
        )
        notes = (scene.narration or scene.body or "").strip()
        if notes:
            slide.notes_slide.notes_text_frame.text = notes

    output.parent.mkdir(parents=True, exist_ok=True)
    prs.save(str(output))
    return output


def _build_pdf(
    slide_images: list[tuple[Path, Scene]],
    output: Path,
    **_,
) -> Path:
    from arka.media.compose_video import _require_pillow

    Image, *_ = _require_pillow()
    images = []
    for png_path, _ in slide_images:
        img = Image.open(png_path)
        if img.mode != "RGB":
            img = img.convert("RGB")
        images.append(img)
    if not images:
        raise SystemExit("No slide images to export as PDF.")
    output.parent.mkdir(parents=True, exist_ok=True)
    images[0].save(
        str(output),
        "PDF",
        save_all=True,
        append_images=images[1:],
        resolution=100.0,
    )
    return output


def _png_data_uri(path: Path) -> str:
    import base64

    data = base64.b64encode(path.read_bytes()).decode("ascii")
    return f"data:image/png;base64,{data}"


def _build_html(
    slide_images: list[tuple[Path, Scene]],
    output: Path,
    *,
    topic: str,
    **_,
) -> Path:
    slides_html = []
    for i, (png_path, scene) in enumerate(slide_images):
        active = " active" if i == 0 else ""
        notes = (scene.narration or scene.body or "").strip()
        note_html = f'<p class="notes">{_html_escape(notes)}</p>' if notes else ""
        slides_html.append(
            f'<section class="slide{active}" data-index="{i}">'
            f'<img src="{_png_data_uri(png_path)}" alt="{_html_escape(scene.title)}">'
            f"{note_html}</section>"
        )
    title = _html_escape(topic_label(topic))
    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8">
<meta name="viewport" content="width=device-width, initial-scale=1">
<title>{title}</title>
<style>
  * {{ box-sizing: border-box; }}
  body {{ margin: 0; background: #111; color: #eee; font-family: system-ui, sans-serif; }}
  .deck {{ width: 100vw; height: 100vh; position: relative; overflow: hidden; }}
  .slide {{ display: none; width: 100%; height: 100%; align-items: center; justify-content: center; flex-direction: column; }}
  .slide.active {{ display: flex; }}
  .slide img {{ max-width: 100%; max-height: calc(100% - 3rem); object-fit: contain; }}
  .notes {{ position: absolute; bottom: 0; left: 0; right: 0; margin: 0; padding: 0.75rem 1rem; background: rgba(0,0,0,0.65); font-size: 0.9rem; }}
  .hint {{ position: fixed; top: 0.5rem; right: 0.5rem; opacity: 0.5; font-size: 0.75rem; }}
</style>
</head>
<body>
<div class="deck" id="deck">
{"".join(slides_html)}
</div>
<p class="hint">← → or Space</p>
<script>
(function() {{
  const slides = Array.from(document.querySelectorAll('.slide'));
  let idx = 0;
  function show(i) {{
    idx = (i + slides.length) % slides.length;
    slides.forEach((s, n) => s.classList.toggle('active', n === idx));
  }}
  document.addEventListener('keydown', (e) => {{
    if (['ArrowRight', 'ArrowDown', ' ', 'PageDown'].includes(e.key)) {{ e.preventDefault(); show(idx + 1); }}
    if (['ArrowLeft', 'ArrowUp', 'PageUp'].includes(e.key)) {{ e.preventDefault(); show(idx - 1); }}
  }});
  document.getElementById('deck').addEventListener('click', () => show(idx + 1));
}})();
</script>
</body>
</html>
"""
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(html, encoding="utf-8")
    return output


def _html_escape(text: str) -> str:
    return (
        text.replace("&", "&amp;")
        .replace("<", "&lt;")
        .replace(">", "&gt;")
        .replace('"', "&quot;")
    )


def _build_markdown(
    slide_images: list[tuple[Path, Scene]],
    output: Path,
    *,
    topic: str,
    scenes: list[Scene],
    **_,
) -> Path:
    _ = slide_images
    lines = [
        "---",
        f"title: {topic_label(topic)}",
        "marp: true",
        "---",
        "",
    ]
    for i, scene in enumerate(scenes):
        if i > 0:
            lines.extend(["", "---", ""])
        lines.append(f"# {scene.title}")
        body = (scene.body or "").strip()
        if body:
            lines.extend(["", body])
        captions = [c.strip() for c in (scene.captions or []) if c and c.strip()]
        if captions:
            lines.append("")
            lines.extend(f"- {c}" for c in captions)
        notes = (scene.narration or "").strip()
        if notes:
            lines.extend(["", f"<!-- speaker notes: {notes} -->"])
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text("\n".join(lines) + "\n", encoding="utf-8")
    return output


def _metadata_payload(
    *,
    topic: str,
    scenes: list[Scene],
    credits: list[dict],
    outputs: dict[str, str],
) -> dict:
    return {
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
            }
            for s in scenes
        ],
        "photo_credits": credits,
        "outputs": outputs,
        "formats": list(outputs),
        "source": "arka-compose-slides",
    }


def _build_json_export(
    slide_images: list[tuple[Path, Scene]],
    output: Path,
    *,
    topic: str,
    scenes: list[Scene],
    credits: list[dict],
    outputs: dict[str, str] | None = None,
    **_,
) -> Path:
    _ = slide_images
    payload = _metadata_payload(
        topic=topic,
        scenes=scenes,
        credits=credits,
        outputs=outputs or {output.suffix.lstrip("."): str(output)},
    )
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(payload, indent=2) + "\n", encoding="utf-8")
    return output


_EXPORTERS = {
    "pptx": _build_pptx,
    "pdf": _build_pdf,
    "html": _build_html,
    "md": _build_markdown,
    "json": _build_json_export,
}


def _export_formats(
    slide_images: list[tuple[Path, Scene]],
    output_paths: dict[str, Path],
    *,
    topic: str,
    scenes: list[Scene],
    cfg: VideoConfig,
    credits: list[dict],
) -> tuple[list[Path], dict[str, str]]:
    saved: list[Path] = []
    errors: list[str] = []
    outputs_map: dict[str, str] = {}

    for fmt, path in output_paths.items():
        if fmt == "json":
            continue
        try:
            exporter = _EXPORTERS[fmt]
            if fmt in {"pptx", "pdf"}:
                saved_path = exporter(slide_images, path, topic=topic, cfg=cfg)
            elif fmt == "html":
                saved_path = exporter(slide_images, path, topic=topic, cfg=cfg)
            else:
                saved_path = exporter(
                    slide_images,
                    path,
                    topic=topic,
                    scenes=scenes,
                    cfg=cfg,
                )
            saved.append(saved_path)
            outputs_map[fmt] = str(saved_path)
        except SystemExit as exc:
            msg = str(exc).strip() or f"{fmt} export unavailable"
            if len(output_paths) == 1:
                raise
            errors.append(f"{fmt}: {msg}")
            print(f"  Skipping {fmt} export — {msg}", file=sys.stderr)

    if not saved and "json" not in output_paths:
        detail = "; ".join(errors) if errors else "no exporters succeeded"
        raise SystemExit(f"No slide formats exported ({detail}).")

    if "json" in output_paths:
        try:
            saved_path = _build_json_export(
                slide_images,
                output_paths["json"],
                topic=topic,
                scenes=scenes,
                credits=credits,
                outputs=outputs_map,
                cfg=cfg,
            )
            saved.append(saved_path)
            outputs_map["json"] = str(saved_path)
        except SystemExit as exc:
            if len(output_paths) == 1:
                raise
            msg = str(exc).strip() or "json export unavailable"
            errors.append(f"json: {msg}")
            print(f"  Skipping json export — {msg}", file=sys.stderr)

    if not saved:
        detail = "; ".join(errors) if errors else "no exporters succeeded"
        raise SystemExit(f"No slide formats exported ({detail}).")

    return saved, outputs_map


def compose(
    scenes: list[Scene],
    *,
    output: Path,
    topic: str,
    cfg: VideoConfig | None = None,
    formats: list[str] | None = None,
) -> list[Path]:
    if not scenes:
        raise SystemExit("No scenes to render.")
    cfg = cfg or load_config()
    formats = formats or [_default_format()]
    from arka.media.chart_slide import scene_has_chart_visual

    needs_photos = any(not scene_has_chart_visual(s) for s in scenes)
    if needs_photos:
        _attach_photo_queries(scenes, topic)
        if not any_source_available():
            print(
                "  No stock photo API keys — using title slides only.",
                file=sys.stderr,
            )

    work = Path(tempfile.mkdtemp(prefix="arka-slides-"))
    used_photo_ids: set[str] = set()
    credits: list[dict] = []
    slide_images: list[tuple[Path, Scene]] = []

    try:
        for i, scene in enumerate(scenes):
            print(f"  Slide {i + 1}/{len(scenes)}: {scene.title}", file=sys.stderr)
            png = _render_scene_png(
                scene,
                topic=topic,
                work=work,
                index=i,
                cfg=cfg,
                used_photo_ids=used_photo_ids,
                credits=credits,
            )
            slide_images.append((png, scene))

        output_paths = _output_paths(output, formats)
        saved, outputs_map = _export_formats(
            slide_images,
            output_paths,
            topic=topic,
            scenes=scenes,
            cfg=cfg,
            credits=credits,
        )

        if "json" not in outputs_map:
            sidecar = output.with_suffix(".meta.json")
            sidecar.write_text(
                json.dumps(
                    _metadata_payload(
                        topic=topic,
                        scenes=scenes,
                        credits=credits,
                        outputs=outputs_map,
                    ),
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        return saved
    finally:
        import shutil

        shutil.rmtree(work, ignore_errors=True)


@dataclass
class LoadedDeck:
    topic: str
    scenes: list[Scene]
    slide_images: list[tuple[Path, Scene]] | None = None
    credits: list[dict] = field(default_factory=list)


def detect_format(path: Path, from_fmt: str | None = None) -> str:
    if from_fmt:
        fmt = normalize_format(from_fmt)
        if not fmt:
            known = ", ".join(SLIDE_FORMATS)
            raise SystemExit(f"Unknown --from format {from_fmt!r}. Choose: {known}")
        return fmt
    ext = path.suffix.lstrip(".").lower()
    fmt = normalize_format(ext)
    if fmt:
        return fmt
    known = ", ".join(SLIDE_FORMATS)
    raise SystemExit(
        f"Cannot detect slide format from {path.name!r} (extension {path.suffix!r}). "
        f"Use --from. Supported: {known}"
    )


def _find_sidecar(path: Path) -> Path | None:
    for candidate in (
        path.with_suffix(".meta.json"),
        path.with_suffix(".json"),
        path.parent / f"{path.stem}.meta.json",
    ):
        if candidate.is_file() and candidate.resolve() != path.resolve():
            try:
                data = json.loads(candidate.read_text(encoding="utf-8"))
            except json.JSONDecodeError:
                continue
            if isinstance(data, dict) and data.get("scenes"):
                return candidate
    return None


def _decode_data_uri(data_uri: str) -> bytes:
    if "," not in data_uri:
        raise ValueError("invalid data URI")
    _, encoded = data_uri.split(",", 1)
    return base64.b64decode(encoded)


def _decode_data_uri_to_file(data_uri: str, dest: Path) -> Path:
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(_decode_data_uri(data_uri))
    return dest


def _parse_markdown_deck(text: str) -> tuple[str, list[Scene]]:
    topic = ""
    body = text
    if body.startswith("---"):
        parts = body.split("---", 2)
        if len(parts) >= 3:
            for line in parts[1].splitlines():
                if line.strip().lower().startswith("title:"):
                    topic = line.split(":", 1)[1].strip().strip("'\"")
            body = parts[2]

    chunks = [chunk.strip() for chunk in re.split(r"\n---\n", body.strip()) if chunk.strip()]
    scenes: list[Scene] = []
    for chunk in chunks:
        if chunk.startswith("---"):
            continue
        title = ""
        body_lines: list[str] = []
        captions: list[str] = []
        notes = ""
        for line in chunk.splitlines():
            stripped = line.strip()
            if re.match(r"^#{1,6}\s", stripped):
                title = re.sub(r"^#{1,6}\s*", "", stripped).strip()
            elif stripped.startswith("- "):
                captions.append(stripped[2:].strip())
            elif stripped.lower().startswith("<!-- speaker notes:"):
                notes = stripped.split(":", 1)[1].strip().rstrip("-->").strip()
            elif not stripped.startswith("<!--"):
                body_lines.append(line)
        body_text = "\n".join(body_lines).strip()
        if not title and not body_text and not captions:
            continue
        scenes.append(
            Scene(
                title=title or f"Slide {len(scenes) + 1}",
                body=body_text,
                narration=notes,
                captions=captions,
            )
        )
    return topic, scenes


def _load_json_deck(path: Path) -> LoadedDeck:
    data = json.loads(path.read_text(encoding="utf-8"))
    if not isinstance(data, dict):
        raise SystemExit(f"Expected JSON object in {path.name}")
    topic = str(data.get("topic") or "").strip()
    scenes = _enrich_scenes(_parse_scenes_json(json.dumps(data)))
    if not scenes:
        raise SystemExit(f"No scenes found in {path.name}")
    credits = data.get("photo_credits") if isinstance(data.get("photo_credits"), list) else []
    return LoadedDeck(
        topic=topic or scenes[0].title,
        scenes=scenes,
        credits=credits,
    )


def _load_markdown_deck(path: Path) -> LoadedDeck:
    topic, scenes = _parse_markdown_deck(path.read_text(encoding="utf-8"))
    if not scenes:
        raise SystemExit(f"No slides found in markdown: {path.name}")
    return LoadedDeck(topic=topic or path.stem, scenes=scenes)


def _load_html_deck(path: Path, work: Path) -> LoadedDeck:
    sidecar = _find_sidecar(path)
    if sidecar:
        return _load_json_deck(sidecar)

    html = path.read_text(encoding="utf-8")
    title_m = re.search(r"<title>([^<]+)</title>", html, re.I)
    topic = html_module.unescape(title_m.group(1).strip()) if title_m else path.stem

    scenes: list[Scene] = []
    slide_images: list[tuple[Path, Scene]] = []
    section_re = re.compile(
        r'<section[^>]*class="[^"]*slide[^"]*"[^>]*data-index="(\d+)"[^>]*>(.*?)</section>',
        re.S | re.I,
    )
    matches = list(section_re.finditer(html))
    if not matches:
        raise SystemExit(
            f"Could not parse slides from HTML: {path.name}\n"
            "Expected arka HTML sections, or place a .meta.json sidecar beside the file."
        )

    for match in matches:
        idx = int(match.group(1))
        body = match.group(2)
        img_m = re.search(r'<img[^>]+alt="([^"]*)"', body, re.I)
        title = html_module.unescape(img_m.group(1)) if img_m else f"Slide {idx + 1}"
        notes_m = re.search(r'<p class="notes">([^<]*)</p>', body, re.I)
        notes = html_module.unescape(notes_m.group(1)) if notes_m else ""
        scene = Scene(title=title, body=notes or title, narration=notes)
        scenes.append(scene)
        data_uri_m = re.search(r'src="(data:image/[^;]+;base64,[^"]+)"', body, re.I)
        if data_uri_m:
            png = _decode_data_uri_to_file(data_uri_m.group(1), work / f"slide-{idx:02d}.png")
            slide_images.append((png, scene))

    return LoadedDeck(
        topic=topic,
        scenes=scenes,
        slide_images=slide_images or None,
    )


def _extract_pptx_images(path: Path, work: Path) -> list[tuple[Path, int]]:
    Presentation, _ = _require_pptx()
    from pptx.enum.shapes import MSO_SHAPE_TYPE

    prs = Presentation(str(path))
    images: list[tuple[Path, int]] = []
    for i, slide in enumerate(prs.slides):
        for shape in slide.shapes:
            if shape.shape_type == MSO_SHAPE_TYPE.PICTURE:
                try:
                    png_path = work / f"slide-{i:02d}.png"
                    png_path.write_bytes(shape.image.blob)
                    images.append((png_path, i))
                except (AttributeError, OSError):
                    pass
                break
    return images


def _load_pptx_deck(path: Path, work: Path) -> LoadedDeck:
    sidecar = _find_sidecar(path)
    images = _extract_pptx_images(path, work)

    if sidecar:
        deck = _load_json_deck(sidecar)
        if images:
            slide_images: list[tuple[Path, Scene]] = []
            for png_path, idx in images:
                if idx < len(deck.scenes):
                    deck.scenes[idx].slide_image = str(png_path)
                    slide_images.append((png_path, deck.scenes[idx]))
                else:
                    scene = Scene(title=f"Slide {idx + 1}", body=f"Slide {idx + 1}")
                    scene.slide_image = str(png_path)
                    deck.scenes.append(scene)
                    slide_images.append((png_path, scene))
            deck.slide_images = slide_images or None
        return deck

    Presentation, _ = _require_pptx()

    prs = Presentation(str(path))
    scenes: list[Scene] = []
    slide_images: list[tuple[Path, Scene]] = []

    for i, slide in enumerate(prs.slides):
        texts: list[str] = []
        png_path: Path | None = None
        for shape in slide.shapes:
            if hasattr(shape, "text"):
                chunk = (shape.text or "").strip()
                if chunk:
                    texts.append(chunk)
        for png_path_c, idx in images:
            if idx == i:
                png_path = png_path_c
                break
        notes = ""
        if slide.has_notes_slide and slide.notes_slide.notes_text_frame:
            notes = (slide.notes_slide.notes_text_frame.text or "").strip()
        title = texts[0] if texts else f"Slide {i + 1}"
        body = "\n".join(texts[1:]).strip() if len(texts) > 1 else ""
        scene = Scene(title=title, body=body or title, narration=notes)
        scenes.append(scene)
        if png_path and png_path.is_file():
            scene.slide_image = str(png_path)
            slide_images.append((png_path, scene))

    if not scenes:
        raise SystemExit(f"No slides found in {path.name}")
    topic = path.stem
    return LoadedDeck(topic=topic, scenes=scenes, slide_images=slide_images or None)


def _require_pymupdf():
    try:
        import fitz  # noqa: F401
    except ImportError as exc:
        raise SystemExit(
            "PyMuPDF is required to convert PDF slide decks.\n"
            "Install: pip install pymupdf\n"
            "Or: pip install 'arka-agent[drawings]'\n"
            "Tip: place a .meta.json sidecar beside the PDF for text-only conversion."
        ) from exc


def _load_pdf_deck(path: Path, work: Path) -> LoadedDeck:
    sidecar = _find_sidecar(path)
    if sidecar:
        return _load_json_deck(sidecar)

    _require_pymupdf()
    import fitz

    doc = fitz.open(path)
    try:
        if len(doc) == 0:
            raise SystemExit(f"PDF has no pages: {path.name}")
        scenes: list[Scene] = []
        slide_images: list[tuple[Path, Scene]] = []
        zoom = float(_env("SLIDES_PDF_ZOOM", "2.0"))
        matrix = fitz.Matrix(zoom, zoom)
        for i in range(len(doc)):
            page = doc.load_page(i)
            pix = page.get_pixmap(matrix=matrix, alpha=False)
            png = work / f"slide-{i:02d}.png"
            png.write_bytes(pix.tobytes("png"))
            scene = Scene(title=f"Slide {i + 1}", body=f"Slide {i + 1}")
            scene.slide_image = str(png)
            scenes.append(scene)
            slide_images.append((png, scene))
        return LoadedDeck(topic=path.stem, scenes=scenes, slide_images=slide_images)
    finally:
        doc.close()


def _soffice_convert(input_path: Path, to_ext: str, out_dir: Path) -> Path:
    soffice = _which("soffice") or _which("libreoffice")
    if not soffice:
        raise SystemExit(
            f"LibreOffice (soffice) is required for direct {input_path.suffix} → .{to_ext} conversion.\n"
            "Install LibreOffice, or convert via JSON/HTML sidecar first."
        )
    out_dir.mkdir(parents=True, exist_ok=True)
    cmd = [
        soffice,
        "--headless",
        "--convert-to",
        to_ext,
        "--outdir",
        str(out_dir),
        str(input_path),
    ]
    proc = subprocess.run(cmd, capture_output=True, text=True)
    if proc.returncode != 0:
        detail = (proc.stderr or proc.stdout or "").strip()
        raise SystemExit(f"LibreOffice conversion failed: {detail or proc.returncode}")
    out = out_dir / f"{input_path.stem}.{to_ext}"
    if not out.is_file():
        matches = sorted(out_dir.glob(f"{input_path.stem}*.{to_ext}"))
        if not matches:
            raise SystemExit(f"LibreOffice did not produce .{to_ext} output for {input_path.name}")
        out = matches[0]
    return out


def load_deck(path: Path, from_fmt: str | None = None, *, work: Path | None = None) -> LoadedDeck:
    path = path.expanduser().resolve()
    if not path.is_file():
        raise SystemExit(f"Input not found: {path}")
    fmt = detect_format(path, from_fmt)
    work_dir = work or Path(tempfile.mkdtemp(prefix="arka-slides-load-"))

    loaders = {
        "json": lambda p: _load_json_deck(p),
        "md": lambda p: _load_markdown_deck(p),
        "html": lambda p: _load_html_deck(p, work_dir),
        "pptx": lambda p: _load_pptx_deck(p, work_dir),
        "pdf": lambda p: _load_pdf_deck(p, work_dir),
    }
    return loaders[fmt](path)


def _render_convert_slides(
    scenes: list[Scene],
    *,
    work: Path,
    cfg: VideoConfig,
    existing_images: list[tuple[Path, Scene]] | None = None,
) -> list[tuple[Path, Scene]]:
    from arka.media.chart_slide import render_scene_visual, render_title_slide, scene_has_chart_visual

    import shutil

    existing = {i: img for i, (img, _) in enumerate(existing_images or [])}
    slide_images: list[tuple[Path, Scene]] = []
    for i, scene in enumerate(scenes):
        if i in existing and existing[i].is_file():
            slide_images.append((existing[i], scene))
            continue
        if scene.slide_image:
            src = Path(scene.slide_image).expanduser()
            if src.is_file():
                dest = work / f"slide-{i:02d}.png"
                shutil.copy2(src, dest)
                slide_images.append((dest, scene))
                continue
        out = work / f"slide-{i:02d}.png"
        if scene_has_chart_visual(scene):
            png = render_scene_visual(scene, work, cfg, index=i)
        else:
            png = render_title_slide(scene, out, cfg)
        slide_images.append((png, scene))
    return slide_images


def convert_deck(
    input_path: Path,
    *,
    output: Path,
    formats: list[str],
    from_fmt: str | None = None,
    cfg: VideoConfig | None = None,
) -> list[Path]:
    """Convert an existing slide deck between supported formats."""
    input_path = input_path.expanduser()
    if not formats:
        raise SystemExit("No output formats specified.")

    src_fmt = detect_format(input_path, from_fmt)
    direct_pairs = {("pptx", "pdf"), ("pdf", "pptx")}
    if len(formats) == 1 and (src_fmt, formats[0]) in direct_pairs:
        try:
            out_dir = output.parent if output.suffix else output.parent
            out_dir.mkdir(parents=True, exist_ok=True)
            direct = _soffice_convert(input_path.resolve(), formats[0], out_dir)
            target = output if output.suffix else output.with_suffix(FORMAT_EXTENSIONS[formats[0]])
            if direct.resolve() != target.resolve():
                target.parent.mkdir(parents=True, exist_ok=True)
                direct.replace(target)
                direct = target
            return [direct]
        except SystemExit:
            if formats[0] not in SLIDE_FORMATS:
                raise
            print("  Direct office conversion unavailable — using scene pipeline …", file=sys.stderr)

    cfg = cfg or load_config()
    work = Path(tempfile.mkdtemp(prefix="arka-slides-convert-"))
    try:
        deck = load_deck(input_path, from_fmt, work=work)
        if not deck.scenes:
            raise SystemExit("No slides to convert.")

        print(
            f"Converting {input_path.name} ({src_fmt}) → {', '.join(formats)} ({len(deck.scenes)} slides)",
            file=sys.stderr,
        )

        slide_images = _render_convert_slides(
            deck.scenes,
            work=work,
            cfg=cfg,
            existing_images=deck.slide_images,
        )

        output_paths = _output_paths(output, formats)
        saved, outputs_map = _export_formats(
            slide_images,
            output_paths,
            topic=deck.topic,
            scenes=deck.scenes,
            cfg=cfg,
            credits=deck.credits,
        )

        if "json" not in outputs_map:
            sidecar = output.with_suffix(".meta.json")
            sidecar.write_text(
                json.dumps(
                    _metadata_payload(
                        topic=deck.topic,
                        scenes=deck.scenes,
                        credits=deck.credits,
                        outputs=outputs_map,
                    ),
                    indent=2,
                )
                + "\n",
                encoding="utf-8",
            )
        return saved
    finally:
        import shutil

        shutil.rmtree(work, ignore_errors=True)


def build_parser() -> argparse.ArgumentParser:
    p = argparse.ArgumentParser(
        description="Compose and convert presentation slide decks — pptx, pdf, html, md, json"
    )
    sub = p.add_subparsers(dest="cmd")

    p_compose = sub.add_parser("compose", help="Build slides from topic or script")
    p_compose.add_argument("--topic", help="Presentation topic (template or --llm script)")
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
        "-f",
        "--format",
        default="auto",
        help="Export format: pptx, pdf, html, md, json, auto (default), or all",
    )
    p_compose.add_argument("-o", "--output", help="Output path (extension adjusted per --format)")
    p_compose.set_defaults(func=cmd_compose)

    p_convert = sub.add_parser("convert", help="Convert an existing deck between formats")
    p_convert.add_argument("input", help="Input deck (.pptx, .pdf, .html, .md, .json)")
    p_convert.add_argument(
        "-f",
        "--format",
        "--to",
        dest="format",
        default="auto",
        help="Output format: pptx, pdf, html, md, json, auto (from -o extension), or all",
    )
    p_convert.add_argument(
        "--from",
        dest="from_fmt",
        default=None,
        help="Input format (auto-detected from extension when omitted)",
    )
    p_convert.add_argument("-o", "--output", help="Output path (extension adjusted per --format)")
    p_convert.set_defaults(func=cmd_convert)

    p_parse = sub.add_parser("parse", help="Parse natural language → compose args")
    p_parse.add_argument("text", nargs="+")
    p_parse.set_defaults(func=cmd_parse)

    p_check = sub.add_parser("check", help="Verify exporters, Pillow, stock photo keys")
    p_check.set_defaults(func=cmd_check)

    return p


def cmd_check(_args: argparse.Namespace) -> int:
    ok = True
    try:
        _require_pptx()
        print("✓ pptx (python-pptx)")
    except SystemExit:
        print("✗ pptx — pip install python-pptx", file=sys.stderr)
        ok = False
    try:
        from arka.media.compose_video import _require_pillow

        _require_pillow()
        print("✓ pdf (Pillow)")
    except SystemExit:
        print("✗ pdf — pip install Pillow", file=sys.stderr)
        ok = False
    print("✓ html (stdlib)")
    print("✓ md (stdlib)")
    print("✓ json (stdlib)")
    try:
        _require_pymupdf()
        print("✓ pdf input (pymupdf)")
    except SystemExit:
        print("  pdf input — optional: pip install pymupdf (or use .meta.json sidecar)")
    if _which("soffice") or _which("libreoffice"):
        print("✓ LibreOffice (direct pptx↔pdf)")
    else:
        print("  LibreOffice optional for direct pptx↔pdf")
    if any_source_available():
        print("✓ Stock photo source configured")
    else:
        print(f"  {stock_setup_hint('compose_slides')}")
    cfg = load_config()
    print(f"  Slide size: {cfg.width}x{cfg.height}")
    return 0 if ok else 1


def cmd_parse(args: argparse.Namespace) -> int:
    argv = nl_to_argv(" ".join(args.text))
    if not argv:
        return 1
    print(" ".join(shlex.quote(a) for a in argv))
    return 0


def cmd_compose(args: argparse.Namespace) -> int:
    scenes: list[Scene] = []
    topic = extract_slides_topic((args.topic or "").strip()) or normalize_topic((args.topic or "").strip())

    if args.script:
        raw = Path(args.script).expanduser().read_text(encoding="utf-8") if Path(args.script).is_file() else args.script
        scenes = _enrich_scenes(_parse_scenes_json(raw))
        if not topic and scenes:
            topic = scenes[0].title

    if not scenes and topic:
        mode = _script_mode(args)
        if mode == "llm":
            if args.scenes is not None:
                print(f"Writing script with LLM ({args.scenes} slides) …", file=sys.stderr)
            else:
                print("Writing script with LLM (auto slide count) …", file=sys.stderr)
            try:
                scenes = _llm_script(topic, scenes=args.scenes)
                if _script_needs_shortening(scenes):
                    print("Script too dense — summarizing …", file=sys.stderr)
                    scenes = _llm_summarize_script(topic, scenes)
                if args.scenes is None:
                    print(f"  LLM chose {len(scenes)} slides", file=sys.stderr)
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

    if _llm_available() and any(not s.image_keywords for s in scenes):
        print("Choosing stock photo keywords with LLM …", file=sys.stderr)
        scenes = _llm_enrich_image_keywords(topic, scenes)

    label = topic_label(topic)
    print(f"Topic: {label}", file=sys.stderr)
    try:
        formats = parse_formats_arg(args.format)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 1
    primary_fmt = formats[0]
    out = (
        Path(args.output).expanduser()
        if args.output
        else _default_output(topic, primary_fmt if len(formats) == 1 else "pptx")
    )
    fmt_label = ", ".join(formats)
    print(f"Composing {len(scenes)} slides ({fmt_label}) → {out}", file=sys.stderr)
    saved = compose(scenes, output=out, topic=topic, formats=formats)
    for path in saved:
        print(f"Saved slides: {path}")
    meta = out.with_suffix(".meta.json")
    if meta.is_file():
        print(f"Metadata: {meta}")
    elif "json" in {p.suffix.lstrip(".") for p in saved}:
        json_out = next(p for p in saved if p.suffix == ".json")
        print(f"Metadata: {json_out}")
    if _env("OPEN_SLIDES", "1") not in {"0", "false"}:
        _open_slides(saved[0])
    return 0


def _format_from_output_path(output: Path) -> str | None:
    ext = output.suffix.lstrip(".").lower()
    return normalize_format(ext) or None


def cmd_convert(args: argparse.Namespace) -> int:
    input_path = Path(args.input).expanduser()
    output_arg = Path(args.output).expanduser() if args.output else None

    fmt_raw = args.format
    if fmt_raw in {None, "", "auto"} and output_arg and output_arg.suffix:
        detected = _format_from_output_path(output_arg)
        if detected:
            fmt_raw = detected

    try:
        formats = parse_formats_arg(fmt_raw)
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 1

    if output_arg:
        output = output_arg
    else:
        stem = input_path.with_suffix("")
        output = (
            stem.with_suffix(FORMAT_EXTENSIONS[formats[0]])
            if len(formats) == 1
            else stem
        )

    try:
        saved = convert_deck(
            input_path,
            output=output,
            formats=formats,
            from_fmt=args.from_fmt,
        )
    except SystemExit as exc:
        print(exc, file=sys.stderr)
        return 1

    for path in saved:
        print(f"Saved: {path}")
    meta = output.with_suffix(".meta.json")
    if meta.is_file():
        print(f"Metadata: {meta}")
    elif "json" in {p.suffix.lstrip(".") for p in saved}:
        json_out = next(p for p in saved if p.suffix == ".json")
        print(f"Metadata: {json_out}")
    if _env("OPEN_SLIDES", "1") not in {"0", "false"} and saved:
        _open_slides(saved[0])
    return 0


def _open_slides(path: Path) -> None:
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
    if argv[0] not in {"compose", "convert", "parse", "check", "-h", "--help"}:
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
