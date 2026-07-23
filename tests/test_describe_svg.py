"""Tests for SVG handling in describe_image."""

from __future__ import annotations

import io
import unittest
from pathlib import Path
from unittest import mock

from PIL import Image

from arka.vision.describe import (
    _extract_svg_text,
    _is_svg,
    _prepare_image_bytes,
    load_image_bytes,
)

SVG_FIXTURE = Path(__file__).resolve().parents[1] / "visuals" / "space-tech-vs-engineering.svg"


def _make_png(width: int, height: int) -> bytes:
    img = Image.new("RGB", (width, height), color="blue")
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


class SvgDescribeTests(unittest.TestCase):
    def test_is_svg_detects_extension_and_markup(self) -> None:
        raw = b'<svg xmlns="http://www.w3.org/2000/svg"><text>Hi</text></svg>'
        self.assertTrue(_is_svg(raw, "image/svg+xml"))
        self.assertTrue(_is_svg(raw, ""))

    def test_extract_svg_text_from_fixture(self) -> None:
        raw = SVG_FIXTURE.read_bytes()
        text = _extract_svg_text(raw)
        self.assertIn("Space technology versus engineering", text)
        self.assertIn("SPACE TECHNOLOGY", text)
        self.assertIn("VISION → DESIGN → VERIFY → OPERATE", text)

    def test_prepare_image_bytes_uses_raster_when_available(self) -> None:
        raw = SVG_FIXTURE.read_bytes()
        png = _make_png(1200, 800)
        with mock.patch("arka.vision.describe._svg_to_png", return_value=png):
            out, mime, svg_text = _prepare_image_bytes(raw, "image/svg+xml")
        self.assertIsNone(svg_text)
        self.assertEqual(mime, "image/jpeg")
        with Image.open(io.BytesIO(out)) as img:
            self.assertGreater(img.size[0], 0)

    def test_prepare_image_bytes_falls_back_to_text(self) -> None:
        raw = SVG_FIXTURE.read_bytes()
        with mock.patch("arka.vision.describe._svg_to_png", return_value=None):
            out, mime, svg_text = _prepare_image_bytes(raw, "image/svg+xml")
        self.assertEqual(mime, "image/svg+xml")
        self.assertEqual(out, raw)
        self.assertIn("ENGINEERING", svg_text or "")

    def test_load_image_bytes_local_svg_without_unidentified_image_error(self) -> None:
        with mock.patch("arka.vision.describe._svg_to_png", return_value=None):
            data, mime, label, svg_text = load_image_bytes(str(SVG_FIXTURE))
        self.assertEqual(label, SVG_FIXTURE.name)
        self.assertEqual(mime, "image/svg+xml")
        self.assertIn("SPACE TECH", svg_text or "")


if __name__ == "__main__":
    unittest.main()
