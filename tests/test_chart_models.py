"""Tests for AI model characteristic charts."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arka.charts.models import (
    ModelPoint,
    benchmark_points,
    choose_chart_kind,
    nl_to_model_chart_argv,
    plot_model_characteristics,
    wants_model_chart,
)
from arka.routing.symbolic import route_chart


class ModelChartIntentTests(unittest.TestCase):
    def test_wants_model_chart(self) -> None:
        self.assertTrue(
            wants_model_chart("chart showing AI model characteristics with data points")
        )
        self.assertTrue(wants_model_chart("scatter plot of model latency vs score"))
        self.assertFalse(wants_model_chart("line chart AAPL last year"))

    def test_nl_to_argv(self) -> None:
        argv = nl_to_model_chart_argv("graph AI model benchmark scatter latency vs score")
        self.assertEqual(argv, ["models", "--type", "scatter"])

    def test_route_chart(self) -> None:
        routed = route_chart("visualize LLM model characteristics as a chart")
        self.assertIsNotNone(routed)
        assert routed is not None
        self.assertIn("models", routed)


class ModelChartPlotTests(unittest.TestCase):
    def test_scatter_writes_png(self) -> None:
        points = [
            ModelPoint("gemini/flash", 0.92, 120.0, 1.0),
            ModelPoint("groq/70b", 0.88, 240.0, 0.95),
            ModelPoint("groq/8b", 0.75, 60.0, 1.0),
        ]
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "models.png"
            saved = plot_model_characteristics(
                points,
                kind="scatter",
                title="Latency vs score",
                output=out,
            )
            self.assertTrue(saved.is_file())
            self.assertGreater(saved.stat().st_size, 1000)

    def test_choose_kind(self) -> None:
        pts = [ModelPoint("a", 0.9, 100, 1.0)]
        self.assertEqual(choose_chart_kind("model size chart", pts), "size_bar")
        self.assertEqual(
            choose_chart_kind("scatter latency vs score", [ModelPoint("a", 0.9, 100, 1.0)]),
            "scatter",
        )

    def test_benchmark_points_mock(self) -> None:
        payload = {
            "suites": {
                "default": {
                    "rankings": {
                        "chat": [
                            {
                                "candidate": "gemini/gemini-2.5-flash",
                                "score": 0.91,
                                "latency_ms": 110,
                                "success_rate": 1.0,
                            }
                        ]
                    }
                }
            }
        }
        with mock.patch("arka.llm.benchmarks.load_results", return_value=payload):
            pts = benchmark_points("chat")
        self.assertEqual(len(pts), 1)
        self.assertAlmostEqual(pts[0].score, 0.91)


if __name__ == "__main__":
    unittest.main()
