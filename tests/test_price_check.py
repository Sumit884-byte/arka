"""Tests for price_check skill routing and core logic."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from arka.agent.core import price_check
from arka.agent.price_sources import (
    build_price_search_queries,
    detect_price_region,
    extract_product_name,
    fetch_price_web_context,
    is_price_check_query,
    parse_price_query,
)
from arka.router import route
from arka.routing.symbolic import route_price_check


class PriceCheckRoutingTests(unittest.TestCase):
    def test_route_price_check_explicit_and_natural(self) -> None:
        cases = {
            "price_check macbook air m3": "price_check",
            "macbook price right now": "price_check",
            "iphone 16 price in india": "price_check",
            "how much is macbook air m3": "price_check",
            "price of iphone 16 pro": "price_check",
            "cost of macbook pro 14": "price_check",
            "what is the price of ipad air": "price_check",
        }
        for query, skill in cases.items():
            with self.subTest(query=query):
                hit = route_price_check(query)
                self.assertIsNotNone(hit)
                assert hit is not None
                self.assertEqual(hit.split()[0], skill)

    def test_route_price_check_rejects_stock_and_crypto(self) -> None:
        for query in (
            "aapl stock price",
            "bitcoin price right now",
            "ethereum price",
            "house price in mumbai",
        ):
            with self.subTest(query=query):
                self.assertIsNone(route_price_check(query))

    def test_router_symbolic_routes_to_price_check(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("macbook price right now")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "price_check")

    def test_router_price_check_before_web_answer(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("how much is macbook air m3")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "price_check")


class PriceCheckParseTests(unittest.TestCase):
    def test_extract_product_name(self) -> None:
        cases = {
            "macbook price right now": "macbook",
            "iphone 16 price in india": "iphone 16",
            "how much is macbook air m3": "macbook air m3",
            "price of iphone 16 pro": "iphone 16 pro",
            "cost of macbook pro 14": "macbook pro 14",
            "price_check macbook air m3": "macbook air m3",
        }
        for query, product in cases.items():
            with self.subTest(query=query):
                self.assertEqual(extract_product_name(query), product)

    def test_detect_region(self) -> None:
        self.assertEqual(detect_price_region("iphone 16 price in india"), "india")
        self.assertEqual(detect_price_region("macbook price in us"), "us")
        self.assertEqual(detect_price_region("macbook price"), "india")

    def test_is_price_check_query(self) -> None:
        self.assertTrue(is_price_check_query("macbook price right now"))
        self.assertFalse(is_price_check_query("how much disk space left"))
        self.assertFalse(is_price_check_query("bitcoin price"))

    def test_build_queries_target_india_domains(self) -> None:
        queries = build_price_search_queries("macbook air m3", region="india")
        combined = queries[0].query
        self.assertIn("site:apple.com/in", combined)
        self.assertIn("site:flipkart.com", combined)
        self.assertIn("site:amazon.in", combined)
        ids = {q.source_id for q in queries}
        self.assertIn("apple_in", ids)
        self.assertIn("flipkart", ids)

    def test_build_queries_target_us_domains(self) -> None:
        queries = build_price_search_queries("macbook air m3", region="us")
        combined = queries[0].query
        self.assertIn("site:apple.com", combined)
        self.assertIn("site:bestbuy.com", combined)
        self.assertIn("site:amazon.com", combined)

    def test_parse_price_query(self) -> None:
        product, region = parse_price_query("iphone 16 price in india")
        self.assertEqual(product, "iphone 16")
        self.assertEqual(region, "india")


class PriceCheckCoreTests(unittest.TestCase):
    def test_price_check_formats_output_from_scraped_context(self) -> None:
        scraped = (
            "[Apple India]\n"
            "MacBook Air M3 13-inch — ₹1,14,900 — https://www.apple.com/in/shop/buy-mac/macbook-air"
        )
        with mock.patch(
            "arka.agent.price_sources.fetch_price_web_context",
            return_value=(scraped, ["Apple India", "Flipkart"]),
        ):
            with mock.patch("arka.agent.core._llm", return_value=(
                "MacBook Air M3 13-inch | ₹1,14,900 | Apple India | "
                "https://www.apple.com/in/shop/buy-mac/macbook-air\n"
                "Date retrieved: 2026-07-09"
            )) as llm:
                with mock.patch("arka.output.print_block") as print_block:
                    price_check("macbook air m3 price in india")
        llm.assert_called_once()
        args, _ = print_block.call_args
        self.assertEqual(args[0], "Price check")
        self.assertIn("₹1,14,900", args[1])

    def test_price_check_honest_when_no_prices(self) -> None:
        with mock.patch(
            "arka.agent.price_sources.fetch_price_web_context",
            return_value=("", ["Apple India", "Flipkart"]),
        ):
            with mock.patch("arka.agent.core._llm") as llm:
                with mock.patch("arka.output.print_block") as print_block:
                    price_check("obscure gadget xyz123")
        llm.assert_not_called()
        args, _ = print_block.call_args
        self.assertIn("No live prices found", args[1])

    def test_price_check_empty_query_prints_usage(self) -> None:
        with mock.patch("arka.agent.price_sources.fetch_price_web_context") as fetch:
            with mock.patch("builtins.print") as print_mock:
                price_check("   ")
        fetch.assert_not_called()
        print_mock.assert_called_once()
        self.assertIn("Usage", print_mock.call_args[0][0])

    def test_fetch_price_web_context_uses_scrape_pipeline(self) -> None:
        with mock.patch("arka.agent.chat.scrape_search_results", return_value="page text") as scrape:
            with mock.patch("arka.agent.chat.snippet_lookup", return_value=""):
                ctx, labels = fetch_price_web_context("iphone 16", region="india", deep=True)
        self.assertTrue(scrape.called)
        self.assertIn("page text", ctx)
        self.assertTrue(labels)


if __name__ == "__main__":
    unittest.main()
