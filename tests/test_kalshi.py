"""Tests for kalshi skill: parsing, routing, and mocked API responses."""

from __future__ import annotations

import json
import unittest
from unittest import mock

from arka.integrations.kalshi import (
    _market_text,
    exchange_status,
    fetch_market,
    format_market_line,
    format_status,
    nl_to_argv,
    route_command,
    sanitize_search_query,
    sanitize_ticker,
    search_markets,
    trending_markets,
)
from arka.routing.symbolic import route_kalshi, route_offline_extras


SAMPLE_MARKET = {
    "ticker": "KXBTC-25JUL-T100K",
    "event_ticker": "KXBTC-25JUL",
    "title": "Bitcoin above 100k",
    "subtitle": "July 2025",
    "yes_sub_title": "Above 100k",
    "no_sub_title": "At or below 100k",
    "status": "active",
    "yes_bid_dollars": "0.4200",
    "yes_ask_dollars": "0.4400",
    "last_price_dollars": "0.4300",
    "volume_fp": "12000",
    "volume_24h_fp": "3500",
    "close_time": "2025-07-31T23:59:00Z",
}

OTHER_MARKET = {
    "ticker": "KXFED-25JUL",
    "event_ticker": "KXFED-25JUL",
    "title": "Fed rate cut in July",
    "subtitle": "",
    "yes_sub_title": "Cut",
    "status": "active",
    "yes_bid_dollars": "0.6100",
    "yes_ask_dollars": "0.6300",
    "last_price_dollars": "0.6200",
    "volume_fp": "8000",
    "volume_24h_fp": "9000",
    "close_time": "2025-07-15T18:00:00Z",
}


def _json_response(payload: dict) -> bytes:
    return json.dumps(payload).encode()


class KalshiSanitizeTests(unittest.TestCase):
    def test_sanitize_ticker(self) -> None:
        self.assertEqual(sanitize_ticker("kxbtc-25jul"), "KXBTC-25JUL")

    def test_sanitize_ticker_rejects_shell(self) -> None:
        with self.assertRaises(ValueError):
            sanitize_ticker("FOO; rm -rf /")

    def test_sanitize_search_query(self) -> None:
        self.assertEqual(sanitize_search_query("bitcoin etf"), "bitcoin etf")

    def test_sanitize_search_rejects_metacharacters(self) -> None:
        with self.assertRaises(ValueError):
            sanitize_search_query("bitcoin; curl evil")


class KalshiParseTests(unittest.TestCase):
    def test_nl_search(self) -> None:
        self.assertEqual(nl_to_argv("kalshi predictions on bitcoin"), ["search", "bitcoin"])
        self.assertEqual(nl_to_argv("what are kalshi odds for fed rate cut"), ["search", "fed rate cut"])

    def test_nl_market_ticker(self) -> None:
        self.assertEqual(nl_to_argv("kalshi market KXBTC-25JUL-T100K"), ["market", "KXBTC-25JUL-T100K"])

    def test_nl_trending_status(self) -> None:
        self.assertEqual(nl_to_argv("kalshi trending"), ["trending"])
        self.assertEqual(nl_to_argv("kalshi status"), ["status"])

    def test_route_command(self) -> None:
        self.assertEqual(route_command("kalshi odds on inflation"), "kalshi search inflation")

    def test_no_match(self) -> None:
        self.assertEqual(nl_to_argv("what is the weather"), [])


class KalshiFormatTests(unittest.TestCase):
    def test_format_market_line(self) -> None:
        text = format_market_line(SAMPLE_MARKET)
        self.assertIn("KXBTC-25JUL-T100K", text)
        self.assertIn("YES", text)

    def test_format_status(self) -> None:
        text = format_status({"exchange_active": True, "trading_active": True})
        self.assertIn("Exchange active: True", text)


class KalshiApiTests(unittest.TestCase):
    @mock.patch("arka.integrations.kalshi._fetch_json")
    def test_fetch_market(self, fetch: mock.MagicMock) -> None:
        fetch.return_value = {"market": SAMPLE_MARKET}
        market = fetch_market("KXBTC-25JUL-T100K")
        self.assertEqual(market["ticker"], "KXBTC-25JUL-T100K")
        fetch.assert_called_once()

    @mock.patch("arka.integrations.kalshi.fetch_open_markets")
    def test_search_markets(self, open_markets: mock.MagicMock) -> None:
        open_markets.return_value = [SAMPLE_MARKET, OTHER_MARKET]
        hits = search_markets("bitcoin")
        self.assertEqual(len(hits), 1)
        self.assertEqual(hits[0]["ticker"], "KXBTC-25JUL-T100K")

    @mock.patch("arka.integrations.kalshi.fetch_open_markets")
    def test_trending_markets(self, open_markets: mock.MagicMock) -> None:
        open_markets.return_value = [SAMPLE_MARKET, OTHER_MARKET]
        hits = trending_markets(limit=1)
        self.assertEqual(hits[0]["ticker"], "KXFED-25JUL")

    @mock.patch("arka.integrations.kalshi._fetch_json")
    def test_exchange_status(self, fetch: mock.MagicMock) -> None:
        fetch.return_value = {"exchange_active": True, "trading_active": False}
        data = exchange_status()
        self.assertTrue(data["exchange_active"])
        self.assertFalse(data["trading_active"])


class KalshiRoutingTests(unittest.TestCase):
    def test_route_kalshi(self) -> None:
        hit = route_kalshi("kalshi predictions on bitcoin")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertTrue(hit.startswith("kalshi search"))

    def test_route_offline_extras(self) -> None:
        hit = route_offline_extras("what are kalshi odds for inflation")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertIn("kalshi", hit)

    def test_weather_not_kalshi(self) -> None:
        self.assertIsNone(route_kalshi("what is the weather today"))


class KalshiMarketTextTests(unittest.TestCase):
    def test_market_text_includes_fields(self) -> None:
        text = _market_text(SAMPLE_MARKET)
        self.assertIn("bitcoin", text)
        self.assertIn("kxbtc", text)


if __name__ == "__main__":
    unittest.main()
