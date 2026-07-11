"""Tests for convert_media — detection, NL parsing, and conversions."""

from __future__ import annotations

import json
import struct
import zlib
from pathlib import Path
from unittest import mock

import pytest

from arka.media.convert_media import (
    convert_image,
    convert_media,
    detect_media_type,
    nl_to_argv,
    parse_target_formats,
)
from arka.routing.symbolic import route_convert_media


def _png_bytes(width: int = 8, height: int = 8, rgb: tuple[int, int, int] = (255, 0, 0)) -> bytes:
    r, g, b = rgb
    raw = b"".join(b"\x00" + bytes([r, g, b]) * width for _ in range(height))
    compressed = zlib.compress(raw, 9)
    def chunk(tag: bytes, data: bytes) -> bytes:
        return struct.pack(">I", len(data)) + tag + data + struct.pack(">I", zlib.crc32(tag + data) & 0xFFFFFFFF)

    ihdr = struct.pack(">IIBBBBB", width, height, 8, 2, 0, 0, 0)
    return b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", ihdr) + chunk(b"IDAT", compressed) + chunk(b"IEND", b"")


def test_detect_media_type_by_extension(tmp_path: Path):
    png = tmp_path / "photo.png"
    png.write_bytes(_png_bytes())
    assert detect_media_type(png) == "image"
    assert detect_media_type(tmp_path / "clip.mp4") == "video"
    assert detect_media_type(tmp_path / "song.mp3") == "audio"
    assert detect_media_type(tmp_path / "deck.pptx") == "slides"


def test_detect_media_type_magic_bytes(tmp_path: Path):
    mystery = tmp_path / "upload.bin"
    mystery.write_bytes(_png_bytes())
    assert detect_media_type(mystery) == "image"


def test_parse_target_formats_image():
    assert parse_target_formats("webp", "image") == ["webp"]
    assert "png" in parse_target_formats("all", "image")


def test_nl_to_argv_image_and_video():
    assert nl_to_argv("convert photo.png to webp") == ["photo.png", "--to", "webp"]
    assert nl_to_argv("convert video.mp4 to gif") == ["video.mp4", "--to", "gif"]
    assert nl_to_argv("convert deck.pptx to pdf") == ["deck.pptx", "--to", "pdf"]


def test_nl_to_argv_ignores_currency():
    assert nl_to_argv("convert 100 USD to INR") == []


def test_route_convert_media():
    hit = route_convert_media("convert image.png to webp")
    assert hit == "convert_media image.png --to webp"


def test_convert_image_png_to_webp_and_jpg(tmp_path: Path):
    pytest.importorskip("PIL")
    src = tmp_path / "in.png"
    src.write_bytes(_png_bytes())
    webp = convert_image(src, tmp_path / "out.webp", target_format="webp")
    jpg = convert_image(src, tmp_path / "out.jpg", target_format="jpg", quality=80)
    assert webp.is_file() and webp.stat().st_size > 0
    assert jpg.is_file() and jpg.stat().st_size > 0


def test_convert_image_resize(tmp_path: Path):
    pytest.importorskip("PIL")
    src = tmp_path / "in.png"
    src.write_bytes(_png_bytes(32, 16))
    out = convert_image(src, tmp_path / "small.png", target_format="png", width=16)
    from PIL import Image

    img = Image.open(out)
    assert img.width == 16
    assert img.height == 8


def test_convert_video_mocked_ffmpeg(tmp_path: Path):
    src = tmp_path / "clip.mp4"
    src.write_bytes(b"\x00\x00\x00\x18ftypmp42")
    out = tmp_path / "out.gif"

    def fake_run(cmd, capture_output=True, text=True, check=False):
        assert "ffmpeg" in cmd[0] or cmd[0] == "ffmpeg"
        out.write_bytes(b"GIF89a")
        return mock.Mock(returncode=0, stdout="", stderr="")

    with mock.patch("arka.media.convert_media._which", return_value="ffmpeg"), mock.patch(
        "arka.media.convert_media.subprocess.run", side_effect=fake_run
    ):
        saved = convert_media(src, target_formats=["gif"], output=out)
    assert saved == [out]
    assert out.is_file()


def test_convert_slides_json_to_pdf(tmp_path: Path, monkeypatch: pytest.MonkeyPatch):
    pytest.importorskip("PIL")
    meta = {
        "topic": "Demo",
        "scenes": [
            {
                "title": "Intro",
                "narration": "Hello world",
                "body": "Welcome",
                "captions": ["Welcome"],
            }
        ],
    }
    src = tmp_path / "deck.json"
    src.write_text(json.dumps(meta), encoding="utf-8")
    monkeypatch.setenv("OPEN_SLIDES", "0")
    with mock.patch("arka.media.compose_slides._render_scene_png") as render:
        slide_png = tmp_path / "slide.png"
        slide_png.write_bytes(_png_bytes())
        render.return_value = slide_png
        saved = convert_media(src, target_formats=["pdf"], output=tmp_path / "out.pdf")
    assert saved[0].suffix == ".pdf"
    assert saved[0].stat().st_size > 0


def test_cmd_check_runs():
    from arka.media.convert_media import cmd_check
    import argparse

    code = cmd_check(argparse.Namespace())
    assert code in {0, 1}
