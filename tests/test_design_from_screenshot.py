"""Tests for screenshot-to-design brief routing."""

from __future__ import annotations

import unittest
from unittest import mock

from arka.agent import design_from_screenshot as ds
from arka.router import route


class DesignFromScreenshotTests(unittest.TestCase):
    def test_parse_request_from_path(self) -> None:
        source, prompt = ds.parse_request("build this from screenshot.png")
        self.assertEqual(source, "screenshot.png")
        self.assertIn("build", prompt.lower())

    def test_route_command(self) -> None:
        self.assertEqual(
            ds.route_command("build this project from screenshot.png"),
            "design_from_screenshot analyze screenshot.png 'build this project from screenshot.png'",
        )

    def test_router_symbolic(self) -> None:
        with mock.patch.dict("os.environ", {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("build this project from screenshot.png")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "design_from_screenshot")

    def test_scaffold_prompt_style(self) -> None:
        self.assertIn("component hierarchy", ds.DESIGN_PROMPT.lower())

    def test_cmd_analyze_uses_describe(self) -> None:
        with mock.patch("arka.agent.design_from_screenshot.describe_source", return_value="ok") as fn:
            ns = type("A", (), {"source": "x.png", "prompt": ["hi"]})()
            self.assertEqual(ds.cmd_analyze(ns), 0)
            fn.assert_called_once()

    def test_build_tool_help(self) -> None:
        out = ds.route_command("recreate a landing page from ui screenshot.png")
        self.assertIn("design_from_screenshot", out)


if __name__ == "__main__":
    unittest.main()
