"""Tests for price_check skill routing and core logic."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from arka.agent.core import price_check
from arka.agent.price_sources import (
    PriceListing,
    build_price_search_queries,
    check_url_reachable,
    detect_price_region,
    extract_apple_shop_listings,
    extract_prices_from_content,
    extract_product_name,
    fetch_apple_shop_listings,
    fetch_price_listings,
    fetch_price_web_context,
    format_price_check_output,
    is_category_only_apple_url,
    is_excluded_retail_url,
    is_price_check_query,
    is_shop_product_url,
    parse_price_query,
    resolve_apple_shop_url,
    retailer_for_url,
)
from arka.router import route
from arka.routing.symbolic import route_price_check

APPLE_SHOP_URL = "https://www.apple.com/in/shop/buy-mac/macbook-pro/14-inch-space-black"
APPLE_MBP_LINE_URL = "https://www.apple.com/in/shop/buy-mac/macbook-pro"
APPLE_CATEGORY_URL = "https://www.apple.com/in/shop/buy-mac"
APPLE_NEWSROOM_URL = (
    "https://www.apple.com/in/newsroom/2024/10/apples-new-macbook-pro-features-m4-family-of-chips"
)
FLIPKART_URL = "https://www.flipkart.com/apple-macbook-pro-m4/p/itm1234567890abcd"


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

    def test_build_queries_target_india_shop_domains(self) -> None:
        queries = build_price_search_queries("macbook air m3", region="india")
        combined = queries[0].query
        self.assertIn("macbook air m3 price buy", combined)
        ids = {q.source_id for q in queries}
        self.assertIn("apple_in", ids)
        self.assertIn("flipkart", ids)
        apple_q = next(q for q in queries if q.source_id == "apple_in")
        self.assertIn("apple.com", apple_q.query)
        flipkart_q = next(q for q in queries if q.source_id == "flipkart")
        self.assertIn("flipkart.com", flipkart_q.query)

    def test_build_queries_target_us_shop_domains(self) -> None:
        queries = build_price_search_queries("macbook air m3", region="us")
        combined = queries[0].query
        self.assertIn("macbook air m3 price buy", combined)
        ids = {q.source_id for q in queries}
        self.assertIn("apple_us", ids)
        self.assertIn("bestbuy", ids)
        amazon_q = next(q for q in queries if q.source_id == "amazon_us")
        self.assertIn("amazon.com", amazon_q.query)

    def test_parse_price_query(self) -> None:
        product, region = parse_price_query("iphone 16 price in india")
        self.assertEqual(product, "iphone 16")
        self.assertEqual(region, "india")


class PriceUrlValidationTests(unittest.TestCase):
    def test_rejects_category_only_apple_urls(self) -> None:
        for url in (
            APPLE_CATEGORY_URL,
            "https://www.apple.com/shop/buy-mac",
            "https://www.apple.com/in/shop/buy-iphone",
        ):
            with self.subTest(url=url):
                self.assertTrue(is_category_only_apple_url(url))
                self.assertTrue(is_excluded_retail_url(url))
                self.assertIsNone(retailer_for_url(url))

    def test_rejects_newsroom_and_support_urls(self) -> None:
        for url in (
            APPLE_NEWSROOM_URL,
            "https://www.apple.com/in/support/macbook-pro/",
            "https://www.apple.com/newsroom/2024/10/macbook-pro",
            "https://www.apple.com/in/news/macbook-pro",
        ):
            with self.subTest(url=url):
                self.assertTrue(is_excluded_retail_url(url))
                self.assertIsNone(retailer_for_url(url))
                self.assertFalse(is_shop_product_url(url))

    def test_accepts_shop_and_product_urls(self) -> None:
        self.assertEqual(retailer_for_url(APPLE_SHOP_URL), ("apple_in", "Apple India"))
        self.assertTrue(is_shop_product_url(APPLE_SHOP_URL, "apple_in"))
        self.assertEqual(
            retailer_for_url("https://www.amazon.in/dp/B0DLH1GZDP"),
            ("amazon_in", "Amazon India"),
        )
        self.assertEqual(
            retailer_for_url(FLIPKART_URL),
            ("flipkart", "Flipkart"),
        )

    def test_check_url_reachable_uses_head_or_get(self) -> None:
        with mock.patch("urllib.request.urlopen") as urlopen:
            urlopen.return_value.__enter__.return_value.status = 200
            self.assertTrue(check_url_reachable(APPLE_SHOP_URL))
        urlopen.assert_called()


class PriceExtractionTests(unittest.TestCase):
    def test_extract_inr_from_shop_page_html(self) -> None:
        shop_html = (
            "14-inch MacBook Pro - Space Black From ₹1,69,900 "
            "or ₹14,158.33/month for 12 mo."
        )
        prices = extract_prices_from_content(shop_html, region="india")
        self.assertEqual(prices, ["₹1,69,900"])

    def test_extract_usd_from_shop_page_html(self) -> None:
        shop_html = "MacBook Pro 14-inch From $1,599.00"
        prices = extract_prices_from_content(shop_html, region="us")
        self.assertEqual(prices, ["$1,599.00"])

    def test_newsroom_page_without_price_returns_empty(self) -> None:
        newsroom_html = (
            "Apple introduces the new MacBook Pro with M4 family of chips. "
            "Available starting November 8."
        )
        self.assertEqual(extract_prices_from_content(newsroom_html, region="india"), [])


class PriceCheckCoreTests(unittest.TestCase):
    def test_price_check_formats_output_from_validated_listings(self) -> None:
        listings = [
            PriceListing(
                model="MacBook Air M3 13-inch",
                price="₹1,14,900",
                source="Apple India",
                url=APPLE_SHOP_URL,
            )
        ]
        with mock.patch(
            "arka.agent.price_sources.fetch_price_listings",
            return_value=(listings, ["Apple India", "Flipkart"]),
        ):
            with mock.patch("arka.agent.core._llm") as llm:
                with mock.patch("arka.output.print_block") as print_block:
                    price_check("macbook air m3 price in india")
        llm.assert_not_called()
        args, _ = print_block.call_args
        self.assertEqual(args[0], "Price check")
        self.assertIn("₹1,14,900", args[1])
        self.assertIn("/shop/", args[1])
        self.assertNotIn("newsroom", args[1])

    def test_price_check_honest_when_no_prices(self) -> None:
        with mock.patch(
            "arka.agent.price_sources.fetch_price_listings",
            return_value=([], ["Apple India", "Flipkart"]),
        ):
            with mock.patch("arka.agent.core._llm") as llm:
                with mock.patch("arka.output.print_block") as print_block:
                    price_check("obscure gadget xyz123")
        llm.assert_not_called()
        args, _ = print_block.call_args
        self.assertIn("No live prices found", args[1])
        self.assertIn("Apple India", args[1])

    def test_price_check_empty_query_prints_usage(self) -> None:
        with mock.patch("arka.agent.price_sources.fetch_price_listings") as fetch:
            with mock.patch("builtins.print") as print_mock:
                price_check("   ")
        fetch.assert_not_called()
        print_mock.assert_called_once()
        self.assertIn("Usage", print_mock.call_args[0][0])

    def test_fetch_price_listings_rejects_newsroom_and_requires_price(self) -> None:
        search_results = [
            {
                "link": APPLE_NEWSROOM_URL,
                "title": "Apple's new MacBook Pro features M4",
                "snippet": "Apple today announced MacBook Pro with M4 chips.",
            },
            {
                "link": FLIPKART_URL,
                "title": "Apple MacBook Pro M4",
                "snippet": "From ₹1,69,900",
            },
        ]
        with mock.patch("arka.agent.price_sources.fetch_apple_shop_listings", return_value=[]):
            with mock.patch("arka.agent.chat.duckduckgo_search", return_value=search_results):
                with mock.patch("arka.agent.price_sources.check_url_reachable", return_value=True):
                    with mock.patch(
                        "arka.agent.chat.scrape_url",
                        side_effect=lambda url: (
                            "From ₹1,69,900"
                            if "flipkart" in url
                            else "Apple today announced MacBook Pro with M4 chips."
                        ),
                    ):
                        listings, labels = fetch_price_listings(
                            "macbook pro", region="india", deep=True
                        )
        self.assertEqual(len(listings), 1)
        self.assertIn("/p/", listings[0].url)
        self.assertEqual(listings[0].price, "₹1,69,900")
        self.assertTrue(labels)

    def test_fetch_price_web_context_returns_validated_listings(self) -> None:
        listings = [
            PriceListing(
                model="MacBook Pro 14-inch",
                price="₹1,69,900",
                source="Apple India",
                url=APPLE_SHOP_URL,
            )
        ]
        with mock.patch(
            "arka.agent.price_sources.fetch_price_listings",
            return_value=(listings, ["Apple India"]),
        ):
            ctx, labels = fetch_price_web_context("macbook pro", region="india", deep=True)
        self.assertIn(APPLE_SHOP_URL, ctx)
        self.assertIn("₹1,69,900", ctx)
        self.assertEqual(labels, ["Apple India"])

    def test_format_price_check_output_lists_only_shop_links(self) -> None:
        output = format_price_check_output(
            [
                PriceListing(
                    model="14-inch MacBook Pro (M4)",
                    price="₹1,69,900",
                    source="Apple India",
                    url=APPLE_SHOP_URL,
                )
            ],
            product="macbook pro",
            region="india",
            searched_labels=["Apple India", "Flipkart"],
            retrieved_on="2026-07-09",
        )
        self.assertIn(APPLE_SHOP_URL, output)
        self.assertIn("₹1,69,900", output)
        self.assertIn("Date retrieved: 2026-07-09", output)


APPLE_MBP_HTML = """
<script type="application/ld+json">
{"@context":"https://schema.org","@type":"Product","name":"MacBook Pro","url":"https://www.apple.com/in/shop/buy-mac/macbook-pro","offers":[{"@type":"AggregateOffer","lowPrice":239900.00,"highPrice":1287700.00,"priceCurrency":"INR"}]}
</script>
"14inch-spaceblack-standard-m5-10-10":{"comparativeDisplayPrice":"From <span>₹239900.00</span>","amount":239900.00}
"14inch-silver-standard-m5pro-15-16":{"comparativeDisplayPrice":"From <span>₹299900.00</span>","amount":299900.00}
"16inch-silver-standard-m5pro-18-20":{"comparativeDisplayPrice":"From <span>₹339900.00</span>","amount":339900.00}
"""


class AppleDirectFetchTests(unittest.TestCase):
    def test_resolve_apple_shop_url_for_macbook_pro(self) -> None:
        self.assertEqual(
            resolve_apple_shop_url("macbook pro", region="india"),
            APPLE_MBP_LINE_URL,
        )

    def test_extract_apple_shop_listings_from_embedded_pricing(self) -> None:
        listings = extract_apple_shop_listings(
            APPLE_MBP_HTML,
            url=APPLE_MBP_LINE_URL,
            product="macbook pro",
            region="india",
            source_label="Apple India",
        )
        self.assertGreaterEqual(len(listings), 3)
        models = {item.model for item in listings}
        self.assertIn("14-inch MacBook Pro M5 (Space Black)", models)
        self.assertIn("14-inch MacBook Pro M5 Pro (Silver)", models)
        self.assertTrue(all(item.price.startswith("₹") for item in listings))
        self.assertTrue(all("/macbook-pro" in item.url for item in listings))

    def test_extract_filters_by_size_when_requested(self) -> None:
        listings = extract_apple_shop_listings(
            APPLE_MBP_HTML,
            url=APPLE_MBP_LINE_URL,
            product="macbook pro 14",
            region="india",
            source_label="Apple India",
        )
        self.assertTrue(all("14-inch" in item.model for item in listings))
        self.assertFalse(any("16-inch" in item.model for item in listings))

    def test_fetch_price_listings_uses_direct_apple_before_search(self) -> None:
        with mock.patch(
            "arka.agent.price_sources.fetch_apple_shop_listings",
            return_value=[
                PriceListing(
                    model="14-inch MacBook Pro M5 (Space Black)",
                    price="₹239,900",
                    source="Apple India",
                    url=APPLE_MBP_LINE_URL,
                )
            ],
        ) as apple_fetch:
            with mock.patch("arka.agent.chat.duckduckgo_search", return_value=[]):
                listings, labels = fetch_price_listings("macbook pro", region="india", deep=False)
        apple_fetch.assert_called_once()
        self.assertEqual(len(listings), 1)
        self.assertIn("Apple India", labels)
        self.assertIn("/macbook-pro", listings[0].url)

    def test_fetch_apple_shop_listings_mocked(self) -> None:
        with mock.patch("arka.agent.price_sources.check_url_reachable", return_value=True):
            with mock.patch(
                "arka.agent.price_sources.fetch_page_html",
                return_value=APPLE_MBP_HTML,
            ):
                listings = fetch_apple_shop_listings("macbook pro", region="india")
        self.assertGreaterEqual(len(listings), 1)
        self.assertEqual(listings[0].source, "Apple India")


if __name__ == "__main__":
    unittest.main()
