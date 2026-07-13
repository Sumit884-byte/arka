"""Tests for describe_screen skill — countdown, NL parse, routing."""

from __future__ import annotations

import io
import os
import unittest
from pathlib import Path
from unittest import mock

from arka.router import route
from arka.routing.symbolic import route_describe_screen
from arka.vision.screen import (
    DEFAULT_COUNTDOWN,
    capture_screen,
    is_screen_describe_request,
    nl_to_argv,
    run_countdown,
)


class ScreenParseTests(unittest.TestCase):
    def test_default_prompt_is_person_aware(self) -> None:
        from arka.vision.screen import DEFAULT_PROMPT

        self.assertIn("identify who they are", DEFAULT_PROMPT.lower())

    def test_parses_common_phrases(self) -> None:
        for query in (
            "what is on my screen",
            "what's on my screen",
            "tell me what is on my screen",
            "tell what is on my screen",
            "describe screen",
            "describe my screen",
            "screen",
            "screen describe",
            "look at my screen",
        ):
            with self.subTest(query=query):
                self.assertTrue(is_screen_describe_request(query))
                self.assertEqual(nl_to_argv(query), ["capture"])

    def test_parses_optional_question(self) -> None:
        self.assertEqual(
            nl_to_argv("what is on my screen what app is focused"),
            ["capture", "what app is focused"],
        )

    def test_rejects_unrelated_queries(self) -> None:
        for query in (
            "take a screenshot",
            "what is my screen time today",
            "show me competitions on kaggle",
            "describe photo.jpg",
        ):
            with self.subTest(query=query):
                self.assertFalse(is_screen_describe_request(query))
                self.assertEqual(nl_to_argv(query), [])

    def test_route_describe_screen(self) -> None:
        for query in ("what's on my screen", "describe screen", "tell what is on my screen"):
            with self.subTest(query=query):
                hit = route_describe_screen(query)
                self.assertIsNotNone(hit)
                assert hit is not None
                self.assertEqual(hit.split()[0], "describe_screen")

    def test_router_symbolic_only(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("what is on my screen")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "describe_screen")


class CountdownTests(unittest.TestCase):
    def test_countdown_messages(self) -> None:
        buf = io.StringIO()
        with mock.patch("arka.vision.screen.time.sleep"):
            run_countdown(3, stream=buf)
        lines = [ln for ln in buf.getvalue().splitlines() if ln.strip()]
        self.assertEqual(lines, ["Capturing in 3...", "Capturing in 2...", "Capturing in 1...", "Capturing now..."])

    def test_zero_countdown_skips_messages(self) -> None:
        buf = io.StringIO()
        with mock.patch("arka.vision.screen.time.sleep") as sleep:
            run_countdown(0, stream=buf)
        sleep.assert_not_called()
        self.assertEqual(buf.getvalue(), "")

    def test_default_countdown_is_five(self) -> None:
        self.assertEqual(DEFAULT_COUNTDOWN, 5)


class CaptureTests(unittest.TestCase):
    def test_capture_screen_darwin(self) -> None:
        dest = Path("/tmp/arka-test-screen.png")

        def fake_run(cmd, **kwargs):
            dest.write_bytes(b"png")
            return mock.Mock(returncode=0)

        with (
            mock.patch("arka.vision.screen._host_platform", return_value="macos"),
            mock.patch("arka.vision.screen.shutil.which", return_value="/usr/sbin/screencapture"),
            mock.patch("arka.vision.screen.subprocess.run", side_effect=fake_run),
        ):
            path = capture_screen(dest)
        self.assertEqual(path, dest)
        dest.unlink(missing_ok=True)

    def test_capture_screen_linux(self) -> None:
        dest = Path("/tmp/arka-test-screen-linux.png")

        def fake_run(cmd, **kwargs):
            dest.write_bytes(b"png")
            return mock.Mock(returncode=0)

        with (
            mock.patch("arka.vision.screen._host_platform", return_value="linux"),
            mock.patch("arka.vision.screen.shutil.which", side_effect=lambda name: name),
            mock.patch("arka.vision.screen.subprocess.run", side_effect=fake_run),
        ):
            path = capture_screen(dest)
        self.assertEqual(path, dest)
        dest.unlink(missing_ok=True)

    def test_capture_screen_windows(self) -> None:
        dest = Path("/tmp/arka-test-screen-win.png")

        def fake_run(cmd, **kwargs):
            dest.write_bytes(b"png")
            return mock.Mock(returncode=0)

        with (
            mock.patch("arka.vision.screen._host_platform", return_value="windows"),
            mock.patch(
                "arka.vision.screen.shutil.which",
                side_effect=lambda name: "powershell.exe" if name == "powershell" else None,
            ),
            mock.patch("arka.vision.screen.subprocess.run", side_effect=fake_run),
        ):
            path = capture_screen(dest)
        self.assertEqual(path, dest)
        dest.unlink(missing_ok=True)


if __name__ == "__main__":
    unittest.main()
