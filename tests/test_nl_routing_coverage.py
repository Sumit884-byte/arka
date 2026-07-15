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
    ("view colored csv pubmed_sample.csv", "view_data"),
    ("show csv papers.csv as json", "view_data"),
    ("display table data.tsv formats csv,yaml", "view_data"),
    ("list mcp servers", "mcp"),
    ("list arka mcp tools", "mcp"),
    ("show agent heartbeat", "heartbeat"),
    ("validate json package.json", "jsonkit"),
    ("save bookmark https://example.com", "bookmarks"),
    ("check repo health", "repo_health"),
    ("show docker containers", "docker_status"),
    ("show clipboard history", "clipboard_history"),
    ("select best model", "select_model"),
    ("set preferred provider to openrouter", "provider"),
    ("what models are available on groq", "provider"),
    ("list llm providers", "provider"),
    ("make ascii art of hello", "ascii_art"),
    ("fact check the earth is flat", "fact_check"),
    ('verify "Bitcoin hit $100k in 2024"', "fact_check"),
    ("is it true that Python was created in 1991", "fact_check"),
    ("give me a flow for setting up python venv", "flow"),
    ("steps to run a PCR protocol", "flow"),
    ("how does photosynthesis work", "flow"),
    ("explain DNA replication steps", "flow"),
    ("life sciences list", "life_sciences"),
    ("what is Betelgeuse", "astronomy"),
    ("moon phase tonight", "astronomy"),
    ("properties of steel 304", "metallurgy"),
    ("heat treatment steps for aluminum", "metallurgy"),
    ("post linkedin on x", "post_x"),
    ("search kaggle competitions", "competitions"),
    ("teach route X to Y", "route_learn"),
    ("today's tech brief", "daily_brief"),
    ("kalshi predictions on bitcoin", "kalshi"),
    ("download kaggle dataset heptapod/titanic", "kaggle"),
    ("how to close window on brave", "platform_howto"),
    ("gemini explain asyncio", "gemini_cli"),
    ("ask primekg about diabetes", "harvard_ark"),
    ("harvard ark list graphs", "harvard_ark"),
    ("fugu explain TLS", "fugu"),
    ("improve arka", "self_improve"),
    ("self improve add tests", "self_improve"),
    ("loop self fix failing tests", "self_improve"),
    ("improve arka llm fallback", "self_improve"),
    ("self improve routing", "self_improve"),
    ("babysit this pr", "pr_check"),
    ("fix ci until green", "pr_check"),
    ("explain ci failure", "pr_check"),
    ("build this project from screenshot.png", "design_from_screenshot"),
    ("turn this screenshot into a web app", "design_from_screenshot"),
    ("recreate the UI from screenshot", "design_from_screenshot"),
    ("review this frontend and retry 3 loops", "frontend_loop"),
    ("inspect this UI screenshot and rebuild for 2 loops", "frontend_loop"),
    ("repair broken links in this file", "urlkit"),
    ("lint this repo", "lint_project"),
    ("lint this project --full", "lint_project"),
    ("arka ci", "ci"),
    ("arka ci --full", "ci"),
    ("arka ci --fix", "ci"),
    ("review staged", "review"),
    ("review vs main", "review"),
    ("route audit", "route_audit"),
    ("skill new my_tool --template dev", "skill"),
    ("make slides about kubernetes networking", "compose_slides"),
    ("arka slides about Rust memory safety", "compose_slides"),
    ("pitch deck on AI infrastructure", "compose_slides"),
    ("create a 3d model of a gear", "compose_3d"),
    ("create an 3d model of an boy", "compose_3d"),
    ("create a 3d model of a boy", "compose_3d"),
    ("make 3d vase 10cm tall", "compose_3d"),
    ("generate stl for phone stand", "compose_3d"),
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

    def test_symbolic_only_prefers_python_over_fish_llm(self) -> None:
        """Cursor-style offline gate: symbolic extras beat fish LLM fallbacks."""
        from arka.router import Route

        fake_fish = Route("python3 -c 'print(1)'", source="llm", kind="llm")
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            with mock.patch("arka.router._route_via_fish", return_value=fake_fish):
                result = route("view colored csv pubmed_sample.csv")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "view_data")
        self.assertEqual(result.source, "offline")


if __name__ == "__main__":
    unittest.main()
