"""Tests for Kaggle dataset future prediction."""

from __future__ import annotations

import unittest
from pathlib import Path
from unittest import mock

from arka.predict.domains import detect_domain, extract_kaggle_slug
from arka.predict.engine import nl_to_future_argv, run_future
from arka.predict.providers.kaggle import pick_timeseries_file


class KaggleSlugTests(unittest.TestCase):
    def test_extract_slug_from_url(self) -> None:
        self.assertEqual(
            extract_kaggle_slug("predict future from https://www.kaggle.com/datasets/heptapod/titanic"),
            "heptapod/titanic",
        )

    def test_extract_slug_inline(self) -> None:
        self.assertEqual(
            extract_kaggle_slug("forecast kaggle dataset heptapod/titanic next 30 days"),
            "heptapod/titanic",
        )

    def test_detect_kaggle_domain(self) -> None:
        self.assertEqual(
            detect_domain("predict future from kaggle dataset heptapod/titanic"),
            "kaggle",
        )


class KaggleRoutingTests(unittest.TestCase):
    def test_nl_future_argv_kaggle(self) -> None:
        argv = nl_to_future_argv("predict future from kaggle heptapod/titanic next 14 days --chart")
        self.assertIsNotNone(argv)
        assert argv is not None
        self.assertEqual(argv[0], "future")
        self.assertIn("--domain", argv)
        self.assertIn("kaggle", argv)
        self.assertIn("--chart", argv)


class KagglePickFileTests(unittest.TestCase):
    def test_pick_largest_csv(self) -> None:
        import tempfile

        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            small = root / "small.csv"
            big = root / "train.csv"
            small.write_text("x,y\n1,1\n2,2\n", encoding="utf-8")
            rows = ["date,value\n"] + [f"2024-01-{i:02d},{i}\n" for i in range(1, 20)]
            big.write_text("".join(rows), encoding="utf-8")
            picked = pick_timeseries_file(root)
            self.assertEqual(picked, big)


class KaggleForecastTests(unittest.TestCase):
    def test_run_future_kaggle_mock(self) -> None:
        from arka.charts.prediction import ForecastSeries
        from datetime import datetime, timezone, timedelta

        base = datetime(2024, 1, 1, tzinfo=timezone.utc)
        hist = [base + timedelta(days=i) for i in range(10)]
        fc = ForecastSeries(
            label="heptapod/titanic (train.csv)",
            hist_dates=hist,
            hist_values=[float(i) for i in range(10)],
            forecast_dates=hist[-1:] ,
            forecast_values=[10.0],
            band_low=[9.0],
            band_high=[11.0],
            prob_up=0.5,
            signal="TREND",
            method="test",
            currency="",
        )
        with mock.patch(
            "arka.predict.providers.kaggle.build_kaggle_forecast",
            return_value=(fc, "Kaggle summary"),
        ):
            result = run_future(
                "predict from kaggle heptapod/titanic next 7 days",
                domain="kaggle",
                days=7,
                chart=False,
            )
        self.assertEqual(result.domain, "kaggle")
        self.assertIn("Kaggle summary", result.text)


if __name__ == "__main__":
    unittest.main()
