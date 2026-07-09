"""Tests for describe_image resize/compress logic."""

from __future__ import annotations

import io
import os
import unittest
from unittest import mock

from PIL import Image

from arka.vision.describe import (
    _auto_backend_order,
    _is_ollama_context_error,
    _max_edge,
    _max_edge_for,
    _resize_image,
)


def _make_png(width: int, height: int, *, color: str = "red") -> bytes:
    img = Image.new("RGB", (width, height), color=color)
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return buf.getvalue()


def _image_size(data: bytes) -> tuple[int, int]:
    with Image.open(io.BytesIO(data)) as img:
        return img.size


class ResizeTests(unittest.TestCase):
    def test_resize_scales_down_large_image(self) -> None:
        raw = _make_png(3000, 2000)
        with mock.patch.dict(os.environ, {"DESCRIBE_IMAGE_MAX_EDGE": "1024"}, clear=False):
            out, mime = _resize_image(raw, "image/png")
        w, h = _image_size(out)
        self.assertEqual(w, 1024)
        self.assertLessEqual(max(w, h), 1024)
        self.assertEqual(mime, "image/jpeg")

    def test_resize_keeps_small_image_dimensions(self) -> None:
        raw = _make_png(400, 300)
        with mock.patch.dict(os.environ, {"DESCRIBE_IMAGE_MAX_EDGE": "1024"}, clear=False):
            out, mime = _resize_image(raw, "image/png")
        self.assertEqual(_image_size(out), (400, 300))
        self.assertEqual(mime, "image/jpeg")

    def test_resize_prefers_jpeg_by_default(self) -> None:
        raw = _make_png(800, 600)
        out, mime = _resize_image(raw, "image/png")
        self.assertEqual(mime, "image/jpeg")
        self.assertTrue(out.startswith(b"\xff\xd8"))

    def test_resize_can_keep_png_when_disabled(self) -> None:
        raw = _make_png(800, 600)
        with mock.patch.dict(os.environ, {"DESCRIBE_IMAGE_FORCE_JPEG": "0"}, clear=False):
            out, mime = _resize_image(raw, "image/png", prefer_jpeg=False)
        self.assertEqual(mime, "image/png")
        self.assertTrue(out.startswith(b"\x89PNG"))

    def test_resize_custom_max_edge(self) -> None:
        raw = _make_png(2000, 1000)
        out, _mime = _resize_image(raw, "image/png", max_edge=512, prefer_jpeg=True)
        self.assertEqual(_image_size(out), (512, 256))

    def test_jpeg_output_uses_jpeg_magic_bytes(self) -> None:
        raw = _make_png(1920, 1080)
        jpeg_out, mime = _resize_image(raw, "image/png", max_edge=1024, prefer_jpeg=True)
        self.assertEqual(mime, "image/jpeg")
        self.assertTrue(jpeg_out.startswith(b"\xff\xd8"))
        self.assertLessEqual(max(_image_size(jpeg_out)), 1024)

    def test_default_max_edge_is_1024(self) -> None:
        with mock.patch.dict(os.environ, {}, clear=True):
            self.assertEqual(_max_edge(), 1024)

    def test_ollama_max_edge_env_override(self) -> None:
        env = {"DESCRIBE_IMAGE_OLLAMA_MAX_EDGE": "768", "DESCRIBE_IMAGE_MAX_EDGE": "1024"}
        with mock.patch.dict(os.environ, env, clear=False):
            self.assertEqual(_max_edge_for("ollama"), 768)
            self.assertEqual(_max_edge_for("vllm"), 1024)


class BackendOrderTests(unittest.TestCase):
    def test_macos_prefers_gemini_when_key_set(self) -> None:
        with (
            mock.patch("arka.vision.describe.platform.system", return_value="Darwin"),
            mock.patch("arka.vision.describe._api_key", return_value="test-key"),
        ):
            self.assertEqual(_auto_backend_order(), ["gemini", "ollama", "vllm"])

    def test_macos_defaults_ollama_without_key(self) -> None:
        with (
            mock.patch("arka.vision.describe.platform.system", return_value="Darwin"),
            mock.patch("arka.vision.describe._api_key", return_value=""),
        ):
            self.assertEqual(_auto_backend_order(), ["ollama", "vllm", "gemini"])


class OllamaContextErrorTests(unittest.TestCase):
    def test_detects_context_overflow(self) -> None:
        detail = "request (5420 tokens) exceeds the available context size (4096 tokens)"
        self.assertTrue(_is_ollama_context_error(detail))

    def test_ignores_unrelated_errors(self) -> None:
        self.assertFalse(_is_ollama_context_error("model not found"))


if __name__ == "__main__":
    unittest.main()
