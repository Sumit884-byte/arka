"""Tests for just-ai mode (plain LLM chat, no routing/skills)."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from arka.core.just_ai import enable_just_ai, is_just_ai


class JustAiEnvTests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("JUST_AI", None)

    def test_default_is_off(self) -> None:
        self.assertFalse(is_just_ai())

    def test_truthy_values(self) -> None:
        for val in ("1", "true", "yes", "on", "enabled"):
            with self.subTest(val=val):
                os.environ["JUST_AI"] = val
                self.assertTrue(is_just_ai())

    def test_enable_just_ai(self) -> None:
        enable_just_ai()
        self.assertTrue(is_just_ai())
        self.assertEqual(os.environ.get("JUST_AI"), "1")


class JustAiRouterTests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("JUST_AI", None)

    def test_route_returns_none_when_just_ai(self) -> None:
        from arka.router import route

        enable_just_ai()
        self.assertIsNone(route("calc 2+2"))
        self.assertIsNone(route("download playlist"))


class JustAiExecuteTests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("JUST_AI", None)

    def test_execute_request_skips_routing(self) -> None:
        from arka.cli import _execute_request

        enable_just_ai()
        with mock.patch("arka.router.route") as route_mock:
            with mock.patch("arka.skills.run_chat_ask", return_value=0) as ask_mock:
                code = _execute_request("calc 2+2")
        self.assertEqual(code, 0)
        route_mock.assert_not_called()
        ask_mock.assert_called_once_with("calc 2+2")

    def test_cli_flag_enables_just_ai(self) -> None:
        from arka.cli import _strip_just_ai_flag

        args, enabled = _strip_just_ai_flag(["--just-ai", "what", "is", "rust?"])
        self.assertTrue(enabled)
        self.assertEqual(args, ["what", "is", "rust?"])

    def test_cli_short_flag(self) -> None:
        from arka.cli import _strip_just_ai_flag

        args, enabled = _strip_just_ai_flag(["-J", "hello"])
        self.assertTrue(enabled)
        self.assertEqual(args, ["hello"])


class JustAiMcpTests(unittest.TestCase):
    def tearDown(self) -> None:
        os.environ.pop("JUST_AI", None)

    def test_mcp_disables_all_but_arka_ask(self) -> None:
        from arka.integrations.mcp_server import _build_tools, _mcp_disabled_tools

        enable_just_ai()
        disabled = _mcp_disabled_tools()
        tool_names = {tool.name for tool in _build_tools()}
        self.assertIn("arka_ask", tool_names)
        self.assertNotIn("arka_ask", disabled)
        self.assertIn("arka_route", disabled)
        self.assertIn("arka_skill", disabled)

    def test_arka_route_delegates_to_ask(self) -> None:
        from arka.integrations import mcp_server

        enable_just_ai()
        with mock.patch.object(mcp_server, "_handle_arka_ask", return_value="[llm]\nhello") as ask_mock:
            result = mcp_server._handle_arka_route({"prompt": "hi"})
        self.assertEqual(result, "[llm]\nhello")
        ask_mock.assert_called_once()


class JustAiRemoteTests(unittest.TestCase):
    def test_run_just_ai_remote(self) -> None:
        from arka.integrations.remote_server import run_just_ai_remote

        with mock.patch(
            "arka.agent.chat.answer_question",
            return_value=("llm", "plain answer"),
        ):
            output, speak, code = run_just_ai_remote("what is python?")
        self.assertEqual(code, 0)
        self.assertIn("plain answer", output)
        self.assertIn("llm", output)


if __name__ == "__main__":
    unittest.main()
