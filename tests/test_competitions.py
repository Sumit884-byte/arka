"""Tests for competitions search skill."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from arka.agent import competitions as comp
from arka.router import route


class CompetitionsParseTests(unittest.TestCase):
    def test_wants_competitions_search(self) -> None:
        for query in (
            "show me competitions available on kaggle",
            "search hackathons for signoz",
            "find ml contests on devpost",
            "competitions sources",
            "list competition data sources",
        ):
            with self.subTest(query=query):
                self.assertTrue(comp.wants_competitions_search(query))

    def test_rejects_stock_competition(self) -> None:
        self.assertFalse(comp.wants_competitions_search("stock competition peers AAPL"))

    def test_detect_sources(self) -> None:
        self.assertEqual(
            comp.detect_sources("show me kaggle and devpost hackathons"),
            ["kaggle", "devpost"],
        )

    def test_extract_search_query(self) -> None:
        self.assertEqual(
            comp.extract_search_query("show me competitions available on kaggle"),
            "available",
        )
        self.assertEqual(
            comp.extract_search_query("search hackathons for signoz observability"),
            "signoz observability",
        )

    def test_route_kaggle_query(self) -> None:
        route_cmd = comp.route_command("show me competitions available on kaggle")
        self.assertEqual(
            route_cmd,
            "competitions search available --source kaggle",
        )

    def test_route_sources_list(self) -> None:
        self.assertEqual(
            comp.route_command("list competition data sources"),
            "competitions sources",
        )

    def test_list_sources_text(self) -> None:
        text = comp.list_sources_text()
        self.assertIn("Kaggle", text)
        self.assertIn("Devpost", text)
        self.assertIn("competitions search", text)


class CompetitionsRouterTests(unittest.TestCase):
    def test_routes_kaggle_competitions_to_competitions_skill(self) -> None:
        for query in (
            "show me competitions available on kaggle",
            "show me competetions available on kaggle",
        ):
            with self.subTest(query=query):
                with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
                    result = route(query)
                self.assertIsNotNone(result)
                assert result is not None
                self.assertEqual(result.skill.split()[0], "competitions")
                self.assertIn("kaggle", result.skill.lower())


if __name__ == "__main__":
    unittest.main()
