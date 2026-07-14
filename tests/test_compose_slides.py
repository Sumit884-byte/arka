"""Tests for compose_slides — NL parsing and slide deck assembly."""

from __future__ import annotations

import argparse
import io
import json
import zipfile
from pathlib import Path

import pytest

from arka.media.compose_slides import (
    EMU_PER_INCH,
    compose,
    convert_deck,
    detect_format,
    extract_slide_style,
    extract_slides_topic,
    nl_to_argv,
    normalize_format,
    normalize_slide_style,
    parse_formats_arg,
    _pptx_slide_dimensions,
    _prepare_pptx_image_stream,
    _sanitize_ooxml_text,
    _slides_scene_bounds,
    _slides_script_needs_shortening,
    _template_slides_script,
    _validate_pptx_file,
)
from arka.media.compose_video import Scene, load_config


def test_nl_to_argv_slides_about_topic():
    argv = nl_to_argv("make slides about kubernetes networking")
    assert argv == ["compose", "--topic", "kubernetes networking"]


def test_nl_to_argv_arka_slides():
    argv = nl_to_argv("arka slides about Rust memory safety")
    assert argv == ["compose", "--topic", "Rust memory safety"]


def test_nl_to_argv_presentation_on_topic():
    argv = nl_to_argv("presentation on climate change")
    assert argv == ["compose", "--topic", "climate change"]


def test_nl_to_argv_pitch_deck_style():
    argv = nl_to_argv("pitch deck on AI infrastructure")
    assert argv == ["compose", "--topic", "AI infrastructure", "--style", "pitch"]


def test_nl_to_argv_academic_presentation():
    argv = nl_to_argv("academic presentation on quantum computing as md")
    assert argv == [
        "compose",
        "--topic",
        "quantum computing",
        "--format",
        "md",
        "--style",
        "academic",
    ]


def test_normalize_slide_style_defaults_executive():
    assert normalize_slide_style(None) == "executive"
    assert normalize_slide_style("unknown") == "executive"
    assert normalize_slide_style("pitch") == "pitch"


def test_extract_slide_style_from_nl():
    assert extract_slide_style("executive slides about sales") == "executive"
    assert extract_slide_style("style academic presentation") == "academic"


def test_template_slides_script_executive_arc():
    scenes = _template_slides_script("cloud security", style="executive")
    assert 6 <= len(scenes) <= _slides_scene_bounds()[1]
    titles = [scene.title for scene in scenes]
    assert any("priority" in title.lower() or "strategic" in title.lower() for title in titles)
    assert all(scene.narration.strip() for scene in scenes)
    assert all(scene.body.strip() for scene in scenes)


def test_template_slides_script_pitch_has_cta():
    scenes = _template_slides_script("fintech", style="pitch")
    assert any("ask" in scene.title.lower() for scene in scenes)


def test_slides_script_needs_shortening_flags_dense_deck():
    scenes = [
        Scene(title="A" * 80, narration="n", captions=["one", "two", "three", "four", "five"]),
    ]
    assert _slides_script_needs_shortening(scenes)


def test_nl_to_argv_presentation_with_llm():
    argv = nl_to_argv("create presentation on Rust with llm")
    assert argv == ["compose", "--topic", "Rust", "--llm"]


def test_nl_to_argv_pdf_format():
    argv = nl_to_argv("make slides about kubernetes as pdf")
    assert argv == ["compose", "--topic", "kubernetes", "--format", "pdf"]


def test_nl_to_argv_html_presentation():
    argv = nl_to_argv("html presentation on climate change")
    assert argv == ["compose", "--topic", "climate change", "--format", "html"]


def test_nl_to_argv_markdown_slides():
    argv = nl_to_argv("create markdown slides about Python asyncio")
    assert argv == ["compose", "--topic", "Python asyncio", "--format", "md"]


def test_nl_to_argv_ignores_video_requests():
    assert nl_to_argv("make youtube video about ai") == []


def test_extract_slides_topic_strips_trailing_llm():
    assert extract_slides_topic("slides about Python asyncio with llm") == "Python asyncio"


def test_extract_slides_topic_strips_format_suffix():
    assert extract_slides_topic("slides about Rust memory safety as pdf") == "Rust memory safety"


def test_parse_formats_arg_auto_and_all():
    assert parse_formats_arg("auto") == ["pptx"]
    assert parse_formats_arg("all") == ["pptx", "pdf", "html", "md", "json"]


def test_parse_formats_arg_aliases():
    assert parse_formats_arg("markdown,pdf") == ["md", "pdf"]


def test_normalize_format_aliases():
    assert normalize_format("powerpoint") == "pptx"
    assert normalize_format("marp") == "md"


def test_compose_builds_pptx_and_sidecar(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pptx = pytest.importorskip("pptx")
    _ = pptx  # noqa: F841

    monkeypatch.setenv("OPEN_SLIDES", "0")
    scenes = _template_slides_script("testing", style="executive")
    out = tmp_path / "deck.pptx"
    cfg = load_config()
    batch = compose(scenes, output=out, topic="testing", cfg=cfg, formats=["pptx"])
    saved = batch.saved
    assert saved == [out]
    assert out.is_file()
    assert out.stat().st_size > 5000
    sidecar = out.with_suffix(".meta.json")
    assert sidecar.is_file()
    meta = json.loads(sidecar.read_text(encoding="utf-8"))
    assert meta["source"] == "arka-compose-slides"
    assert len(meta["scenes"]) == len(scenes)
    assert meta["outputs"]["pptx"] == str(out)


def test_compose_exports_pdf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pytest.importorskip("PIL")
    monkeypatch.setenv("OPEN_SLIDES", "0")
    monkeypatch.delenv("UNSPLASH_ACCESS_KEY", raising=False)
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)

    scenes = [Scene(title="Hello", narration="Notes.", body="Body copy")]
    out = tmp_path / "deck.pdf"
    batch = compose(scenes, output=out, topic="Hello", cfg=load_config(), formats=["pdf"])
    saved = batch.saved
    assert saved == [out]
    assert out.is_file()
    assert out.stat().st_size > 1000


def test_compose_exports_html(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPEN_SLIDES", "0")

    scenes = [Scene(title="Hello", narration="Notes.", body="Body copy")]
    out = tmp_path / "deck.html"
    batch = compose(scenes, output=out, topic="Hello", cfg=load_config(), formats=["html"])
    saved = batch.saved
    assert saved == [out]
    html = out.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html
    assert "Hello" in html
    assert "data:image/png;base64," in html


def test_compose_exports_markdown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPEN_SLIDES", "0")

    scenes = [Scene(title="Hello", narration="Speaker notes.", body="Short headline")]
    out = tmp_path / "deck.md"
    batch = compose(scenes, output=out, topic="Hello", cfg=load_config(), formats=["md"])
    saved = batch.saved
    assert saved == [out]
    md = out.read_text(encoding="utf-8")
    assert "marp: true" in md
    assert "# Hello" in md
    assert "Speaker notes." in md


def test_compose_exports_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPEN_SLIDES", "0")

    scenes = [Scene(title="Hello", narration="Speaker notes.", body="Short headline")]
    out = tmp_path / "deck.json"
    batch = compose(scenes, output=out, topic="Hello", cfg=load_config(), formats=["json"])
    saved = batch.saved
    assert saved == [out]
    meta = json.loads(out.read_text(encoding="utf-8"))
    assert meta["source"] == "arka-compose-slides"
    assert meta["outputs"]["json"] == str(out)
    assert meta["scenes"][0]["title"] == "Hello"


def test_nl_to_argv_convert_pptx_to_pdf():
    argv = nl_to_argv("convert slides.pptx to pdf")
    assert argv == ["convert", "slides.pptx", "--format", "pdf"]


def test_nl_to_argv_convert_html():
    argv = nl_to_argv("convert deck.html --format markdown")
    assert argv == ["convert", "deck.html", "--format", "md"]


def test_nl_to_argv_convert_all():
    argv = nl_to_argv("convert presentation.pptx to all")
    assert argv == ["convert", "presentation.pptx", "--format", "all"]


def test_detect_format_from_extension():
    assert detect_format(Path("deck.pptx")) == "pptx"
    assert detect_format(Path("notes.markdown")) == "md"


def test_convert_json_to_pptx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pytest.importorskip("pptx")
    monkeypatch.setenv("OPEN_SLIDES", "0")

    scenes = [
        Scene(title="Intro", narration="Welcome.", body="Opening slide"),
        Scene(title="Details", narration="More notes.", body="Main points"),
    ]
    json_path = tmp_path / "deck.json"
    compose(scenes, output=json_path, topic="Demo", cfg=load_config(), formats=["json"])

    out = tmp_path / "converted.pptx"
    batch = convert_deck(json_path, output=out, formats=["pptx"], cfg=load_config())
    saved = batch.saved
    assert saved == [out]
    assert out.is_file()
    assert out.stat().st_size > 3000


def test_convert_pptx_to_html(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pytest.importorskip("pptx")
    monkeypatch.setenv("OPEN_SLIDES", "0")

    scenes = [Scene(title="Hello", narration="Notes.", body="Body copy")]
    pptx_path = tmp_path / "deck.pptx"
    compose(scenes, output=pptx_path, topic="Hello", cfg=load_config(), formats=["pptx"])

    html_path = tmp_path / "deck.html"
    batch = convert_deck(pptx_path, output=html_path, formats=["html"], cfg=load_config())
    saved = batch.saved
    assert saved == [html_path]
    html = html_path.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html
    assert "Hello" in html


def test_convert_markdown_to_html(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPEN_SLIDES", "0")

    md_path = tmp_path / "deck.md"
    md_path.write_text(
        """---
title: Test Deck
marp: true
---

# Slide One

Hello world

---

# Slide Two

More content
""",
        encoding="utf-8",
    )

    html_path = tmp_path / "deck.html"
    batch = convert_deck(md_path, output=html_path, formats=["html"], cfg=load_config())
    saved = batch.saved
    assert saved == [html_path]
    html = html_path.read_text(encoding="utf-8")
    assert "Slide One" in html
    assert "Slide Two" in html


def test_convert_html_to_markdown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPEN_SLIDES", "0")

    scenes = [Scene(title="Hello", narration="Speaker notes.", body="Short headline")]
    html_path = tmp_path / "deck.html"
    compose(scenes, output=html_path, topic="Hello", cfg=load_config(), formats=["html"])

    md_path = tmp_path / "deck.md"
    batch = convert_deck(html_path, output=md_path, formats=["md"], cfg=load_config())
    saved = batch.saved
    assert saved == [md_path]
    md = md_path.read_text(encoding="utf-8")
    assert "# Hello" in md
    assert "Speaker notes." in md


def test_compose_title_only_slide_without_stock_keys(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pytest.importorskip("pptx")
    monkeypatch.delenv("UNSPLASH_ACCESS_KEY", raising=False)
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)
    monkeypatch.setenv("OPEN_SLIDES", "0")

    scenes = [
        Scene(title="Hello", narration="Speaker notes here.", body="Short headline"),
    ]
    out = tmp_path / "title-only.pptx"
    batch = compose(scenes, output=out, topic="Hello", cfg=load_config(), formats=["pptx"])
    saved = batch.saved
    assert saved[0].is_file()
    assert saved[0].stat().st_size > 3000


def test_symbolic_route_compose_slides():
    from arka.routing.symbolic import route_compose_slides

    hit = route_compose_slides("make slides about kubernetes networking")
    assert hit == "compose_slides compose --topic 'kubernetes networking'"
    assert route_compose_slides("make youtube video about ai") is None


def test_symbolic_route_compose_slides_pitch_deck():
    from arka.routing.symbolic import route_compose_slides

    hit = route_compose_slides("pitch deck on AI infrastructure")
    assert hit == "compose_slides compose --topic 'AI infrastructure' --style pitch"


def test_dispatch_split_skill_line_multi_word_topic():
    """Dispatch must preserve quoted multi-word --topic values (fish _agent_dispatch_one)."""
    from arka.dispatch import _split_skill_line

    cases = [
        ("compose_slides compose --topic 'AI infrastructure' --style pitch", [
            "compose_slides",
            "compose",
            "--topic",
            "AI infrastructure",
            "--style",
            "pitch",
        ]),
        ("compose_slides compose --topic 'machine learning' --style pitch", [
            "compose_slides",
            "compose",
            "--topic",
            "machine learning",
            "--style",
            "pitch",
        ]),
        ("compose_slides compose --topic 'cloud native'", [
            "compose_slides",
            "compose",
            "--topic",
            "cloud native",
        ]),
        ("compose_slides compose --topic 'kubernetes networking'", [
            "compose_slides",
            "compose",
            "--topic",
            "kubernetes networking",
        ]),
    ]
    for line, expected in cases:
        assert _split_skill_line(line) == expected, line


def test_nl_to_argv_multi_word_topics():
    """NL parse must keep spaces inside slide topics."""
    assert nl_to_argv("pitch deck on machine learning") == [
        "compose",
        "--topic",
        "machine learning",
        "--style",
        "pitch",
    ]
    assert nl_to_argv("make slides about cloud native") == [
        "compose",
        "--topic",
        "cloud native",
    ]


def test_normalize_compose_argv_inserts_compose_subcommand():
    from arka.media.compose_slides import _normalize_compose_argv

    assert _normalize_compose_argv(["--topic", "AI infrastructure", "--style", "pitch"]) == [
        "compose",
        "--topic",
        "AI infrastructure",
        "--style",
        "pitch",
    ]
    assert _normalize_compose_argv(["compose", "--topic", "Rust"]) == [
        "compose",
        "--topic",
        "Rust",
    ]
    assert _normalize_compose_argv(
        ["--", "compose", "--topic", "AI infrastructure", "--style", "pitch"]
    ) == [
        "compose",
        "--topic",
        "AI infrastructure",
        "--style",
        "pitch",
    ]
    assert _normalize_compose_argv(["pitch deck on AI infrastructure"]) == [
        "compose",
        "--topic",
        "AI infrastructure",
        "--style",
        "pitch",
    ]


def test_main_accepts_compose_flags_without_subcommand(monkeypatch: pytest.MonkeyPatch):
    from arka.media import compose_slides as mod

    captured: list[argparse.Namespace] = []

    def _fake_compose(args: argparse.Namespace) -> int:
        captured.append(args)
        return 0

    monkeypatch.setattr(mod, "cmd_compose", _fake_compose)
    assert mod.main(["--topic", "AI infrastructure", "--style", "pitch"]) == 0
    assert mod.main(["--", "compose", "--topic", "AI infrastructure", "--style", "pitch"]) == 0
    assert [args.topic for args in captured] == ["AI infrastructure", "AI infrastructure"]
    assert len(captured) == 2
    assert all(args.style == "pitch" for args in captured)


def test_pptx_export_valid_ooxml(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pytest.importorskip("pptx")
    monkeypatch.setenv("OPEN_SLIDES", "0")
    monkeypatch.delenv("UNSPLASH_ACCESS_KEY", raising=False)
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)

    scenes = _template_slides_script("valid export", style="executive")[:2]
    out = tmp_path / "deck.pptx"
    batch = compose(scenes, output=out, topic="valid export", cfg=load_config(), formats=["pptx"])
    assert batch.saved == [out]
    assert not batch.failed

    _validate_pptx_file(out)
    with zipfile.ZipFile(out) as zf:
        names = zf.namelist()
        assert "[Content_Types].xml" in names
        assert "ppt/presentation.xml" in names
        assert "_rels/.rels" in names
        assert any(name.startswith("ppt/slides/slide") for name in names)
        assert zf.testzip() is None


def test_keynote_compatible_pptx(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    """PPTX must use standard slide size and pass stricter OOXML checks Keynote expects."""
    pptx = pytest.importorskip("pptx")
    from pptx import Presentation

    _ = pptx  # noqa: F841
    monkeypatch.setenv("OPEN_SLIDES", "0")
    monkeypatch.delenv("UNSPLASH_ACCESS_KEY", raising=False)
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)

    scenes = _template_slides_script("AI infrastructure", style="pitch")
    scenes[0].narration = "Notes with café, résumé, and — em dash."
    out = tmp_path / "keynote-deck.pptx"
    cfg = load_config()
    batch = compose(scenes, output=out, topic="AI infrastructure", cfg=cfg, formats=["pptx"])
    assert batch.saved == [out]
    assert not batch.failed

    _validate_pptx_file(out)

    prs = Presentation(str(out))
    w_in = prs.slide_width / EMU_PER_INCH
    h_in = prs.slide_height / EMU_PER_INCH
    assert 12.5 <= w_in <= 13.5
    assert 7.0 <= h_in <= 8.0
    assert abs((w_in / h_in) - (16 / 9)) < 0.05

    slide_w, slide_h = _pptx_slide_dimensions(cfg)
    assert prs.slide_width == slide_w
    assert prs.slide_height == slide_h

    with zipfile.ZipFile(out) as zf:
        media = [n for n in zf.namelist() if n.startswith("ppt/media/")]
        assert len(media) == len(scenes)
        for name in media:
            data = zf.read(name)
            assert data[:8] == b"\x89PNG\r\n\x1a\n"
            assert b"IEND" in data[-32:]
        assert not any(name.startswith("ppt/notesSlides/") for name in zf.namelist())

    assert _sanitize_ooxml_text(scenes[0].narration) == scenes[0].narration


def test_keynote_pptx_notes_can_be_opted_in(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pytest.importorskip("pptx")
    monkeypatch.setenv("OPEN_SLIDES", "0")
    monkeypatch.setenv("SLIDES_PPTX_NOTES", "1")
    monkeypatch.delenv("UNSPLASH_ACCESS_KEY", raising=False)
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)

    scenes = _template_slides_script("AI infrastructure", style="pitch")[:1]
    out = tmp_path / "keynote-notes.pptx"
    batch = compose(scenes, output=out, topic="AI infrastructure", cfg=load_config(), formats=["pptx"])
    assert batch.saved == [out]
    with zipfile.ZipFile(out) as zf:
        assert any(name.startswith("ppt/notesSlides/") for name in zf.namelist())


def test_prepare_pptx_image_stream_reencodes_rgba(tmp_path: Path):
    pytest.importorskip("PIL")
    from PIL import Image

    src = tmp_path / "rgba.png"
    img = Image.new("RGBA", (32, 32), (10, 20, 30, 128))
    img.save(src, "PNG")

    stream = _prepare_pptx_image_stream(src)
    data = stream.read()
    assert data[:8] == b"\x89PNG\r\n\x1a\n"
    assert b"IEND" in data[-32:]
    with Image.open(io.BytesIO(data)) as out:
        assert out.mode == "RGB"
        assert out.size == (32, 32)


def test_invalid_generation_does_not_write_file(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
):
    pytest.importorskip("pptx")
    monkeypatch.setenv("OPEN_SLIDES", "0")
    monkeypatch.delenv("UNSPLASH_ACCESS_KEY", raising=False)
    monkeypatch.delenv("PEXELS_API_KEY", raising=False)
    monkeypatch.delenv("PIXABAY_API_KEY", raising=False)

    def _reject_pptx(path: Path) -> None:
        raise ValueError("simulated invalid pptx")

    monkeypatch.setattr("arka.media.compose_slides._validate_pptx_file", _reject_pptx)

    scenes = [Scene(title="Broken export", narration="Notes.", body="Headline")]
    out = tmp_path / "broken.pptx"
    batch = compose(scenes, output=out, topic="Broken export", cfg=load_config(), formats=["pptx"])

    assert not out.exists()
    assert not out.with_suffix(".pptx.partial").exists()
    assert batch.failed.get("pptx")
    assert batch.fallback_md is not None
    assert batch.fallback_md.is_file()
    assert batch.fallback_md.suffix == ".md"
    assert "# Broken export" in batch.fallback_md.read_text(encoding="utf-8")
