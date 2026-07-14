"""Router tests for gift/life-advice questions (must not route to agent_ask)."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from arka.router import route


class RouterGiftAdviceTests(unittest.TestCase):
    def test_routes_birthday_gift_to_web_answer(self) -> None:
        for query in (
            "what to give as an birthday gift",
            "what to give as a birthday gift",
            "birthday gift ideas for my friend",
            "what should i give my mom for christmas",
        ):
            with self.subTest(query=query):
                with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
                    result = route(query)
                self.assertIsNotNone(result)
                assert result is not None
                self.assertEqual(result.skill.split()[0], "web_answer")

    def test_keeps_system_advice_on_agent_path(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("is my cpu too outdated for gaming")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "agent_ask")

    def test_keeps_system_advice_in_ai_only_mode(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "ai_only"}, clear=False):
            result = route("is my cpu too outdated for gaming")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "agent_ask")


if __name__ == "__main__":
    unittest.main()
