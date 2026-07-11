"""Tests for compose_slides — NL parsing and slide deck assembly."""

from __future__ import annotations

import json
from pathlib import Path

import pytest

from arka.media.compose_slides import (
    compose,
    convert_deck,
    detect_format,
    extract_slides_topic,
    nl_to_argv,
    normalize_format,
    parse_formats_arg,
)
from arka.media.compose_video import Scene, _template_script, load_config


def test_nl_to_argv_slides_about_topic():
    argv = nl_to_argv("make slides about kubernetes networking")
    assert argv == ["compose", "--topic", "kubernetes networking"]


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
    scenes = _template_script("testing")
    out = tmp_path / "deck.pptx"
    cfg = load_config()
    saved = compose(scenes, output=out, topic="testing", cfg=cfg, formats=["pptx"])
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
    saved = compose(scenes, output=out, topic="Hello", cfg=load_config(), formats=["pdf"])
    assert saved == [out]
    assert out.is_file()
    assert out.stat().st_size > 1000


def test_compose_exports_html(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPEN_SLIDES", "0")

    scenes = [Scene(title="Hello", narration="Notes.", body="Body copy")]
    out = tmp_path / "deck.html"
    saved = compose(scenes, output=out, topic="Hello", cfg=load_config(), formats=["html"])
    assert saved == [out]
    html = out.read_text(encoding="utf-8")
    assert "<!DOCTYPE html>" in html
    assert "Hello" in html
    assert "data:image/png;base64," in html


def test_compose_exports_markdown(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPEN_SLIDES", "0")

    scenes = [Scene(title="Hello", narration="Speaker notes.", body="Short headline")]
    out = tmp_path / "deck.md"
    saved = compose(scenes, output=out, topic="Hello", cfg=load_config(), formats=["md"])
    assert saved == [out]
    md = out.read_text(encoding="utf-8")
    assert "marp: true" in md
    assert "# Hello" in md
    assert "Speaker notes." in md


def test_compose_exports_json(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    monkeypatch.setenv("OPEN_SLIDES", "0")

    scenes = [Scene(title="Hello", narration="Speaker notes.", body="Short headline")]
    out = tmp_path / "deck.json"
    saved = compose(scenes, output=out, topic="Hello", cfg=load_config(), formats=["json"])
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
    saved = convert_deck(json_path, output=out, formats=["pptx"], cfg=load_config())
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
    saved = convert_deck(pptx_path, output=html_path, formats=["html"], cfg=load_config())
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
    saved = convert_deck(md_path, output=html_path, formats=["html"], cfg=load_config())
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
    saved = convert_deck(html_path, output=md_path, formats=["md"], cfg=load_config())
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
    saved = compose(scenes, output=out, topic="Hello", cfg=load_config(), formats=["pptx"])
    assert saved[0].is_file()
    assert saved[0].stat().st_size > 3000
