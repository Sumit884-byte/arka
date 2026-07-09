"""Tests for describe_image OCR text-map visibility (debug-only by default)."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from arka.vision.describe import _format_two_layer_output
from arka.vision.ocr import OcrBlock


_SAMPLE_BLOCKS = (
    OcrBlock(text="©", x_pct=1.4, y_pct=5.4, conf=66),
    OcrBlock(text="(970", x_pct=85.6, y_pct=5.4, conf=63),
)


class DescribeImageOcrOutputTests(unittest.TestCase):
    def _format(self, **kwargs: object) -> str:
        defaults = {
            "chart_facts": None,
            "ocr_text": "© (970",
            "ocr_engine": "tesseract",
            "ocr_blocks": _SAMPLE_BLOCKS,
            "vision_text": "A desktop with a browser window open.",
            "vision_backend": "gemini",
        }
        defaults.update(kwargs)
        return _format_two_layer_output(**defaults)  # type: ignore[arg-type]

    def test_text_map_hidden_by_default(self) -> None:
        env = {
            k: v
            for k, v in os.environ.items()
            if k not in {"DESCRIBE_IMAGE_DEBUG", "ARKA_DEBUG", "DESCRIBE_IMAGE_SHOW_OCR"}
        }
        with mock.patch.dict(os.environ, env, clear=True):
            out = self._format()
        self.assertNotIn("Text map", out)
        self.assertNotIn("x%, y% = center of word", out)
        self.assertIn("Description", out)
        self.assertIn("browser window", out)

    def test_text_map_shown_with_describe_image_debug(self) -> None:
        with mock.patch.dict(os.environ, {"DESCRIBE_IMAGE_DEBUG": "1"}, clear=False):
            out = self._format()
        self.assertIn("Text map", out)
        self.assertIn('(1.4, 5.4) "©"', out)

    def test_text_map_shown_with_arka_debug(self) -> None:
        with mock.patch.dict(os.environ, {"ARKA_DEBUG": "1"}, clear=False):
            out = self._format()
        self.assertIn("Text map", out)

    def test_text_map_shown_with_show_ocr_flag(self) -> None:
        with mock.patch.dict(os.environ, {"DESCRIBE_IMAGE_SHOW_OCR": "1"}, clear=False):
            out = self._format()
        self.assertIn("Text map", out)


if __name__ == "__main__":
    unittest.main()
