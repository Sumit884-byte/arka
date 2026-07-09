"""Tests for currency_convert skill: parsing, routing, and mocked rate fetch."""

from __future__ import annotations

import os
import unittest
from decimal import Decimal
from unittest import mock

from arka.integrations.currency import (
    convert,
    format_result,
    nl_to_argv,
    normalize_currency,
    parse_convert,
    ConversionResult,
)
from arka.router import route
from arka.routing.symbolic import route_currency_convert


class CurrencyNormalizeTests(unittest.TestCase):
    def test_iso_codes(self) -> None:
        self.assertEqual(normalize_currency("usd"), "USD")
        self.assertEqual(normalize_currency("EUR"), "EUR")
        self.assertEqual(normalize_currency("inr"), "INR")

    def test_aliases(self) -> None:
        self.assertEqual(normalize_currency("dollars"), "USD")
        self.assertEqual(normalize_currency("euros"), "EUR")
        self.assertEqual(normalize_currency("rupees"), "INR")
        self.assertEqual(normalize_currency("pounds"), "GBP")

    def test_unknown(self) -> None:
        self.assertIsNone(normalize_currency("monopoly money"))


class CurrencyParseTests(unittest.TestCase):
    def test_direct_three_args(self) -> None:
        parsed = parse_convert("100 USD INR")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed[0], Decimal("100"))
        self.assertEqual(parsed[1], "USD")
        self.assertEqual(parsed[2], "INR")

    def test_nl_to_pattern(self) -> None:
        parsed = parse_convert("convert 100 USD to INR")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed[0], Decimal("100"))
        self.assertEqual(parsed[1], "USD")
        self.assertEqual(parsed[2], "INR")

    def test_currency_alias_words(self) -> None:
        parsed = parse_convert("50 euros to dollars")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed[0], Decimal("50"))
        self.assertEqual(parsed[1], "EUR")
        self.assertEqual(parsed[2], "USD")

    def test_what_is_pattern(self) -> None:
        parsed = parse_convert("what is 500 EUR in GBP")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed[0], Decimal("500"))
        self.assertEqual(parsed[1], "EUR")
        self.assertEqual(parsed[2], "GBP")

    def test_rupees_to_usd(self) -> None:
        parsed = parse_convert("convert 1000 rupees to usd")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed[1], "INR")
        self.assertEqual(parsed[2], "USD")

    def test_exchange_rate_defaults_to_one(self) -> None:
        parsed = parse_convert("USD to INR")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed[0], Decimal("1"))

    def test_unknown_currency_returns_none(self) -> None:
        self.assertIsNone(parse_convert("100 foobar to bazqux"))

    def test_nl_to_argv(self) -> None:
        self.assertEqual(nl_to_argv("convert 100 USD to INR"), ["100", "USD", "INR"])
        self.assertEqual(nl_to_argv("hello world"), [])


class CurrencyFetchTests(unittest.TestCase):
    def test_convert_same_currency(self) -> None:
        result = convert(Decimal("100"), "USD", "USD")
        self.assertEqual(result.result, Decimal("100"))
        self.assertEqual(result.rate, Decimal("1"))

    def test_convert_unknown_raises(self) -> None:
        with self.assertRaises(ValueError):
            convert(Decimal("1"), "ZZZ", "USD")

    @mock.patch("arka.integrations.currency.fetch_conversion")
    def test_convert_delegates_fetch(self, mock_fetch: mock.MagicMock) -> None:
        mock_fetch.return_value = ConversionResult(
            amount=Decimal("100"),
            from_ccy="USD",
            to_ccy="INR",
            rate=Decimal("83"),
            result=Decimal("8300"),
            date="2026-07-09",
            source="test",
        )
        result = convert(Decimal("100"), "USD", "INR")
        self.assertEqual(result.result, Decimal("8300"))
        mock_fetch.assert_called_once_with(Decimal("100"), "USD", "INR")

    def test_format_result(self) -> None:
        text = format_result(
            ConversionResult(
                amount=Decimal("100"),
                from_ccy="USD",
                to_ccy="INR",
                rate=Decimal("83.5"),
                result=Decimal("8350"),
                date="2026-07-09",
                source="Frankfurter (ECB)",
            )
        )
        self.assertIn("100 USD", text)
        self.assertIn("8350 INR", text)
        self.assertIn("Frankfurter", text)


class CurrencyRoutingTests(unittest.TestCase):
    def test_symbolic_route_convert(self) -> None:
        hit = route_currency_convert("convert 100 USD to INR")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.split()[0], "currency_convert")

    def test_symbolic_route_what_is(self) -> None:
        hit = route_currency_convert("what is 500 EUR in GBP")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertIn("500", hit)
        self.assertIn("EUR", hit)

    def test_symbolic_route_non_currency(self) -> None:
        self.assertIsNone(route_currency_convert("what is the weather today"))

    def test_router_symbolic_only(self) -> None:
        for query in (
            "convert 100 USD to INR",
            "what is 500 EUR in GBP",
            "currency 50 euros to dollars",
        ):
            with self.subTest(query=query):
                with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
                    result = route(query)
                self.assertIsNotNone(result)
                assert result is not None
                self.assertEqual(result.skill.split()[0], "currency_convert")


if __name__ == "__main__":
    unittest.main()
