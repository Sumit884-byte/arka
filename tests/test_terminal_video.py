"""Tests for terminal_video skill — NL parse and routing."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from arka.router import route
from arka.routing.symbolic import route_terminal_video
from arka.media.terminal_video import nl_to_argv


class TerminalVideoParseTests(unittest.TestCase):
    def test_build_intent(self) -> None:
        cases = {
            "create a terminal demo video": ["build"],
            "make an animated cli screencast": ["build"],
            "generate terminal recording mp4": ["build"],
            "build arka demo video to demo.mp4": ["build", "-o", "demo.mp4"],
        }
        for query, expected in cases.items():
            with self.subTest(query=query):
                self.assertEqual(nl_to_argv(query), expected)

    def test_capture_intent(self) -> None:
        self.assertEqual(nl_to_argv("capture terminal output for video"), ["capture"])

    def test_export_images_intent(self) -> None:
        self.assertEqual(nl_to_argv("export cli screenshots as jpg"), ["export-images"])

    def test_rejects_unrelated(self) -> None:
        for query in (
            "compose video about python",
            "describe video clip.mp4",
            "transcribe meeting.mp4",
        ):
            with self.subTest(query=query):
                self.assertEqual(nl_to_argv(query), [])


class TerminalVideoRoutingTests(unittest.TestCase):
    def test_symbolic_route(self) -> None:
        routed = route_terminal_video("create a terminal demo video")
        self.assertEqual(routed, "terminal_video build")

    def test_router_offline(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("create a terminal demo video")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "terminal_video")


if __name__ == "__main__":
    unittest.main()
