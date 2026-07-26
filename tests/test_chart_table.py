"""Tests for table-as-image chart rendering."""

from __future__ import annotations

import csv
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arka.charts.plot import nl_to_argv
from arka.charts.table_image import (
    nl_to_table_argv,
    plot_table,
    rows_to_grid,
    table_from_file,
    wants_table_image,
)
from arka.routing.symbolic import route_chart


class TableImageIntentTests(unittest.TestCase):
    def test_wants_table_image(self) -> None:
        self.assertTrue(wants_table_image("render sales.csv as table image"))
        self.assertTrue(wants_table_image("generate table png from metrics.csv"))
        self.assertFalse(wants_table_image("chart bar Apple 1 Samsung 2"))

    def test_nl_to_table_argv(self) -> None:
        argv = nl_to_table_argv('table image from ~/data/sales.csv title "Q1"')
        self.assertEqual(argv[:2], ["table", "~/data/sales.csv"])
        self.assertIn("--title", argv)
        self.assertIn("Q1", argv)

    def test_nl_to_argv_routes_table(self) -> None:
        argv = nl_to_argv("chart table from metrics.csv")
        self.assertEqual(argv[:2], ["table", "metrics.csv"])

    def test_route_chart_table(self) -> None:
        route = route_chart('arka "render metrics.csv as table png"')
        self.assertIsNotNone(route)
        assert route is not None
        self.assertIn("table", route)
        self.assertIn("metrics.csv", route)


class TableImageRenderTests(unittest.TestCase):
    def test_rows_to_grid(self) -> None:
        rows = [{"Name": "Alice", "Age": "30"}, {"Name": "Bob", "Age": "25"}]
        cols, grid = rows_to_grid(rows)
        self.assertEqual(cols, ["Name", "Age"])
        self.assertEqual(grid[0][0], "Alice")

    def test_plot_table_writes_png(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "table.png"
            with mock.patch("arka.charts.plot.open_image"):
                saved = plot_table(
                    ["A", "B"],
                    [["1", "2"], ["3", "4"]],
                    title="Demo",
                    output=out,
                )
            self.assertTrue(saved.is_file())
            self.assertGreater(saved.stat().st_size, 500)

    def test_table_from_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            csv_path = Path(tmp) / "demo.csv"
            with csv_path.open("w", newline="", encoding="utf-8") as fh:
                writer = csv.writer(fh)
                writer.writerow(["Product", "Units"])
                writer.writerow(["Apple", "230"])
                writer.writerow(["Samsung", "210"])
            out = Path(tmp) / "out.png"
            with mock.patch("arka.charts.plot.open_image"):
                saved = table_from_file(csv_path, output=out, title="Phone sales")
            self.assertTrue(saved.is_file())
            self.assertEqual(saved, out.resolve())


if __name__ == "__main__":
    unittest.main()
