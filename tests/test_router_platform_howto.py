"""Router and prompt tests for platform-specific app/UI how-to questions."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from arka.agent.platform_howto import answer_platform_howto
from arka.routing.platform_howto import (
    is_platform_howto_question,
    platform_howto_system_prompt,
    platform_web_answer_system_prompt,
)
from arka.router import route


class PlatformHowtoDetectionTests(unittest.TestCase):
    def test_detects_brave_close_window(self) -> None:
        self.assertTrue(is_platform_howto_question("how to close an window on brave"))

    def test_detects_chrome_tab_shortcut(self) -> None:
        self.assertTrue(is_platform_howto_question("how do i close a tab in chrome"))

    def test_rejects_install_questions(self) -> None:
        self.assertFalse(is_platform_howto_question("how to install brave on mac"))

    def test_rejects_gift_advice(self) -> None:
        self.assertFalse(is_platform_howto_question("what to give as a birthday gift"))


class PlatformHowtoPromptTests(unittest.TestCase):
    def test_macos_prompt_mentions_cmd_not_ctrl_only(self) -> None:
        prompt = platform_howto_system_prompt("macos")
        self.assertIn("Cmd", prompt)
        self.assertIn("macOS", prompt)
        self.assertIn("Do NOT mention", prompt)

    def test_macos_web_fallback_prompt_is_platform_specific(self) -> None:
        prompt = platform_web_answer_system_prompt("macos")
        self.assertIn("Cmd+W", prompt)
        self.assertIn("do not list other oses", prompt.lower())


class PlatformHowtoRouterTests(unittest.TestCase):
    def test_routes_brave_close_to_platform_howto(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("how to close an window on brave")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "platform_howto")

    def test_keeps_gift_advice_on_web_answer(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("what to give as a birthday gift")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "web_answer")


class PlatformHowtoAnswerTests(unittest.TestCase):
    def test_macos_answer_mentions_cmd_not_ctrl_only(self) -> None:
        with mock.patch(
            "arka.llm.cli.llm_complete",
            return_value="Press Cmd+W to close the Brave tab, or click the red button top-left.",
        ):
            answer = answer_platform_howto("how to close an window on brave", platform="macos")
        self.assertIn("Cmd", answer)
        self.assertNotRegex(answer, r"\bCtrl\+W\b")


if __name__ == "__main__":
    unittest.main()
