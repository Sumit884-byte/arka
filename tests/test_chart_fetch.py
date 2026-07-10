"""Tests for sourced charts, NL parse fixes, and chart-type suitability."""

from __future__ import annotations

import json
import unittest
from pathlib import Path
from unittest import mock

from arka.charts.data import (
    ChartDataset,
    ChartSeries,
    ScatterDataset,
    build_scatter_dataset,
    detect_chart_intent,
    detect_local_country,
    detect_requested_chart_type,
    detect_share_topic,
    detect_topic,
    extract_countries,
    extract_scatter_entity,
    extract_year_range,
    has_chart_cue,
    is_year_range_pseudo_data,
    needs_external_data,
    needs_scatter_fetch,
    parse_scatter_axes,
    parse_share_percentages,
    recommend_chart_type,
)
from arka.charts.plot import nl_to_argv, parse_bar_pairs, unwrap_shell_quotes


class YearRangeParseTests(unittest.TestCase):
    def test_extract_year_range(self) -> None:
        self.assertEqual(extract_year_range("from 2023 to 2026"), (2023, 2026))
        self.assertEqual(extract_year_range("2020-2024"), (2020, 2024))
        self.assertEqual(extract_year_range("2019 vs 2022"), (2019, 2022))

    def test_year_range_is_pseudo_data(self) -> None:
        self.assertTrue(
            is_year_range_pseudo_data(
                "make an bar group to show population changes from 2023 to 2026"
            )
        )
        self.assertFalse(is_year_range_pseudo_data("Apple:230,Samsung:210"))
        self.assertFalse(is_year_range_pseudo_data("phone sales Apple 230 Samsung 210"))

    def test_parse_bar_pairs_rejects_from_to_years(self) -> None:
        labels, values, _ = parse_bar_pairs(
            "make an bar group to show population changes from 2023 to 2026"
        )
        self.assertEqual(labels, [])
        self.assertEqual(values, [])


class ExternalDataIntentTests(unittest.TestCase):
    def test_detect_topic_and_countries(self) -> None:
        self.assertEqual(detect_topic("population of India and China"), "population")
        self.assertEqual(detect_topic("GDP per capita trends"), "gdp_per_capita")
        self.assertEqual(extract_countries("India China USA"), ["IN", "CN", "US"])

    def test_detect_local_country_from_env(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {"ARKA_CHART_COUNTRY": "JP", "LANG": "en_US.UTF-8"},
            clear=False,
        ):
            self.assertEqual(detect_local_country(), "JP")

    def test_detect_local_country_from_locale(self) -> None:
        with mock.patch.dict(
            "os.environ",
            {"ARKA_CHART_COUNTRY": "", "LANG": "en_GB.UTF-8", "LC_ALL": "", "TZ": ""},
            clear=False,
        ), mock.patch(
            "arka.charts.data._country_from_chat_context",
            return_value=None,
        ), mock.patch(
            "arka.charts.data._country_from_timezone",
            return_value=None,
        ):
            self.assertEqual(detect_local_country(), "GB")

    def test_needs_external_data(self) -> None:
        self.assertTrue(
            needs_external_data(
                "make a bar group to show population changes from 2023 to 2026"
            )
        )
        self.assertFalse(needs_external_data("bar chart Apple:230,Samsung:210"))
        self.assertFalse(needs_external_data("chart line AAPL TSLA"))

    def test_nl_to_argv_routes_to_fetch(self) -> None:
        argv = nl_to_argv(
            "make an bar group to show population changes from 2023 to 2026"
        )
        self.assertEqual(argv[0], "fetch")
        self.assertIn("--type", argv)
        self.assertIn("grouped_bar", argv)

    def test_unwrap_fish_nested_quotes(self) -> None:
        nested = "''\"'\"'make an bar graph to show population changes from 2023 to 2026'\"'\"''"
        self.assertEqual(
            unwrap_shell_quotes(nested),
            "make an bar graph to show population changes from 2023 to 2026",
        )
        self.assertEqual(
            unwrap_shell_quotes("'make an bar graph to show population'"),
            "make an bar graph to show population",
        )

    def test_nl_to_argv_unwraps_quoted_fetch(self) -> None:
        argv = nl_to_argv(
            "'make an bar graph to show population changes from 2023 to 2026'"
        )
        self.assertEqual(argv[0], "fetch")
        self.assertEqual(
            argv[1],
            "make an bar graph to show population changes from 2023 to 2026",
        )

    def test_cmd_parse_prints_one_arg_per_line(self) -> None:
        import io

        from arka.charts import plot as plot_mod

        ns = mock.Mock(
            text=["make an bar graph to show population changes from 2023 to 2026"]
        )
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            rc = plot_mod.cmd_parse(ns)
        self.assertEqual(rc, 0)
        lines = [ln for ln in buf.getvalue().splitlines() if ln]
        self.assertEqual(lines[0], "fetch")
        self.assertEqual(
            lines[1],
            "make an bar graph to show population changes from 2023 to 2026",
        )
        self.assertIn("--type", lines)
        self.assertIn("bar", lines)

    def test_nl_to_argv_keeps_inline_bar(self) -> None:
        argv = nl_to_argv("phone sales Apple 230 Samsung 210 Xiaomi 140")
        self.assertEqual(argv[0], "bar")
        self.assertIn("--data", argv)

    def test_nl_to_argv_scatter_with_numbers(self) -> None:
        argv = nl_to_argv("scatter ad spend vs revenue 100 200 120 190 170 280")
        self.assertEqual(argv[0], "scatter")
        self.assertIn("--data", argv)
        self.assertIn("100:200,120:190,170:280", argv)
        self.assertIn("--xlabel", argv)
        self.assertIn("Ad Spend", argv)

    def test_nl_to_argv_scatter_ad_spend_without_numbers_needs_real_data(self) -> None:
        # Stay on chart path (not agent_ask) but do not invent demo pairs.
        argv = nl_to_argv("scatter ad spend vs revenue")
        self.assertEqual(argv, ["scatter"])
        self.assertNotIn("--data", argv)

    def test_nl_to_argv_scatter_fetch_for_company(self) -> None:
        argv = nl_to_argv("scatter ad spend vs revenue for blinkit")
        self.assertEqual(argv[0], "fetch")
        self.assertEqual(argv[1], "scatter ad spend vs revenue for blinkit")
        self.assertIn("--type", argv)
        self.assertEqual(argv[argv.index("--type") + 1], "scatter")

    def test_needs_scatter_fetch(self) -> None:
        self.assertTrue(
            needs_scatter_fetch("scatter ad spend vs revenue for blinkit")
        )
        self.assertFalse(needs_scatter_fetch("scatter ad spend vs revenue"))
        self.assertFalse(
            needs_scatter_fetch(
                "scatter ad spend vs revenue 100 200 120 190 170 280"
            )
        )

    def test_parse_scatter_axes_and_entity(self) -> None:
        axes = parse_scatter_axes("scatter ad spend vs revenue for blinkit")
        self.assertIsNotNone(axes)
        self.assertEqual(axes[1], "Ad spend")
        self.assertEqual(axes[2], "Revenue")
        self.assertEqual(extract_scatter_entity("scatter ad spend vs revenue for blinkit"), "blinkit")

    def test_build_scatter_dataset_sec_meta(self) -> None:
        from arka.charts import data as data_mod

        fake_tickers = {"META": {"cik_str": 1326801, "ticker": "META", "title": "Meta"}}
        fake_facts = {
            "facts": {
                "us-gaap": {
                    "AdvertisingExpense": {
                        "units": {
                            "USD": [
                                {"fy": 2022, "val": 2.0e9, "form": "10-K", "filed": "2023-02-01"},
                                {"fy": 2023, "val": 3.0e9, "form": "10-K", "filed": "2024-02-01"},
                                {"fy": 2024, "val": 2.5e9, "form": "10-K", "filed": "2025-02-01"},
                            ]
                        }
                    },
                    "RevenueFromContractWithCustomerExcludingAssessedTax": {
                        "units": {
                            "USD": [
                                {"fy": 2022, "val": 80.0e9, "form": "10-K", "filed": "2023-02-01"},
                                {"fy": 2023, "val": 110.0e9, "form": "10-K", "filed": "2024-02-01"},
                                {"fy": 2024, "val": 120.0e9, "form": "10-K", "filed": "2025-02-01"},
                            ]
                        }
                    },
                }
            }
        }
        with (
            mock.patch.object(data_mod, "_sec_load_company_tickers", return_value=fake_tickers),
            mock.patch.object(data_mod, "_sec_http_json", return_value=fake_facts),
        ):
            ds = build_scatter_dataset("scatter ad spend vs revenue for meta")
        self.assertIsInstance(ds, ScatterDataset)
        self.assertEqual(len(ds.xs), 3)
        self.assertEqual(len(ds.ys), 3)
        self.assertIn("SEC EDGAR", ds.source)
        self.assertEqual(ds.xlabel, "Ad spend")

    def test_build_scatter_dataset_blinkit_web_fallback(self) -> None:
        from arka.charts import data as data_mod

        blob = """
        Zomato FY2022 advertising spend Rs 450 crore and revenue Rs 4190 crore.
        FY2023 ad expenses were Rs 680 crore with revenue of Rs 7079 crore.
        In FY2024 marketing spend reached Rs 900 crore while revenue hit Rs 12114 crore.
        """
        with (
            mock.patch.object(data_mod, "_sec_load_company_tickers", return_value={}),
            mock.patch.object(data_mod, "_collect_scatter_web_text", return_value=blob),
        ):
            ds = build_scatter_dataset("scatter ad spend vs revenue for blinkit")
        self.assertEqual(len(ds.xs), 3)
        self.assertIn("Blinkit", ds.title)
        self.assertTrue(any("private" in n.lower() for n in ds.notes))

    def test_build_scatter_dataset_errors_without_data(self) -> None:
        from arka.charts import data as data_mod

        with (
            mock.patch.object(data_mod, "_sec_load_company_tickers", return_value={}),
            mock.patch.object(data_mod, "_collect_scatter_web_text", return_value="no figures here"),
            mock.patch.object(
                data_mod,
                "fetch_scatter_from_web",
                side_effect=RuntimeError("no web pairs"),
            ),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                build_scatter_dataset("scatter ad spend vs revenue for blinkit")
        self.assertIn("no web pairs", str(ctx.exception))

    def test_nl_to_argv_bare_scatter_stays_on_chart_path(self) -> None:
        # Unknown title without numbers: still return scatter so routing
        # does not fall through to agent_ask via \bvs\b.
        argv = nl_to_argv("scatter widgets vs gadgets")
        self.assertEqual(argv, ["scatter"])

    def test_os_pie_routes_to_fetch(self) -> None:
        self.assertEqual(
            detect_share_topic(
                "make an pie chart for distribution of various os as of 2026"
            )[0],
            "os_share",
        )
        self.assertTrue(
            needs_external_data(
                "make an pie chart for distribution of various os as of 2026"
            )
        )
        argv = nl_to_argv(
            "make an pie chart for distribution of various os as of 2026"
        )
        self.assertEqual(argv[0], "fetch")
        self.assertIn("--type", argv)
        self.assertIn("pie", argv)

    def test_device_pareto_routes_to_fetch(self) -> None:
        text = "make an pareto chart for various kinds of devices and user base"
        self.assertEqual(detect_share_topic(text)[0], "device_share")
        self.assertTrue(needs_external_data(text))
        self.assertEqual(detect_requested_chart_type(text), "pareto")
        argv = nl_to_argv(text)
        self.assertEqual(argv[0], "fetch")
        self.assertEqual(argv[1], text)
        self.assertIn("--type", argv)
        self.assertEqual(argv[argv.index("--type") + 1], "pareto")

    def test_nl_to_argv_bare_pareto_stays_on_chart_path(self) -> None:
        argv = nl_to_argv("make an pareto chart for defect causes")
        self.assertEqual(argv, ["pareto"])
        self.assertNotIn("--data", argv)

    def test_build_dataset_from_device_share_statcounter(self) -> None:
        from arka.charts import data as data_mod

        statcounter = """
| Desktop vs Mobile vs Tablet Market Share Worldwide |
|---|---|
| Mobile | 58.67% |
| Desktop | 39.12% |
| Tablet | 2.21% |
"""
        with (
            mock.patch.object(data_mod, "_collect_share_text", return_value=(statcounter, "StatCounter Global Stats")),
            mock.patch.object(data_mod, "detect_share_topic", return_value=("device_share", "Device traffic share")),
        ):
            ds = data_mod.build_dataset_from_share(
                "make an pareto chart for various kinds of devices and user base"
            )
        self.assertEqual(ds.topic, "device_share")
        self.assertIn("Mobile", ds.categories)
        self.assertIn("Desktop", ds.categories)
        self.assertGreater(ds.series[0].values[0], 0)

    def test_build_dataset_from_device_share_errors_without_data(self) -> None:
        from arka.charts import data as data_mod

        with (
            mock.patch.object(data_mod, "_collect_share_text", return_value=("no percentages here", "web search")),
            mock.patch.object(data_mod, "detect_share_topic", return_value=("device_share", "Device traffic share")),
            mock.patch.object(data_mod, "SHARE_FALLBACKS", {}),
        ):
            with self.assertRaises(RuntimeError) as ctx:
                data_mod.build_dataset_from_share(
                    "make an pareto chart for various kinds of devices and user base"
                )
        self.assertIn("No market-share slices", str(ctx.exception))

    def test_cmd_fetch_device_pareto(self) -> None:
        from pathlib import Path

        from arka.charts import plot as plot_mod

        dataset = ChartDataset(
            topic="device_share",
            indicator="market_share_pct",
            title="Device traffic share",
            ylabel="Share (%)",
            categories=["Mobile", "Desktop", "Tablet"],
            series=[ChartSeries("share", [58.67, 39.12, 2.21])],
            source="StatCounter Global Stats",
            years=[],
        )
        ns = mock.Mock(
            text=["make an pareto chart for various kinds of devices and user base"],
            type="pareto",
            force=False,
            title="",
            ylabel="",
            output="/tmp/arka-device-pareto.png",
        )
        with (
            mock.patch(
                "arka.charts.data.build_dataset",
                return_value=dataset,
            ),
            mock.patch.object(
                plot_mod,
                "plot_pareto",
                return_value=Path("/tmp/arka-device-pareto.png"),
            ) as pareto,
            mock.patch.object(plot_mod, "open_image"),
        ):
            rc = plot_mod.cmd_fetch(ns)
        self.assertEqual(rc, 0)
        pareto.assert_called_once()
        self.assertEqual(pareto.call_args.kwargs["source"], "StatCounter Global Stats")
        self.assertIs(pareto.call_args.kwargs["cumulative_line"], False)

    def test_parse_share_percentages(self) -> None:
        text = (
            "As of June 2026, the global market share for desktop OS: "
            "1. Microsoft Windows: 62.16% 2. Mac OS: 14.58% "
            "3. Desktop Linux: 3.09% 4. Google ChromeOS: 1.42%"
        )
        pairs = parse_share_percentages(text)
        labels = {lbl for lbl, _ in pairs}
        self.assertIn("Windows", labels)
        self.assertIn("macOS", labels)
        self.assertGreaterEqual(len(pairs), 3)

    def test_parse_statcounter_table_merges_osx(self) -> None:
        text = """
| Desktop Operating Systems | Percentage Market Share |
|---|---|
| Windows | 56.61% |
| Unknown | 21.45% |
| OS X | 11.89% |
| macOS | 4.48% |
| Linux | 4.36% |
| Chrome OS | 1.21% |
"""
        pairs = dict(parse_share_percentages(text))
        self.assertAlmostEqual(pairs["Windows"], 56.61, places=2)
        self.assertAlmostEqual(pairs["macOS"], 16.37, places=2)
        self.assertAlmostEqual(pairs["Linux"], 4.36, places=2)
        self.assertNotIn("OS X", pairs)


class ChartIntentRoutingTests(unittest.TestCase):
    """Decision-matrix NL routing: comparison→bar, temporal→line, composition→pie, …"""

    def test_detect_chart_intent_matrix(self) -> None:
        self.assertEqual(detect_chart_intent("compare phone sales by brand"), "bar")
        self.assertEqual(detect_chart_intent("population trend over time"), "line")
        self.assertEqual(detect_chart_intent("breakdown of market share"), "pie")
        self.assertEqual(detect_chart_intent("correlation between spend and revenue"), "scatter")
        self.assertEqual(detect_chart_intent("distribution of response times"), "histogram")
        self.assertEqual(detect_chart_intent("80/20 defect causes"), "pareto")
        self.assertEqual(detect_chart_intent("top contributors to downtime"), "pareto")

    def test_has_chart_cue(self) -> None:
        self.assertTrue(has_chart_cue("make an pareto chart for devices"))
        self.assertTrue(has_chart_cue("visualize device traffic share"))
        self.assertFalse(has_chart_cue("what is the population of India"))

    def test_compare_phone_sales_routes_to_bar_not_stocks(self) -> None:
        argv = nl_to_argv("compare phone sales Apple 230 Samsung 210 Xiaomi 140")
        self.assertEqual(argv[0], "bar")
        self.assertIn("Apple:230", argv[argv.index("--data") + 1])

    def test_make_chart_comparing_inline_data_is_bar(self) -> None:
        argv = nl_to_argv("make a chart comparing phone sales Apple 230 Samsung 210")
        self.assertEqual(argv[0], "bar")
        self.assertIn("--data", argv)

    def test_distribution_with_numbers_is_histogram(self) -> None:
        argv = nl_to_argv(
            "graph the distribution of response times 12 15 18 22 25 28 30"
        )
        self.assertEqual(argv[0], "histogram")
        self.assertIn("--data", argv)

    def test_pareto_8020_with_space_separated_pairs(self) -> None:
        argv = nl_to_argv("make an 80/20 chart for defect causes Scratches 45 Dents 28")
        self.assertEqual(argv[0], "pareto")
        self.assertIn("--data", argv)
        self.assertIn("Scratches:45", argv[argv.index("--data") + 1])

    def test_visualize_device_traffic_routes_to_fetch(self) -> None:
        argv = nl_to_argv("visualize device traffic share")
        self.assertEqual(argv[0], "fetch")
        self.assertEqual(detect_share_topic("visualize device traffic share")[0], "device_share")

    def test_bare_chart_intent_stays_on_chart_path(self) -> None:
        argv = nl_to_argv("make a chart comparing quarterly revenue magnitudes")
        self.assertEqual(argv, ["bar"])

    def test_temporal_population_routes_to_fetch_line(self) -> None:
        argv = nl_to_argv("visualize population trend over time from 2020 to 2024")
        self.assertEqual(argv[0], "fetch")
        self.assertEqual(argv[argv.index("--type") + 1], "line")

    def test_detect_requested_type_from_composition_keywords(self) -> None:
        self.assertEqual(detect_requested_chart_type("show breakdown of traffic sources"), "pie")
        self.assertEqual(detect_requested_chart_type("compare magnitudes by category"), "bar")


class StockLineNLTests(unittest.TestCase):
    """Natural-language stock line charts (Yahoo Finance tickers)."""

    def _assert_line_stock(self, text: str, tickers: list[str], rng: str) -> None:
        argv = nl_to_argv(text)
        self.assertEqual(argv[0], "line", msg=text)
        for sym in tickers:
            self.assertIn(sym, argv, msg=text)
        self.assertEqual(argv[argv.index("--range") + 1], rng, msg=text)

    def test_compare_company_names_with_stock_and_year(self) -> None:
        self._assert_line_stock("compare Apple and Tesla stock last year", ["AAPL", "TSLA"], "1y")

    def test_line_chart_tickers_past_year(self) -> None:
        self._assert_line_stock(
            "line chart AAPL and TSLA over the past year", ["AAPL", "TSLA"], "1y"
        )

    def test_vs_stock_phrase(self) -> None:
        self._assert_line_stock("Apple vs Tesla stock last year", ["AAPL", "TSLA"], "1y")

    def test_compare_tickers_without_stock_word(self) -> None:
        self._assert_line_stock("compare AAPL and TSLA", ["AAPL", "TSLA"], "3mo")

    def test_line_chart_company_names_one_year(self) -> None:
        self._assert_line_stock(
            "line chart of Apple and Tesla over 1 year", ["AAPL", "TSLA"], "1y"
        )

    def test_chart_tickers_last_three_months(self) -> None:
        self._assert_line_stock("chart TSLA and NVDA last 3 months", ["TSLA", "NVDA"], "3mo")

    def test_compare_phone_sales_stays_bar(self) -> None:
        argv = nl_to_argv("compare phone sales Apple 230 Samsung 210 Xiaomi 140")
        self.assertEqual(argv[0], "bar")
        self.assertIn("Apple:230", argv[argv.index("--data") + 1])

    def test_wants_stock_line_helper(self) -> None:
        from arka.charts.plot import wants_stock_line

        self.assertTrue(wants_stock_line("compare AAPL and TSLA", ["AAPL", "TSLA"], []))
        self.assertFalse(wants_stock_line("compare phone sales Apple 230", ["AAPL"], ["Apple"]))


class SuitabilityTests(unittest.TestCase):
    def _multi_year_dataset(self) -> ChartDataset:
        return ChartDataset(
            topic="population",
            indicator="SP.POP.TOTL",
            title="Population (2020–2023)",
            ylabel="People",
            categories=["India", "China", "United States"],
            series=[
                ChartSeries("2020", [1.0, 1.1, 0.3]),
                ChartSeries("2023", [1.1, 1.05, 0.33]),
            ],
            source="World Bank",
            years=[2020, 2023],
        )

    def _local_country_years(self) -> ChartDataset:
        return ChartDataset(
            topic="population",
            indicator="SP.POP.TOTL",
            title="Population — India (2020–2023)",
            ylabel="Population",
            categories=["2020", "2021", "2022", "2023"],
            series=[ChartSeries("India", [1.38e9, 1.40e9, 1.42e9, 1.44e9])],
            source="World Bank",
            years=[2020, 2021, 2022, 2023],
        )

    def test_recommend_grouped_for_multi_year(self) -> None:
        advice = recommend_chart_type(self._multi_year_dataset(), "auto")
        self.assertEqual(advice.recommended, "grouped_bar")

    def test_recommend_line_for_local_country_years(self) -> None:
        advice = recommend_chart_type(self._local_country_years(), "auto")
        self.assertEqual(advice.recommended, "line")

    def test_recommend_pie_for_os_share(self) -> None:
        ds = ChartDataset(
            topic="os_share",
            indicator="market_share_pct",
            title="Desktop OS market share",
            ylabel="Share (%)",
            categories=["Windows", "macOS", "Linux"],
            series=[ChartSeries("share", [70.0, 20.0, 10.0])],
            source="web",
            years=[],
        )
        advice = recommend_chart_type(ds, "auto")
        self.assertEqual(advice.recommended, "pie")

    def test_grouped_request_downgrades_for_single_country(self) -> None:
        advice = recommend_chart_type(self._local_country_years(), "grouped_bar")
        self.assertEqual(advice.recommended, "line")

    def test_warn_pie_for_time_series(self) -> None:
        advice = recommend_chart_type(self._multi_year_dataset(), "pie")
        self.assertEqual(advice.recommended, "grouped_bar")
        self.assertIn("Pie", advice.warning)

    def test_bar_upgrades_to_grouped(self) -> None:
        advice = recommend_chart_type(self._multi_year_dataset(), "bar")
        self.assertEqual(advice.recommended, "grouped_bar")
        self.assertTrue(advice.warning)

    def test_detect_requested_grouped(self) -> None:
        self.assertEqual(
            detect_requested_chart_type("make an bar group population"),
            "grouped_bar",
        )


class LocalDefaultDatasetTests(unittest.TestCase):
    def test_build_dataset_defaults_to_local_country(self) -> None:
        from arka.charts import data as data_mod

        fake = {"India": {2023: 1.44e9, 2024: 1.45e9}}
        with (
            mock.patch.object(data_mod, "detect_local_country", return_value="IN"),
            mock.patch.object(data_mod, "fetch_worldbank", return_value=fake) as fetch,
        ):
            ds = data_mod.build_dataset_from_worldbank(
                "population changes from 2023 to 2024"
            )
        fetch.assert_called_once()
        self.assertEqual(fetch.call_args.args[0], ["IN"])
        self.assertEqual(ds.categories, ["2023", "2024"])
        self.assertEqual(len(ds.series), 1)
        self.assertEqual(ds.series[0].name, "India")
        self.assertIn("India", ds.title)
        self.assertTrue(any("location" in n.lower() for n in ds.notes))

    def test_build_dataset_caps_future_years(self) -> None:
        from arka.charts import data as data_mod

        fake = {"India": {2023: 1.44e9, 2024: 1.45e9, 2025: 1.46e9}}
        with (
            mock.patch.object(data_mod, "detect_local_country", return_value="IN"),
            mock.patch.object(data_mod, "fetch_worldbank", return_value=fake) as fetch,
        ):
            ds = data_mod.build_dataset_from_worldbank(
                "population changes from 2023 to 2026"
            )
        # Asked through 2026; fetch should stop at last published calendar year.
        self.assertEqual(fetch.call_args.args[2], 2023)
        self.assertLessEqual(fetch.call_args.args[3], 2025)
        self.assertTrue(any("no data past" in n.lower() for n in ds.notes))

    def test_http_json_retries_then_uses_stale_cache(self) -> None:
        from arka.charts import data as data_mod

        url = "https://api.worldbank.org/v2/country/IN/indicator/SP.POP.TOTL?format=json"
        with (
            mock.patch.object(data_mod, "WORLDBANK_RETRIES", 2),
            mock.patch.object(data_mod, "WORLDBANK_CACHE_TTL", 86400),
            mock.patch.object(data_mod, "_cache_load", return_value=None),
            mock.patch.object(data_mod, "_cache_store"),
            mock.patch.object(
                data_mod,
                "_cache_key",
                return_value=mock.Mock(
                    is_file=mock.Mock(return_value=True),
                    read_text=mock.Mock(return_value='[{"page":1},[]]'),
                ),
            ),
            mock.patch("urllib.request.urlopen", side_effect=TimeoutError("timed out")),
            mock.patch("time.sleep"),
        ):
            out = data_mod._http_json(url, timeout=0.1)
        self.assertEqual(out, [{"page": 1}, []])

    def test_build_dataset_keeps_named_countries(self) -> None:
        from arka.charts import data as data_mod

        fake = {
            "India": {2023: 1.44e9},
            "China": {2023: 1.41e9},
        }
        with mock.patch.object(data_mod, "fetch_worldbank", return_value=fake) as fetch:
            ds = data_mod.build_dataset_from_worldbank(
                "population India China from 2023 to 2023"
            )
        self.assertEqual(fetch.call_args.args[0], ["IN", "CN"])
        self.assertEqual(ds.categories, ["India", "China"])
        self.assertEqual([s.name for s in ds.series], ["2023"])


class FetchCommandTests(unittest.TestCase):
    def test_cmd_fetch_overrides_unsuitable_pie(self) -> None:
        from pathlib import Path

        from arka.charts import plot as plot_mod

        dataset = ChartDataset(
            topic="population",
            indicator="SP.POP.TOTL",
            title="Population (2020–2023)",
            ylabel="People",
            categories=["India", "China"],
            series=[
                ChartSeries("2020", [100.0, 200.0]),
                ChartSeries("2023", [110.0, 190.0]),
            ],
            source="World Bank Open Data",
            years=[2020, 2023],
        )
        ns = mock.Mock(
            text=["population changes from 2020 to 2023"],
            type="pie",
            force=False,
            title="",
            ylabel="",
            output="/tmp/arka-test-chart.png",
        )
        with (
            mock.patch(
                "arka.charts.data.build_dataset",
                return_value=dataset,
            ),
            mock.patch.object(
                plot_mod,
                "plot_grouped_bar",
                return_value=Path("/tmp/arka-test-chart.png"),
            ) as grouped,
            mock.patch.object(plot_mod, "open_image"),
        ):
            rc = plot_mod.cmd_fetch(ns)
        self.assertEqual(rc, 0)
        grouped.assert_called_once()
        self.assertEqual(grouped.call_args.kwargs["title"], "Population (2020–2023)")
        self.assertEqual(grouped.call_args.kwargs["source"], "World Bank Open Data")

    def test_cmd_fetch_force_keeps_pie(self) -> None:
        from pathlib import Path

        from arka.charts import plot as plot_mod

        dataset = ChartDataset(
            topic="population",
            indicator="SP.POP.TOTL",
            title="Population (2020–2023)",
            ylabel="People",
            categories=["India", "China"],
            series=[
                ChartSeries("2020", [100.0, 200.0]),
                ChartSeries("2023", [110.0, 190.0]),
            ],
            source="World Bank Open Data",
            years=[2020, 2023],
        )
        ns = mock.Mock(
            text=["population pie"],
            type="pie",
            force=True,
            title="",
            ylabel="",
            output="/tmp/arka-test-pie.png",
        )
        with (
            mock.patch(
                "arka.charts.data.build_dataset",
                return_value=dataset,
            ),
            mock.patch.object(
                plot_mod,
                "plot_pie",
                return_value=Path("/tmp/arka-test-pie.png"),
            ) as pie,
            mock.patch.object(plot_mod, "open_image"),
        ):
            rc = plot_mod.cmd_fetch(ns)
        self.assertEqual(rc, 0)
        pie.assert_called_once()

    def test_cmd_fetch_os_share_pie(self) -> None:
        from pathlib import Path

        from arka.charts import plot as plot_mod

        dataset = ChartDataset(
            topic="os_share",
            indicator="market_share_pct",
            title="Desktop OS market share (2026)",
            ylabel="Share (%)",
            categories=["Windows", "macOS", "Linux", "ChromeOS", "Other"],
            series=[
                ChartSeries("share", [62.0, 15.0, 3.0, 1.5, 18.5]),
            ],
            source="StatCounter (via web)",
            years=[],
        )
        ns = mock.Mock(
            text=["make an pie chart for distribution of various os as of 2026"],
            type="pie",
            force=False,
            title="",
            ylabel="",
            output="/tmp/arka-os-pie.png",
        )
        with (
            mock.patch(
                "arka.charts.data.build_dataset",
                return_value=dataset,
            ),
            mock.patch.object(
                plot_mod,
                "plot_pie",
                return_value=Path("/tmp/arka-os-pie.png"),
            ) as pie,
            mock.patch.object(plot_mod, "open_image"),
        ):
            rc = plot_mod.cmd_fetch(ns)
        self.assertEqual(rc, 0)
        pie.assert_called_once()
        self.assertEqual(pie.call_args.kwargs["source"], "StatCounter (via web)")

    def test_cmd_fetch_scatter_sec(self) -> None:
        from pathlib import Path

        from arka.charts import plot as plot_mod

        scatter = ScatterDataset(
            topic="scatter_financial",
            title="Meta: Ad spend vs Revenue (FY2022–FY2024)",
            xlabel="Ad spend",
            ylabel="Revenue",
            periods=["FY2022", "FY2023", "FY2024"],
            xs=[2.0e9, 3.0e9, 2.5e9],
            ys=[80.0e9, 110.0e9, 120.0e9],
            source="SEC EDGAR XBRL (data.sec.gov, META)",
            notes=[],
            entity="Meta",
        )
        ns = mock.Mock(
            text=["scatter ad spend vs revenue for meta"],
            type="scatter",
            force=False,
            title="",
            ylabel="",
            xlabel="",
            output="/tmp/arka-scatter-test.png",
        )
        with (
            mock.patch(
                "arka.charts.data.build_scatter_dataset",
                return_value=scatter,
            ),
            mock.patch.object(
                plot_mod,
                "plot_scatter",
                return_value=Path("/tmp/arka-scatter-test.png"),
            ) as scatter_plot,
            mock.patch.object(plot_mod, "open_image"),
        ):
            rc = plot_mod.cmd_fetch(ns)
        self.assertEqual(rc, 0)
        scatter_plot.assert_called_once()
        self.assertEqual(scatter_plot.call_args.kwargs["source"], scatter.source)


class ChartDefaultsTests(unittest.TestCase):
    def setUp(self) -> None:
        import tempfile

        from arka.charts import defaults as defaults_mod

        self._tmpdir = tempfile.TemporaryDirectory()
        self._config_path = Path(self._tmpdir.name) / "charts.json"
        self._env_patch = mock.patch.dict(
            "os.environ",
            {"ARKA_CHARTS_CONFIG": str(self._config_path)},
            clear=False,
        )
        self._env_patch.start()
        self._defaults_mod = defaults_mod

    def tearDown(self) -> None:
        self._env_patch.stop()
        self._tmpdir.cleanup()

    def test_set_and_list_scatter_defaults(self) -> None:
        path = self._defaults_mod.set_kind_defaults(
            "scatter",
            {
                "data": "100:200,120:190,170:280",
                "xlabel": "Ad Spend",
                "ylabel": "Revenue",
            },
        )
        self.assertTrue(path.is_file())
        entries = self._defaults_mod.list_defaults()
        self.assertIn("scatter", entries)
        self.assertEqual(entries["scatter"]["data"], "100:200,120:190,170:280")

    def test_nl_to_argv_uses_scatter_defaults(self) -> None:
        self._defaults_mod.set_kind_defaults(
            "scatter",
            {"data": "100:200,120:190,170:280"},
        )
        argv = nl_to_argv("scatter ad spend vs revenue")
        self.assertEqual(argv[0], "scatter")
        self.assertIn("--data", argv)
        self.assertIn("100:200,120:190,170:280", argv)
        self.assertIn("--xlabel", argv)
        self.assertIn("Ad Spend", argv)
        self.assertIn("--ylabel", argv)
        self.assertIn("Revenue", argv)

    def test_nl_to_argv_scatter_without_defaults_stays_bare(self) -> None:
        argv = nl_to_argv("scatter ad spend vs revenue")
        self.assertEqual(argv, ["scatter"])

    def test_build_default_argv_bar(self) -> None:
        from arka.charts.plot import build_default_argv

        self._defaults_mod.set_kind_defaults(
            "bar",
            {"data": "Apple:230,Samsung:210", "title": "Phone sales"},
        )
        argv = build_default_argv("bar")
        self.assertEqual(argv[:3], ["bar", "--data", "Apple:230,Samsung:210"])
        self.assertIn("--title", argv)
        self.assertIn("Phone sales", argv)

    def test_cmd_scatter_uses_defaults(self) -> None:
        from arka.charts import plot as plot_mod

        self._defaults_mod.set_kind_defaults(
            "scatter",
            {
                "data": "100:200,120:190,170:280",
                "xlabel": "Spend",
                "ylabel": "Revenue",
            },
        )
        ns = mock.Mock(data="", title="", xlabel="", ylabel="", output="/tmp/arka-default-scatter.png")
        with (
            mock.patch.object(plot_mod, "plot_scatter", return_value=Path("/tmp/arka-default-scatter.png")) as scatter,
            mock.patch.object(plot_mod, "open_image"),
        ):
            rc = plot_mod.cmd_scatter(ns)
        self.assertEqual(rc, 0)
        scatter.assert_called_once()
        self.assertEqual(scatter.call_args.kwargs["xlabel"], "Spend")

    def test_cmd_defaults_list_and_unset(self) -> None:
        import io

        from arka.charts import plot as plot_mod

        self._defaults_mod.set_kind_defaults("pie", {"data": "A:1,B:2"})
        ns_list = mock.Mock(defaults_action="list", kind="")
        buf = io.StringIO()
        with mock.patch("sys.stdout", buf):
            rc = plot_mod.cmd_defaults(ns_list)
        self.assertEqual(rc, 0)
        self.assertIn("pie", buf.getvalue())

        ns_unset = mock.Mock(defaults_action="unset", kind="pie")
        rc = plot_mod.cmd_defaults(ns_unset)
        self.assertEqual(rc, 0)
        self.assertNotIn("pie", self._defaults_mod.list_defaults())


class ParetoPlotTests(unittest.TestCase):
    def test_default_cumulative_line_for_defect_causes(self) -> None:
        from arka.charts.plot import _default_pareto_cumulative_line

        self.assertTrue(
            _default_pareto_cumulative_line(
                ["Scratches", "Dents", "Cracks"],
                [45.0, 28.0, 15.0],
            )
        )

    def test_default_no_cumulative_line_for_device_share(self) -> None:
        from arka.charts.plot import _default_pareto_cumulative_line

        self.assertFalse(
            _default_pareto_cumulative_line(
                ["Mobile", "Desktop", "Tablet"],
                [51.51, 47.12, 1.36],
            )
        )

    def test_device_share_pareto_renders_without_twin_axis(self) -> None:
        import tempfile
        from pathlib import Path

        from arka.charts.plot import plot_pareto

        with tempfile.TemporaryDirectory() as tmp:
            out = Path(tmp) / "device-pareto.png"
            plot_pareto(
                ["Mobile", "Desktop", "Tablet"],
                [51.51, 47.12, 1.36],
                title="Device traffic share",
                output=out,
                source="StatCounter Global Stats",
                cumulative_line=False,
            )
            sidecar = json.loads(out.with_suffix(".json").read_text(encoding="utf-8"))
            self.assertFalse(sidecar["cumulative_line"])
            self.assertNotIn("cumulative_pct", sidecar)
            self.assertTrue(out.is_file())


if __name__ == "__main__":
    unittest.main()
