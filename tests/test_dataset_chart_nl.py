"""Tests for flexible dataset chart NL axis parsing."""

from __future__ import annotations

import unittest

from arka.charts.dataset_nl import parse_dataset_axes, wants_dataset_file_chart
from arka.charts.plot import nl_to_argv
from arka.routing.symbolic import route_chart


class DatasetAxesParseTests(unittest.TestCase):
    def test_time_vs_income(self) -> None:
        axes = parse_dataset_axes("present time vs income from income.csv")
        self.assertIsNotNone(axes)
        assert axes is not None
        self.assertEqual(axes.by, "time")
        self.assertEqual(axes.value, "income")
        self.assertEqual(axes.chart_type, "line")

    def test_income_over_time(self) -> None:
        axes = parse_dataset_axes("plot monthly_income over reporting_date from ~/data/pay.csv")
        self.assertIsNotNone(axes)
        assert axes is not None
        self.assertEqual(axes.by, "reporting_date")
        self.assertEqual(axes.value, "monthly_income")
        self.assertEqual(axes.chart_type, "line")

    def test_income_vs_time_flips_temporal(self) -> None:
        axes = parse_dataset_axes("show income vs time from payroll.csv")
        self.assertIsNotNone(axes)
        assert axes is not None
        self.assertEqual(axes.by, "time")
        self.assertEqual(axes.value, "income")

    def test_by_value_generic_columns(self) -> None:
        axes = parse_dataset_axes("chart from sales.csv by region value revenue")
        self.assertIsNotNone(axes)
        assert axes is not None
        self.assertEqual(axes.by, "region")
        self.assertEqual(axes.value, "revenue")

    def test_columns_and_pair(self) -> None:
        axes = parse_dataset_axes("visualize data.csv with tenure and salary")
        self.assertIsNotNone(axes)
        assert axes is not None
        self.assertEqual(axes.by, "tenure")
        self.assertEqual(axes.value, "salary")

    def test_scatter_hint(self) -> None:
        axes = parse_dataset_axes("scatter height vs weight from athletes.json")
        self.assertIsNotNone(axes)
        assert axes is not None
        self.assertEqual(axes.chart_type, "scatter")

    def test_no_hardcoded_loss_epoch(self) -> None:
        axes = parse_dataset_axes("chart training_loss over epoch from metrics.csv")
        self.assertIsNotNone(axes)
        assert axes is not None
        self.assertEqual(axes.by, "epoch")
        self.assertEqual(axes.value, "training_loss")


class DatasetChartRouteTests(unittest.TestCase):
    def test_nl_to_argv_present_phrase(self) -> None:
        argv = nl_to_argv("present time vs income from income.csv")
        self.assertEqual(argv[:2], ["from", "income.csv"])
        self.assertIn("--by", argv)
        self.assertIn("time", argv)
        self.assertIn("--value", argv)
        self.assertIn("income", argv)

    def test_route_chart_without_chart_keyword(self) -> None:
        route = route_chart("present time vs income from income.csv")
        self.assertIsNotNone(route)
        assert route is not None
        self.assertIn("chart from", route)
        self.assertIn("--by", route)
        self.assertIn("time", route)

    def test_wants_dataset_file_chart(self) -> None:
        self.assertTrue(wants_dataset_file_chart("present time vs income from income.csv"))
        self.assertFalse(wants_dataset_file_chart("how many rows in income.csv"))

    def test_table_test_path_does_not_hijack_line_chart(self) -> None:
        phrase = "present time vs income from recordings/table-test/income.csv -o out.png"
        argv = nl_to_argv(phrase)
        self.assertEqual(argv[:2], ["from", "recordings/table-test/income.csv"])
        self.assertIn("--by", argv)
        self.assertIn("time", argv)
        self.assertNotEqual(argv[0], "table")


if __name__ == "__main__":
    unittest.main()
