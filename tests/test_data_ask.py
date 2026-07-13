"""Tests for data_ask skill."""

from __future__ import annotations

import os
import unittest
from pathlib import Path
from unittest import mock

from arka.agent import data_ask as da
from arka.router import route
from arka.routing.symbolic import route_data_ask

FIXTURES = Path(__file__).resolve().parent / "fixtures"
DATA_FOLDER = FIXTURES / "data_folder"


class DataAskTests(unittest.TestCase):
    def test_wants_data_ask(self) -> None:
        self.assertTrue(da.wants_data_ask("data_ask users.csv how many rows?"))
        self.assertTrue(da.wants_data_ask("ask about sales.json total revenue by category"))
        self.assertTrue(da.wants_data_ask("summarize this csv data/products.csv"))
        self.assertTrue(da.wants_data_ask("analyze data report.jsonl"))
        self.assertTrue(da.wants_data_ask("data_ask reports/ summarize all files"))
        self.assertTrue(da.wants_data_ask("analyze csv files in data/ top 10 products"))
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
        self.assertEqual(
            da.route_command("data_ask ./data/ --format csv average salary?"),
            "data_ask ./data --format csv --question 'average salary?'",
        )
        self.assertEqual(
            da.route_command("analyze csv files in data/ top 10 products"),
            "data_ask data --format csv --question 'top 10 products'",
        )

    def test_discover_data_files_single_file(self) -> None:
        files = da.discover_data_files(FIXTURES / "users.csv")
        self.assertEqual(files, [FIXTURES / "users.csv"])

    def test_discover_data_files_folder(self) -> None:
        files = da.discover_data_files(DATA_FOLDER)
        names = {f.name for f in files}
        self.assertEqual(names, {"team.csv", "notes.json"})

    def test_discover_data_files_format_filter(self) -> None:
        files = da.discover_data_files(DATA_FOLDER, formats=["csv"])
        self.assertEqual([f.name for f in files], ["team.csv"])

    def test_load_data_sources_folder(self) -> None:
        datasets, skipped = da.load_data_sources(DATA_FOLDER)
        self.assertEqual(len(datasets), 2)
        self.assertEqual(skipped, 0)
        names = {d.path.name for d in datasets}
        self.assertEqual(names, {"team.csv", "notes.json"})

    def test_build_multi_context(self) -> None:
        datasets, _ = da.load_data_sources(DATA_FOLDER)
        context = da.build_multi_context(datasets, source_path=DATA_FOLDER)
        self.assertIn("Files loaded: 2", context)
        self.assertIn("team.csv", context)
        self.assertIn("notes.json", context)

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

    def test_answer_question_folder_mock_llm(self) -> None:
        with mock.patch("arka.llm.cli.llm_complete", return_value="Two files loaded."):
            answer = da.answer_question(DATA_FOLDER, "summarize all files")
        self.assertIn("Two files", answer)

    def test_answer_question_format_filter_mock_llm(self) -> None:
        with mock.patch("arka.llm.cli.llm_complete", return_value="CSV only."):
            answer = da.answer_question(DATA_FOLDER, "list columns", formats="csv")
        self.assertIn("CSV", answer)

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
