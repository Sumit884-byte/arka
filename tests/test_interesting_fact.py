"""Routing and NL parsing tests for interesting_fact / trivia skill."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from arka.agent.interesting_fact import answer_interesting_fact
from arka.routing.interesting_fact import (
    extract_topic,
    is_interesting_fact_request,
    interesting_fact_system_prompt,
)
from arka.router import route


class InterestingFactDetectionTests(unittest.TestCase):
    def test_detects_tell_something_interesting(self) -> None:
        self.assertTrue(is_interesting_fact_request("tell me something interesting"))

    def test_detects_do_tell_something_interesting(self) -> None:
        self.assertTrue(is_interesting_fact_request("do tell something interesting"))

    def test_detects_fun_fact(self) -> None:
        self.assertTrue(is_interesting_fact_request("give me a fun fact"))

    def test_detects_random_fact(self) -> None:
        self.assertTrue(is_interesting_fact_request("random fact"))

    def test_detects_topic_phrase(self) -> None:
        self.assertTrue(is_interesting_fact_request("something cool about space"))

    def test_rejects_factual_lookup(self) -> None:
        self.assertFalse(is_interesting_fact_request("tell me about Tokyo"))

    def test_rejects_weather(self) -> None:
        self.assertFalse(is_interesting_fact_request("tell me something interesting about the weather"))


class InterestingFactTopicTests(unittest.TestCase):
    def test_extracts_biology_topic(self) -> None:
        self.assertEqual(
            extract_topic("something interesting about biology"),
            "biology",
        )

    def test_extracts_space_topic(self) -> None:
        self.assertEqual(
            extract_topic("tell me something cool about space"),
            "space",
        )

    def test_no_topic_for_generic_request(self) -> None:
        self.assertIsNone(extract_topic("do tell something interesting"))


class InterestingFactRouterTests(unittest.TestCase):
    def test_routes_do_tell_to_interesting_fact(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("do tell something interesting")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "interesting_fact")

    def test_routes_topic_request_to_interesting_fact(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("something cool about space")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "interesting_fact")

    def test_keeps_factual_lookup_on_web_answer(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("tell me about Tokyo")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "web_answer")


class InterestingFactAnswerTests(unittest.TestCase):
    def test_prompt_is_lightweight(self) -> None:
        prompt = interesting_fact_system_prompt()
        self.assertIn("2-4", prompt)
        self.assertIn("interesting fact", prompt.lower())

    def test_answer_uses_llm(self) -> None:
        with mock.patch(
            "arka.llm.cli.llm_complete",
            return_value="Octopuses have three hearts and blue blood.",
        ):
            answer = answer_interesting_fact("do tell something interesting")
        self.assertIn("hearts", answer)


if __name__ == "__main__":
    unittest.main()
