"""Tests for ASCII art skill — NL routing, rendering, and generate_image disambiguation."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from arka.agent.ascii_art import (
    _render_block_fallback,
    image_to_ascii,
    nl_to_argv,
    render_text,
)
from arka.generate.image import nl_to_argv as image_nl_to_argv
from arka.routing.symbolic import route_ascii_art


class TestAsciiNlToArgv(unittest.TestCase):
    def test_make_ascii_art_of(self) -> None:
        self.assertEqual(nl_to_argv("make ascii art of arka"), ["arka"])

    def test_ascii_banner(self) -> None:
        self.assertEqual(nl_to_argv("ascii banner welcome"), ["welcome"])

    def test_figlet(self) -> None:
        self.assertEqual(nl_to_argv("figlet HELLO WORLD"), ["HELLO WORLD"])

    def test_ascii_from_image(self) -> None:
        self.assertEqual(
            nl_to_argv("ascii art from logo.png"),
            ["--from-image", "logo.png"],
        )

    def test_image_to_ascii_phrase(self) -> None:
        self.assertEqual(
            nl_to_argv("convert cat.jpg to ascii"),
            ["--from-image", "cat.jpg"],
        )

    def test_font_in_request(self) -> None:
        self.assertEqual(
            nl_to_argv("ascii banner hello font slant"),
            ["--font", "slant", "hello"],
        )

    def test_not_chart_or_image(self) -> None:
        self.assertEqual(nl_to_argv("chart line AAPL"), [])
        self.assertEqual(nl_to_argv("make an image of a cat"), [])

    def test_route_symbolic(self) -> None:
        hit = route_ascii_art("make ascii art of arka")
        self.assertEqual(hit, "ascii_art arka")


class TestGenerateImageDisambiguation(unittest.TestCase):
    def test_ascii_art_not_generate_image(self) -> None:
        self.assertEqual(image_nl_to_argv("make ascii art of arka"), [])
        self.assertEqual(image_nl_to_argv("ascii banner hello"), [])


class TestAsciiRender(unittest.TestCase):
    def test_block_fallback_nonempty(self) -> None:
        out = _render_block_fallback("HI")
        self.assertIn("#", out)
        self.assertIn("\n", out)

    def test_render_text_uses_fallback_without_figlet(self) -> None:
        with patch("arka.agent.ascii_art._render_pyfiglet", return_value=None), patch(
            "arka.agent.ascii_art._render_system_figlet", return_value=None
        ), patch("arka.agent.ascii_art._render_npx_figlet", return_value=None):
            out = render_text("OK")
        self.assertIn("#", out)

    def test_image_to_ascii(self) -> None:
        try:
            from PIL import Image
        except ImportError:
            self.skipTest("Pillow not installed")

        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "square.png"
            Image.new("L", (4, 4), color=128).save(path)
            out = image_to_ascii(path, width=30)
            lines = out.strip().splitlines()
            self.assertGreaterEqual(len(lines), 1)
            self.assertTrue(all(len(line) == 30 for line in lines))


if __name__ == "__main__":
    unittest.main()
