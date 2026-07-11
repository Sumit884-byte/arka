"""Table-driven NL routing coverage for recently added skills."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from arka.router import route
from arka.routing.symbolic import route_offline_extras


NL_CASES: tuple[tuple[str, str], ...] = (
    ("generate 50 users as csv", "generate_data"),
    ("generate real world bank gdp india as csv", "generate_data"),
    ("generate 20 pubmed papers on mRNA vaccines as csv", "generate_data"),
    ("ask data in reports folder", "data_ask"),
    ("analyze csv files in data/", "data_ask"),
    ("list mcp servers", "mcp"),
    ("save bookmark https://example.com", "bookmarks"),
    ("check repo health", "repo_health"),
    ("show docker containers", "docker_status"),
    ("show clipboard history", "clipboard_history"),
    ("select best model", "select_model"),
    ("make ascii art of hello", "ascii_art"),
    ("life sciences list", "life_sciences"),
    ("post linkedin on x", "post_x"),
    ("search kaggle competitions", "competitions"),
    ("teach route X to Y", "route_learn"),
    ("today's tech brief", "daily_brief"),
    ("kalshi predictions on bitcoin", "kalshi"),
    ("download kaggle dataset heptapod/titanic", "kaggle"),
    ("how to close window on brave", "platform_howto"),
    ("gemini explain asyncio", "gemini_cli"),
    ("fugu explain TLS", "fugu"),
)


class SymbolicExtrasRoutingTests(unittest.TestCase):
    def test_offline_extras_map_priority_phrases(self) -> None:
        for phrase, expected_skill in NL_CASES:
            with self.subTest(phrase=phrase, expected=expected_skill):
                hit = route_offline_extras(phrase)
                self.assertIsNotNone(hit, msg=f"no symbolic route for {phrase!r}")
                assert hit is not None
                self.assertEqual(hit.split()[0], expected_skill)


class RouterSymbolicOnlyTests(unittest.TestCase):
    def test_router_symbolic_only_priority_phrases(self) -> None:
        for phrase, expected_skill in NL_CASES:
            with self.subTest(phrase=phrase, expected=expected_skill):
                with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
                    result = route(phrase)
                self.assertIsNotNone(result, msg=f"no route for {phrase!r}")
                assert result is not None
                self.assertEqual(
                    result.skill.split()[0],
                    expected_skill,
                    msg=f"{phrase!r} -> {result.skill!r}",
                )


if __name__ == "__main__":
    unittest.main()
