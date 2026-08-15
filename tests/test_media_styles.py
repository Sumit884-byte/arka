"""Tests for shared meme/video style presets."""

from __future__ import annotations

import unittest

from arka.media.compose_video import VideoConfig, load_config
from arka.media.media_styles import (
    apply_video_style,
    extract_style_from_text,
    list_meme_styles,
    list_video_styles,
    resolve_meme_style,
    resolve_video_style,
    styled_ai_prompt,
    styled_ai_video_prompt,
    styled_stock_query,
)


class TestMediaStyles(unittest.TestCase):
    def test_catalogs_non_empty(self) -> None:
        self.assertGreaterEqual(len(list_meme_styles()), 8)
        self.assertGreaterEqual(len(list_video_styles()), 8)

    def test_resolve_defaults(self) -> None:
        self.assertEqual(resolve_meme_style(None).name, "classic")
        self.assertEqual(resolve_video_style(None).name, "documentary")

    def test_extract_style_from_nl(self) -> None:
        cleaned, style = extract_style_from_text("make a neon style drake meme")
        self.assertEqual(style, "neon")
        self.assertNotIn("neon style", cleaned.lower())

    def test_styled_stock_query_appends_suffix(self) -> None:
        out = styled_stock_query("developer laptop", "neon", for_meme=True)
        self.assertIn("developer laptop", out)
        self.assertIn("neon", out.lower())

    def test_styled_ai_prompts(self) -> None:
        img = styled_ai_prompt("mountain lake", "cinematic")
        vid = styled_ai_video_prompt("drone over forest", "tech")
        self.assertIn("mountain lake", img)
        self.assertIn("cinematic", img.lower())
        self.assertIn("drone over forest", vid)
        self.assertIn("tech", vid.lower())

    def test_apply_video_style_overrides_config(self) -> None:
        cfg = VideoConfig()
        styled = apply_video_style(cfg, "neon")
        self.assertEqual(styled.visual_style, "neon")
        self.assertNotEqual(styled.bg_color, cfg.bg_color)
        self.assertGreater(styled.title_size, 0)

    def test_load_config_applies_style(self) -> None:
        cfg = load_config(style="minimal")
        self.assertEqual(cfg.visual_style, "minimal")
        self.assertEqual(cfg.bg_color, resolve_video_style("minimal").bg_color)


if __name__ == "__main__":
    unittest.main()
