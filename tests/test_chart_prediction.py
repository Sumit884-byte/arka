"""Tests for prediction charts and exchange ticker parsing."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arka.charts.prediction import (
    build_forecast,
    extract_prediction_tickers,
    nl_to_predict_argv,
    parse_forecast_days,
    plot_prediction_chart,
    wants_prediction_chart,
    ForecastSeries,
)
from arka.charts.plot import extract_tickers, nl_to_argv
from arka.routing.symbolic import route_chart


class PredictionIntentTests(unittest.TestCase):
    def test_wants_prediction_chart(self) -> None:
        self.assertTrue(wants_prediction_chart("predict AAPL stock price chart"))
        self.assertTrue(wants_prediction_chart("forecast chart for NVDA next 30 days"))
        self.assertTrue(wants_prediction_chart("chart prediction RELIANCE.NS"))
        self.assertFalse(wants_prediction_chart("line chart AAPL last year"))

    def test_parse_forecast_days(self) -> None:
        self.assertEqual(parse_forecast_days("next 14 days"), 14)
        self.assertEqual(parse_forecast_days("forecast next week"), 7)
        self.assertEqual(parse_forecast_days("for 2 months"), 60)

    def test_nl_to_predict_argv(self) -> None:
        argv = nl_to_predict_argv("predict AAPL stock price chart for 14 days")
        self.assertEqual(argv[:2], ["predict", "AAPL"])
        self.assertIn("--days", argv)
        self.assertIn("14", argv)

    def test_nl_routes_via_plot(self) -> None:
        argv = nl_to_argv("chart prediction RELIANCE.NS for 30 days")
        self.assertEqual(argv[0], "predict")
        self.assertIn("RELIANCE.NS", argv)

    def test_route_chart_prediction(self) -> None:
        routed = route_chart("forecast chart for TSLA next month")
        self.assertIsNotNone(routed)
        assert routed is not None
        self.assertIn("predict", routed)
        self.assertIn("TSLA", routed)


class ExchangeTickerTests(unittest.TestCase):
    def test_long_nse_ticker(self) -> None:
        self.assertEqual(extract_tickers("RELIANCE.NS"), ["RELIANCE.NS"])
        self.assertEqual(extract_tickers("chart RELIANCE.NS stock"), ["RELIANCE.NS"])
        self.assertEqual(extract_prediction_tickers("prediction chart RELIANCE.NS"), ["RELIANCE.NS"])

    def test_compare_nse_tickers(self) -> None:
        self.assertEqual(extract_tickers("TCS.NS vs INFY.NS"), ["TCS.NS", "INFY.NS"])


class PredictionPlotTests(unittest.TestCase):
    def test_plot_prediction_chart_writes_png(self) -> None:
        from datetime import datetime, timedelta, timezone

        base = datetime(2025, 1, 1, tzinfo=timezone.utc)
        hist_dates = [base + timedelta(days=i) for i in range(30)]
        hist_values = [100 + i * 0.5 for i in range(30)]
        f_dates = [hist_dates[-1] + timedelta(days=i) for i in range(1, 8)]
        f_vals = [hist_values[-1] + i * 0.4 for i in range(1, 8)]
        forecast = ForecastSeries(
            label="TEST",
            hist_dates=hist_dates,
            hist_values=hist_values,
            forecast_dates=f_dates,
            forecast_values=f_vals,
            band_low=[v - 2 for v in f_vals],
            band_high=[v + 2 for v in f_vals],
            prob_up=0.62,
            signal="BULLISH",
            method="test linear trend",
            currency="USD",
        )
        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "pred.png"
            saved = plot_prediction_chart(forecast, title="Test forecast", output=out)
            self.assertTrue(saved.is_file())
            self.assertGreater(saved.stat().st_size, 1000)

    def test_build_forecast_with_mock_yahoo(self) -> None:
        from arka.charts.plot import PriceSeries
        from datetime import datetime, timezone

        dates = [datetime(2025, 1, i, tzinfo=timezone.utc) for i in range(1, 31)]
        values = [100 + i for i in range(30)]
        series = PriceSeries(label="MOCK", dates=dates, values=values, currency="USD")
        with mock.patch("arka.charts.plot.fetch_yahoo_series", return_value=series), mock.patch(
            "arka.charts.prediction._try_ml_prob", return_value=None
        ):
            fc = build_forecast("MOCK", history_range="1mo", horizon_days=7)
        self.assertIsNotNone(fc)
        assert fc is not None
        self.assertEqual(len(fc.forecast_dates), 7)
        self.assertIn(fc.signal, {"BULLISH", "BEARISH", "NEUTRAL"})


if __name__ == "__main__":
    unittest.main()
