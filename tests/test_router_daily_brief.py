"""Router tests for daily/tech brief phrases (must not route to web_answer)."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from arka.router import route
from arka.routing.symbolic import route_daily_brief


class RouteDailyBriefSymbolicTests(unittest.TestCase):
    def test_route_daily_brief_matches_tech_phrases(self) -> None:
        for query in (
            "today's tech brief personalized for me",
            "tech brief personalized for me",
            "morning tech brief",
            "daily tech brief",
            "daily brief",
            "morning brief",
            "news brief",
            "today's brief",
            "personalized tech brief",
        ):
            with self.subTest(query=query):
                self.assertEqual(route_daily_brief(query), "daily_brief")

    def test_route_daily_brief_skips_unrelated_brief(self) -> None:
        for query in (
            "give me a brief summary of kubernetes",
            "brief me on quantum computing",
        ):
            with self.subTest(query=query):
                self.assertIsNone(route_daily_brief(query))


class RouterDailyBriefTests(unittest.TestCase):
    def test_symbolic_only_routes_tech_brief_to_daily_brief(self) -> None:
        for query in (
            "today's tech brief personalized for me",
            "tech brief personalized for me",
            "morning tech brief",
            "daily tech brief",
        ):
            with self.subTest(query=query):
                with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
                    result = route(query)
                self.assertIsNotNone(result)
                assert result is not None
                self.assertEqual(result.skill.split()[0], "daily_brief")
                self.assertNotEqual(result.skill.split()[0], "web_answer")

    def test_fish_route_preview_tech_brief(self) -> None:
        try:
            from arka.fish_bridge import fish_route_preview
        except ImportError:
            self.skipTest("fish_bridge unavailable")
        if fish_route_preview is None:
            self.skipTest("fish not installed")
        preview = fish_route_preview("today's tech brief personalized for me")
        if preview is None:
            self.skipTest("fish/config unavailable")
        self.assertEqual(preview.action.split()[0], "daily_brief")
        self.assertNotEqual(preview.action.split()[0], "web_answer")


if __name__ == "__main__":
    unittest.main()
