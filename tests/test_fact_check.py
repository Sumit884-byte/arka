"""Tests for Arka fact_check skill — NL routing, parsing, and synthesis."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from arka.agent.fact_check import (
    _is_fact_check_request,
    fact_check,
    format_fact_check_terminal,
    nl_to_argv,
)
from arka.routing.symbolic import route_fact_check


class TestFactCheckNlToArgv(unittest.TestCase):
    def test_fact_check_command(self) -> None:
        self.assertEqual(
            nl_to_argv('fact check "There are 9 planets in the solar system"'),
            ["There are 9 planets in the solar system"],
        )

    def test_factcheck_one_word(self) -> None:
        self.assertEqual(
            nl_to_argv("factcheck Python was created in 1991"),
            ["Python was created in 1991"],
        )

    def test_verify_claim(self) -> None:
        self.assertEqual(
            nl_to_argv('verify "Bitcoin hit $100k in 2024"'),
            ["Bitcoin hit $100k in 2024"],
        )

    def test_is_it_true_that(self) -> None:
        self.assertEqual(
            nl_to_argv("is it true that the earth is flat"),
            ["the earth is flat"],
        )

    def test_direct_skill_name(self) -> None:
        self.assertEqual(
            nl_to_argv("fact_check the moon is made of cheese"),
            ["the moon is made of cheese"],
        )

    def test_not_verify_url(self) -> None:
        self.assertEqual(nl_to_argv("verify url https://example.com"), [])

    def test_not_generic_question(self) -> None:
        self.assertEqual(nl_to_argv("what is the capital of France"), [])

    def test_route_symbolic(self) -> None:
        hit = route_fact_check("fact check the earth is flat")
        self.assertEqual(hit, "fact_check 'the earth is flat'")


class TestFactCheckDetection(unittest.TestCase):
    def test_is_fact_check_request_true(self) -> None:
        self.assertTrue(_is_fact_check_request("fact check climate change is real"))
        self.assertTrue(_is_fact_check_request("is it true that water boils at 100C"))

    def test_is_fact_check_request_false(self) -> None:
        self.assertFalse(_is_fact_check_request("verify my email address"))
        self.assertFalse(_is_fact_check_request("how many planets are there"))


class TestFactCheckFormatting(unittest.TestCase):
    def test_format_sections(self) -> None:
        raw = "## Verdict\nTRUE\n\n## Summary\nIt is true.\n\n## Evidence\n- Source says so"
        out = format_fact_check_terminal(raw)
        self.assertIn("▸ Verdict", out)
        self.assertIn("▸ Summary", out)
        self.assertIn("▸ Evidence", out)


class TestFactCheckRun(unittest.TestCase):
    def test_offline_no_evidence(self) -> None:
        with patch("arka.agent.fact_check._gather_evidence", return_value=("", [])):
            code = fact_check("test claim")
        self.assertEqual(code, 1)

    def test_fact_check_calls_llm(self) -> None:
        evidence = "[Web search results]\nPluto is a dwarf planet."
        with patch("arka.agent.fact_check._gather_evidence", return_value=(evidence, ["web search"])):
            with patch(
                "arka.agent.fact_check._llm_fact_check",
                return_value="## Verdict\nFALSE\n\n## Summary\nThere are 8 planets.",
            ) as mock_llm:
                code = fact_check("There are 9 planets in the solar system")
        self.assertEqual(code, 0)
        mock_llm.assert_called_once()
        user = mock_llm.call_args[0][1]
        self.assertIn("There are 9 planets", user)
        self.assertIn(evidence, user)


if __name__ == "__main__":
    unittest.main()
