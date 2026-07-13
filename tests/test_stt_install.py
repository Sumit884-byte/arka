"""Tests for Whisper STT install routing and setup."""

from __future__ import annotations

import os
import shutil
import unittest
from unittest import mock

from arka.agent.stt_install import (
    is_stt_install_request,
    parse_whisper_model,
    route_command,
)
from arka.fish_bridge import fish_route_preview
from arka.paths import bundled_dir
from arka.routing.symbolic import route_stt_install


def _fish_available() -> bool:
    return shutil.which("fish") is not None


class TestSttInstallParsing(unittest.TestCase):
    def test_parse_large_v3_spaced(self) -> None:
        self.assertEqual(parse_whisper_model("install whisper large v3 stt"), "large-v3")

    def test_parse_large_v3_hyphen(self) -> None:
        self.assertEqual(parse_whisper_model("install whisper large-v3"), "large-v3")

    def test_parse_small(self) -> None:
        self.assertEqual(parse_whisper_model("setup whisper small for stt"), "small")

    def test_default_model(self) -> None:
        self.assertEqual(parse_whisper_model("install whisper for speech to text"), "large-v3")


class TestSttInstallDetection(unittest.TestCase):
    def test_install_whisper_large_v3_stt(self) -> None:
        self.assertTrue(is_stt_install_request("install whisper large v3 stt"))

    def test_install_whisper_for_speech_to_text(self) -> None:
        self.assertTrue(is_stt_install_request("install whisper large v3 for speech to text"))

    def test_not_install_fish(self) -> None:
        self.assertFalse(is_stt_install_request("install fish"))

    def test_route_command(self) -> None:
        self.assertEqual(route_command("install whisper large v3 stt"), "install_stt large-v3")

    def test_route_symbolic(self) -> None:
        self.assertEqual(route_stt_install("install whisper large v3 stt"), "install_stt large-v3")


@unittest.skipUnless(_fish_available(), "fish shell not installed")
class TestSttInstallFishRouting(unittest.TestCase):
    def setUp(self) -> None:
        self._env = {
            "INSTALL_HOME": str(bundled_dir()),
            "PLATFORM": "macos",
            "ROUTE_MODE": "ai_only",
        }

    def _preview(self, query: str):
        with mock.patch.dict(os.environ, self._env, clear=False):
            return fish_route_preview(query)

    def test_ai_only_routes_to_install_stt_not_install_app(self) -> None:
        preview = self._preview("install whisper large v3 stt")
        self.assertIsNotNone(preview)
        assert preview is not None
        self.assertEqual(preview.action, "install_stt large-v3")
        self.assertEqual(preview.kind, "skill")
        self.assertIn("Whisper", preview.why)

    def test_speech_to_text_variant(self) -> None:
        preview = self._preview("install whisper large v3 for speech to text")
        self.assertIsNotNone(preview)
        assert preview is not None
        self.assertEqual(preview.action, "install_stt large-v3")


class TestSttInstallExecution(unittest.TestCase):
    def test_install_invokes_setup_local(self) -> None:
        from arka.agent import stt_install

        with mock.patch("arka.media.transcript.cmd_setup_local", return_value=0) as setup:
            code = stt_install.cmd_install(["large-v3"])
        self.assertEqual(code, 0)
        setup.assert_called_once()
        self.assertEqual(setup.call_args[0][0].model, "large-v3")


if __name__ == "__main__":
    unittest.main()
