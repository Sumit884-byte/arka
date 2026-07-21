"""Tests for treemap skill — data loading, layout, NL parse, routing."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arka.charts.tabular import load_rows, resolve_columns, aggregate_rows
from arka.charts.treemap import _layout_treemap, nl_to_argv, plot_treemap, treemap_from_file
from arka.router import route
from arka.routing.symbolic import route_treemap


class TreemapParseTests(unittest.TestCase):
    def test_nl_with_csv(self) -> None:
        argv = nl_to_argv("generate treemap from sales.csv")
        self.assertEqual(argv, ["sales.csv"])

    def test_nl_with_options(self) -> None:
        argv = nl_to_argv(
            "create treemap from data/revenue.json by category value amount save as tree.png"
        )
        self.assertEqual(
            argv,
            ["data/revenue.json", "-o", "tree.png", "--by", "category", "--value", "amount"],
        )

    def test_rejects_unrelated(self) -> None:
        for query in (
            "chart bar Apple:230,Samsung:210",
            "view_data sales.csv",
            "generate treemap without file",
        ):
            with self.subTest(query=query):
                self.assertEqual(nl_to_argv(query), [])


class TreemapDataTests(unittest.TestCase):
    def test_load_csv(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sales.csv"
            path.write_text("category,amount\nPhones,230\nTablets,110\n", encoding="utf-8")
            rows = load_rows(path)
            self.assertEqual(len(rows), 2)
            label_col, value_col = resolve_columns(rows, by="category", value="amount")
            labels, values = aggregate_rows(rows, label_col, value_col)
            self.assertEqual(labels, ["Phones", "Tablets"])
            self.assertEqual(values, [230.0, 110.0])

    def test_layout_covers_unit_square(self) -> None:
        rects = _layout_treemap([3, 2, 1], 0.0, 0.0, 1.0, 1.0)
        self.assertEqual(len(rects), 3)
        area = sum(w * h for _x, _y, w, h in rects)
        self.assertAlmostEqual(area, 1.0, places=5)


class TreemapRoutingTests(unittest.TestCase):
    def test_symbolic_route(self) -> None:
        routed = route_treemap("generate treemap from sales.csv")
        self.assertEqual(routed, "treemap sales.csv")

    def test_router_offline(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("generate treemap from sales.csv")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "treemap")

    def test_skill_manifest_exists(self) -> None:
        manifest = Path(__file__).parents[1] / "src/arka/skills/treemap/skill.json"
        data = json.loads(manifest.read_text(encoding="utf-8"))
        self.assertEqual(data["name"], "treemap")
        self.assertIn("generate treemap", data["triggers"])


class TreemapIntegrationTests(unittest.TestCase):
    def test_treemap_from_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sales.csv"
            path.write_text("category,amount\nA,40\nB,35\nC,25\n", encoding="utf-8")
            out = Path(tmp) / "treemap.png"
            with mock.patch("arka.charts.treemap.plot_treemap") as plot_treemap_mock:
                plot_treemap_mock.return_value = out
                saved = treemap_from_file(path, output=out, by="category", value="amount")
            self.assertEqual(saved, out)
            plot_treemap_mock.assert_called_once()

    def test_plot_treemap_writes_file(self) -> None:
        try:
            import matplotlib  # noqa: F401
        except ImportError:
            self.skipTest("matplotlib not installed")
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "tree.png"
            saved = plot_treemap(["A", "B", "C"], [40, 35, 25], title="Test", output=out)
            self.assertTrue(saved.is_file())
            self.assertGreater(saved.stat().st_size, 100)


if __name__ == "__main__":
    unittest.main()
