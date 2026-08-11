"""Tests for unified future prediction engine."""

from __future__ import annotations

import unittest
from unittest import mock

from arka.predict.domains import detect_domain, extract_location
from arka.predict.engine import nl_to_future_argv, run_future
from arka.routing.symbolic import route_future_predict


class DomainTests(unittest.TestCase):
    def test_detect_rainfall_isro(self) -> None:
        self.assertEqual(detect_domain("ISRO rainfall forecast for Mumbai next 2 weeks"), "rainfall")
        self.assertEqual(detect_domain("monsoon rain in Pune next month"), "rainfall")

    def test_detect_weather(self) -> None:
        self.assertEqual(detect_domain("weather forecast for Delhi next 7 days"), "weather")

    def test_detect_stock(self) -> None:
        self.assertEqual(detect_domain("predict AAPL stock price next month"), "stock")

    def test_detect_satellite(self) -> None:
        self.assertEqual(detect_domain("ISS pass over Bangalore"), "satellite")

    def test_extract_location(self) -> None:
        self.assertIn("Mumbai", extract_location("rainfall in Mumbai next 2 weeks"))


class RoutingTests(unittest.TestCase):
    def test_nl_future_argv_rainfall(self) -> None:
        argv = nl_to_future_argv("predict monsoon rainfall in Mumbai next 14 days")
        self.assertIsNotNone(argv)
        assert argv is not None
        self.assertEqual(argv[0], "future")
        self.assertIn("--domain", argv)
        self.assertIn("rainfall", argv)

    def test_route_future_predict(self) -> None:
        routed = route_future_predict("forecast rainfall in Chennai next week")
        self.assertIsNotNone(routed)
        assert routed is not None
        self.assertTrue(routed.startswith("predict future"))


class EngineTests(unittest.TestCase):
    def test_run_future_rainfall_mock(self) -> None:
        from arka.charts.prediction import ForecastSeries
        from datetime import datetime, timezone, timedelta

        base = datetime(2025, 6, 1, tzinfo=timezone.utc)
        hist = [base + timedelta(days=i) for i in range(10)]
        vals = [float(i) for i in range(10)]
        fut = [base + timedelta(days=10 + i) for i in range(5)]
        fvals = [5.0, 6.0, 7.0, 4.0, 3.0]
        fc = ForecastSeries(
            label="Mumbai Rainfall",
            hist_dates=hist,
            hist_values=vals,
            forecast_dates=fut,
            forecast_values=fvals,
            band_low=[v - 1 for v in fvals],
            band_high=[v + 1 for v in fvals],
            prob_up=0.6,
            signal="WET",
            method="test",
            currency="mm",
        )
        with mock.patch(
            "arka.predict.providers.weather.build_weather_forecast",
            return_value=fc,
        ), mock.patch(
            "arka.predict.providers.weather.format_weather_text",
            return_value="7-day forecast text",
        ), mock.patch(
            "arka.predict.providers.isro.isro_rainfall_context",
            return_value="ISRO context",
        ), mock.patch("arka.charts.prediction.plot_prediction_chart") as plot, mock.patch(
            "arka.charts.plot.open_image"
        ):
            from pathlib import Path

            plot.return_value = Path("/tmp/rain.png")
            result = run_future(
                "rainfall in Mumbai next week",
                domain="rainfall",
                days=7,
                chart=True,
            )
        self.assertEqual(result.domain, "rainfall")
        self.assertIn("ISRO context", result.text)
        self.assertIsNotNone(result.chart_path)


if __name__ == "__main__":
    unittest.main()
