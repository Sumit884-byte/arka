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
        self.assertEqual(normalize_currency("rs"), "INR")
        self.assertEqual(normalize_currency("pounds"), "GBP")
        self.assertEqual(normalize_currency("bucks"), "USD")
        self.assertEqual(normalize_currency("quid"), "GBP")

    def test_symbols(self) -> None:
        self.assertEqual(normalize_currency("$"), "USD")
        self.assertEqual(normalize_currency("€"), "EUR")
        self.assertEqual(normalize_currency("£"), "GBP")
        self.assertEqual(normalize_currency("₹"), "INR")
        self.assertEqual(normalize_currency("¥"), "JPY")

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

    def test_dollars_to_rs(self) -> None:
        parsed = parse_convert("convert 250 dollars to rs")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed[0], Decimal("250"))
        self.assertEqual(parsed[1], "USD")
        self.assertEqual(parsed[2], "INR")

    def test_dollars_ot_rs_typo(self) -> None:
        parsed = parse_convert("convert 250 dollars ot rs")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed[0], Decimal("250"))
        self.assertEqual(parsed[1], "USD")
        self.assertEqual(parsed[2], "INR")

    def test_arka_prefix(self) -> None:
        parsed = parse_convert("arka convert 100 USD to INR")
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

    def test_symbol_before_amount(self) -> None:
        parsed = parse_convert("convert $250 to ₹")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed[0], Decimal("250"))
        self.assertEqual(parsed[1], "USD")
        self.assertEqual(parsed[2], "INR")

    def test_amount_to_symbol_only_target(self) -> None:
        parsed = parse_convert("250 to ₹")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed[0], Decimal("250"))
        self.assertEqual(parsed[1], "USD")
        self.assertEqual(parsed[2], "INR")

    def test_dollar_prefix_to_rupee_symbol(self) -> None:
        parsed = parse_convert("$250 to ₹")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed[0], Decimal("250"))
        self.assertEqual(parsed[1], "USD")
        self.assertEqual(parsed[2], "INR")

    def test_symbol_after_amount(self) -> None:
        parsed = parse_convert("convert 250 $ to rs")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed[0], Decimal("250"))
        self.assertEqual(parsed[1], "USD")
        self.assertEqual(parsed[2], "INR")

    def test_euro_to_dollars(self) -> None:
        parsed = parse_convert("convert €100 to dollars")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed[0], Decimal("100"))
        self.assertEqual(parsed[1], "EUR")
        self.assertEqual(parsed[2], "USD")

    def test_pound_to_inr_no_convert_prefix(self) -> None:
        parsed = parse_convert("£50 to inr")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed[0], Decimal("50"))
        self.assertEqual(parsed[1], "GBP")
        self.assertEqual(parsed[2], "INR")

    def test_k_shorthand_with_arrow(self) -> None:
        parsed = parse_convert("convert 1k usd → eur")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed[0], Decimal("1000"))
        self.assertEqual(parsed[1], "USD")
        self.assertEqual(parsed[2], "EUR")

    def test_bucks_to_rupees(self) -> None:
        parsed = parse_convert("250 bucks to rupees")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed[0], Decimal("250"))
        self.assertEqual(parsed[1], "USD")
        self.assertEqual(parsed[2], "INR")

    def test_quid_to_usd(self) -> None:
        parsed = parse_convert("100 quid to usd")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed[0], Decimal("100"))
        self.assertEqual(parsed[1], "GBP")
        self.assertEqual(parsed[2], "USD")

    def test_ot_typo_connector(self) -> None:
        parsed = parse_convert("250 $ ot rs")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed[1], "USD")
        self.assertEqual(parsed[2], "INR")

    def test_grand_shorthand(self) -> None:
        parsed = parse_convert("2 grand bucks to inr")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        self.assertEqual(parsed[0], Decimal("2000"))
        self.assertEqual(parsed[1], "USD")
        self.assertEqual(parsed[2], "INR")


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
                amount=Decimal("250"),
                from_ccy="USD",
                to_ccy="INR",
                rate=Decimal("95.604562"),
                result=Decimal("23901.1405"),
                date="Thu, Jul 9, 2026",
                source="open.er-api.com",
            )
        )
        self.assertIn("250 USD", text)
        self.assertIn("23,901.14 INR", text)
        self.assertIn("95.60 INR", text)
        self.assertIn("open.er-api.com", text)
        self.assertIn("Thu, Jul 9, 2026", text)
        self.assertIn("━━━ Currency Conversion ━━━", text)
        self.assertIn("\n\n", text)

    def test_format_result_dollars_ot_rs(self) -> None:
        text = format_result(
            ConversionResult(
                amount=Decimal("250"),
                from_ccy="USD",
                to_ccy="INR",
                rate=Decimal("95.604562"),
                result=Decimal("23901.1405"),
                date="Thu, Jul 9, 2026",
                source="open.er-api.com",
            )
        )
        lines = text.splitlines()
        self.assertEqual(lines[0], "━━━ Currency Conversion ━━━")
        self.assertEqual(lines[1], "")
        self.assertIn("→", lines[2])
        self.assertEqual(lines[3], "")
        self.assertTrue(lines[4].startswith("  Rate:"))
        self.assertTrue(lines[5].startswith("  Source:"))
        self.assertTrue(lines[6].startswith("  As of:"))


class CurrencyRoutingTests(unittest.TestCase):
    def test_symbolic_route_convert(self) -> None:
        hit = route_currency_convert("convert 100 USD to INR")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.split()[0], "currency_convert")

    def test_symbolic_route_dollars_to_rs_typo(self) -> None:
        hit = route_currency_convert("convert 250 dollars ot rs")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.split()[0], "currency_convert")
        self.assertIn("250", hit)
        self.assertIn("USD", hit)
        self.assertIn("INR", hit)

    def test_symbolic_route_what_is(self) -> None:
        hit = route_currency_convert("what is 500 EUR in GBP")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertIn("500", hit)
        self.assertIn("EUR", hit)

    def test_symbolic_route_non_currency(self) -> None:
        self.assertIsNone(route_currency_convert("what is the weather today"))

    def test_symbolic_route_symbols_and_shorthand(self) -> None:
        for query, amount, from_ccy, to_ccy in (
            ("convert $250 to ₹", "250", "USD", "INR"),
            ("250 bucks to rupees", "250", "USD", "INR"),
            ("100 quid to usd", "100", "GBP", "USD"),
            ("£50 to inr", "50", "GBP", "INR"),
            ("convert 1k usd → eur", "1000", "USD", "EUR"),
        ):
            with self.subTest(query=query):
                hit = route_currency_convert(query)
                self.assertIsNotNone(hit)
                assert hit is not None
                self.assertEqual(hit.split()[0], "currency_convert")
                self.assertIn(amount, hit)
                self.assertIn(from_ccy, hit)
                self.assertIn(to_ccy, hit)

    def test_router_symbolic_only(self) -> None:
        for query in (
            "convert 100 USD to INR",
            "convert 250 dollars to rs",
            "convert 250 dollars ot rs",
            "arka convert 100 USD to INR",
            "what is 500 EUR in GBP",
            "currency 50 euros to dollars",
            "convert $250 to ₹",
            "250 bucks to rupees",
            "£50 to inr",
        ):
            with self.subTest(query=query):
                with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
                    result = route(query)
                self.assertIsNotNone(result)
                assert result is not None
                self.assertEqual(result.skill.split()[0], "currency_convert")


if __name__ == "__main__":
    unittest.main()
