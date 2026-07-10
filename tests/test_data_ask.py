"""Tests for data_ask skill."""

from __future__ import annotations

import json
import os
import unittest
from pathlib import Path
from unittest import mock

from arka.agent import data_ask as da
from arka.router import route
from arka.routing.symbolic import route_data_ask

FIXTURES = Path(__file__).resolve().parent / "fixtures"


class DataAskTests(unittest.TestCase):
    def test_wants_data_ask(self) -> None:
        self.assertTrue(da.wants_data_ask("data_ask users.csv how many rows?"))
        self.assertTrue(da.wants_data_ask("ask about sales.json total revenue by category"))
        self.assertTrue(da.wants_data_ask("summarize this csv data/products.csv"))
        self.assertTrue(da.wants_data_ask("analyze data report.jsonl"))
        self.assertFalse(da.wants_data_ask("generate 100 users as csv"))
        self.assertFalse(da.wants_data_ask("create sample json data"))
        self.assertFalse(da.wants_data_ask("how many files in this folder"))

    def test_route_command(self) -> None:
        self.assertEqual(
            da.route_command("data_ask users.csv how many rows?"),
            "data_ask users.csv 'how many rows?'",
        )
        self.assertEqual(
            da.route_command("query_data sales.json what is total revenue by category?"),
            "data_ask sales.json 'what is total revenue by category?'",
        )
        self.assertEqual(
            da.route_command("analyze data report.jsonl"),
            "data_ask report.jsonl",
        )

    def test_load_csv(self) -> None:
        loaded = da.load_data(FIXTURES / "users.csv")
        self.assertEqual(loaded.row_count, 5)
        self.assertIn("name", loaded.columns)
        self.assertEqual(len(loaded.rows), 5)

    def test_load_json(self) -> None:
        loaded = da.load_data(FIXTURES / "sales.json")
        self.assertEqual(loaded.row_count, 5)
        self.assertIn("category", loaded.columns)
        self.assertEqual(loaded.rows[0]["category"], "Electronics")

    def test_build_context(self) -> None:
        loaded = da.load_data(FIXTURES / "users.csv")
        context = da.build_context(loaded)
        self.assertIn("Rows: 5", context)
        self.assertIn("salary", context)
        self.assertIn("Sample rows", context)

    def test_column_stats_numeric(self) -> None:
        loaded = da.load_data(FIXTURES / "users.csv")
        stats = da.column_stats(loaded.rows, loaded.columns)
        self.assertEqual(stats["salary"]["type"], "numeric")
        self.assertGreater(stats["salary"]["max"], stats["salary"]["min"])

    def test_missing_file(self) -> None:
        with self.assertRaises(FileNotFoundError):
            da.load_data(FIXTURES / "missing.csv")

    def test_answer_question_mock_llm(self) -> None:
        with mock.patch("arka.llm.cli.llm_complete", return_value="There are 5 rows."):
            answer = da.answer_question(FIXTURES / "users.csv", "how many rows?")
        self.assertIn("5 rows", answer)

    def test_route_symbolic(self) -> None:
        hit = route_data_ask("ask data users.csv how many rows?")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertTrue(hit.startswith("data_ask"))

    def test_router_symbolic(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("summarize sales.json total revenue by category")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "data_ask")

    def test_cli_main(self) -> None:
        with mock.patch("arka.llm.cli.llm_complete", return_value="5 rows"):
            code = da.main([str(FIXTURES / "users.csv"), "how many rows?"])
        self.assertEqual(code, 0)


if __name__ == "__main__":
    unittest.main()
