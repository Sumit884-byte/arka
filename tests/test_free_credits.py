"""Tests for free credits guide routing and output."""

from __future__ import annotations

import io
import os
import shutil
import unittest
from unittest import mock

from arka.agent.free_credits import (
    is_free_credits_request,
    route_command,
    run_guide,
)
from arka.fish_bridge import fish_route_preview
from arka.paths import bundled_dir
from arka.routing.symbolic import route_free_credits


def _fish_available() -> bool:
    return shutil.which("fish") is not None


class TestFreeCreditsDetection(unittest.TestCase):
    def test_how_to_get_free_ai_credits(self) -> None:
        self.assertTrue(is_free_credits_request("how to get free ai credits"))

    def test_maximize_free_credits(self) -> None:
        self.assertTrue(is_free_credits_request("maximize free credits"))

    def test_free_tier_setup(self) -> None:
        self.assertTrue(is_free_credits_request("free tier setup"))

    def test_use_arka_without_paying(self) -> None:
        self.assertTrue(is_free_credits_request("how to use arka without paying"))

    def test_learn_free_ai_providers(self) -> None:
        self.assertTrue(is_free_credits_request("learn free ai providers"))

    def test_not_unrelated_free(self) -> None:
        self.assertFalse(is_free_credits_request("free shipping on shoes"))

    def test_route_command(self) -> None:
        self.assertEqual(route_command("maximize free credits"), "free_credits")

    def test_route_symbolic(self) -> None:
        self.assertEqual(route_free_credits("arka free tier setup"), "free_credits")


@unittest.skipUnless(_fish_available(), "fish shell not installed")
class TestFreeCreditsFishRouting(unittest.TestCase):
    def setUp(self) -> None:
        self._env = {
            "INSTALL_HOME": str(bundled_dir()),
            "PLATFORM": "macos",
            "ROUTE_MODE": "ai_only",
        }

    def _preview(self, query: str):
        with mock.patch.dict(os.environ, self._env, clear=False):
            return fish_route_preview(query)

    def test_ai_only_routes_to_free_credits(self) -> None:
        preview = self._preview("how to get free ai credits")
        self.assertIsNotNone(preview)
        assert preview is not None
        self.assertEqual(preview.action, "free_credits")
        self.assertEqual(preview.kind, "skill")


class TestFreeCreditsOutput(unittest.TestCase):
    def test_run_guide_smoke(self) -> None:
        buf = io.StringIO()
        code = run_guide(stream=buf)
        self.assertEqual(code, 0)
        text = buf.getvalue()
        self.assertIn("Free AI credits", text)
        self.assertIn("ROUTE_MODE", text)
        self.assertIn("GEMINI_API_KEY", text)
        self.assertIn("Your providers", text)
        self.assertIn("arka doctor", text)


if __name__ == "__main__":
    unittest.main()
