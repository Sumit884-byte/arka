"""Tests for chart_from_pdf skill — table extraction, NL parse, routing."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arka.charts.chart_from_pdf import (
    chart_from_pdf,
    nl_to_argv,
    pick_best_table,
    table_to_rows,
)
from arka.charts.tabular import aggregate_rows, resolve_columns, suggest_chart_type
from arka.router import route
from arka.routing.symbolic import route_chart_from_pdf


class ChartFromPdfParseTests(unittest.TestCase):
    def test_nl_with_pdf_path(self) -> None:
        argv = nl_to_argv("chart from pdf report.pdf")
        self.assertEqual(argv, ["report.pdf"])

    def test_nl_with_output_and_type(self) -> None:
        argv = nl_to_argv("plot pie chart from sales.pdf save as out.png")
        self.assertEqual(argv, ["sales.pdf", "-o", "out.png", "--type", "pie"])

    def test_nl_with_columns(self) -> None:
        argv = nl_to_argv("graph pdf table data/report.pdf by category value amount")
        self.assertIn("data/report.pdf", argv)
        self.assertIn("--by", argv)
        self.assertIn("category", argv)
        self.assertIn("--value", argv)
        self.assertIn("amount", argv)

    def test_rejects_unrelated(self) -> None:
        for query in (
            "chart TSLA last 3 months",
            "merge report.pdf",
            "describe video clip.mp4",
            "chart from pdf without path",
        ):
            with self.subTest(query=query):
                self.assertEqual(nl_to_argv(query), [])


class ChartFromPdfTableTests(unittest.TestCase):
    def test_table_to_rows(self) -> None:
        grid = [
            ["Region", "Sales"],
            ["East", "120"],
            ["West", "90"],
        ]
        rows = table_to_rows(grid)
        self.assertEqual(len(rows), 2)
        self.assertEqual(rows[0]["Region"], "East")
        self.assertEqual(rows[0]["Sales"], "120")

    def test_pick_best_table_prefers_numeric(self) -> None:
        tables = [
            [["A", "B"], ["x", "note"]],
            [["Category", "Amount"], ["Phones", "230"], ["Tablets", "110"]],
        ]
        rows = pick_best_table(tables)
        self.assertEqual(rows[0]["Category"], "Phones")

    def test_suggest_chart_type(self) -> None:
        self.assertEqual(suggest_chart_type(["2020", "2021", "2022"], [1, 2, 3]), "line")
        self.assertEqual(suggest_chart_type(["A", "B", "C"], [40, 35, 25]), "pie")
        self.assertEqual(suggest_chart_type(["A", "B", "C", "D"], [1, 2, 3, 4]), "bar")

    def test_resolve_and_aggregate(self) -> None:
        rows = [
            {"category": "Phones", "amount": "230"},
            {"category": "Phones", "amount": "20"},
            {"category": "Tablets", "amount": "110"},
        ]
        label_col, value_col = resolve_columns(rows, by="category", value="amount")
        labels, values = aggregate_rows(rows, label_col, value_col)
        self.assertEqual(labels, ["Phones", "Tablets"])
        self.assertEqual(values, [250.0, 110.0])


class ChartFromPdfRoutingTests(unittest.TestCase):
    def test_symbolic_route(self) -> None:
        routed = route_chart_from_pdf("chart from pdf report.pdf")
        self.assertEqual(routed, "chart_from_pdf report.pdf")

    def test_router_offline(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("chart from pdf report.pdf")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "chart_from_pdf")

    def test_skill_manifest_exists(self) -> None:
        manifest = Path(__file__).parents[1] / "src/arka/skills/chart_from_pdf/skill.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(data["name"], "chart_from_pdf")
        self.assertIn("chart from pdf", data["triggers"])


class ChartFromPdfIntegrationTests(unittest.TestCase):
    def test_chart_from_pdf_with_mocked_tables(self) -> None:
        grid = [["Product", "Units"], ["Apple", "230"], ["Samsung", "210"]]
        with tempfile.TemporaryDirectory() as tmp:
            pdf = Path(tmp) / "report.pdf"
            pdf.write_bytes(b"%PDF-1.4 mock")
            out = Path(tmp) / "chart.png"
            with mock.patch("arka.charts.chart_from_pdf.extract_tables_from_pdf", return_value=[grid]):
                with mock.patch("arka.charts.chart_from_pdf.plot_bar") as plot_bar:
                    plot_bar.return_value = out
                    saved = chart_from_pdf(pdf, output=out, chart_type="bar")
            self.assertEqual(saved, out)
            plot_bar.assert_called_once()


if __name__ == "__main__":
    unittest.main()
