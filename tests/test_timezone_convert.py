"""Tests for timezone_convert skill: parsing, routing, and conversion."""

from __future__ import annotations

import os
import unittest
from datetime import datetime
from unittest import mock

from arka.agent.data_ask import route_command as data_ask_route, wants_data_ask
from arka.integrations.timezone_convert import (
    convert_datetime,
    format_result,
    nl_to_argv,
    parse_convert,
    route_command,
    wants_timezone_convert,
)
from arka.router import route
from arka.routing.symbolic import (
    is_timezone_convert_request,
    route_convert,
    route_offline_extras,
    route_timezone_convert,
)


class TimezoneNormalizeTests(unittest.TestCase):
    def test_common_abbreviations(self) -> None:
        from arka.integrations.timezone_convert import normalize_tz

        self.assertEqual(normalize_tz("pdt"), "America/Los_Angeles")
        self.assertEqual(normalize_tz("IST"), "Asia/Kolkata")
        self.assertEqual(normalize_tz("utc"), "UTC")

    def test_iana_passthrough(self) -> None:
        from arka.integrations.timezone_convert import normalize_tz

        self.assertEqual(normalize_tz("Asia/Kolkata"), "Asia/Kolkata")


class TimezoneParseTests(unittest.TestCase):
    def test_pdt_to_ist_with_date(self) -> None:
        parsed = parse_convert("what is this in ist July 13 at 9:00am PDT")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        dt, from_tz, to_tz = parsed
        self.assertEqual(dt, datetime(2026, 7, 13, 9, 0))
        self.assertEqual(from_tz, "America/Los_Angeles")
        self.assertEqual(to_tz, "Asia/Kolkata")

    def test_convert_shorthand(self) -> None:
        parsed = parse_convert("convert 9am PDT to IST")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        _, from_tz, to_tz = parsed
        self.assertEqual(from_tz, "America/Los_Angeles")
        self.assertEqual(to_tz, "Asia/Kolkata")

    def test_date_at_end(self) -> None:
        parsed = parse_convert("July 13 at 9:00am PDT in IST")
        self.assertIsNotNone(parsed)
        assert parsed is not None
        dt, from_tz, to_tz = parsed
        self.assertEqual(dt.month, 7)
        self.assertEqual(dt.day, 13)
        self.assertEqual(from_tz, "America/Los_Angeles")
        self.assertEqual(to_tz, "Asia/Kolkata")

    def test_non_timezone_query(self) -> None:
        self.assertIsNone(parse_convert("list files in data folder"))
        self.assertIsNone(parse_convert("what is 100 USD in INR"))

    def test_current_time_in_city(self) -> None:
        for phrase in (
            "time in tokyo",
            "time now in Tokyo",
            "what time is it in tokyo",
            "what time in tokyo",
        ):
            self.assertTrue(wants_timezone_convert(phrase), phrase)
            parsed = parse_convert(phrase)
            self.assertIsNotNone(parsed, phrase)
            assert parsed is not None
            _, from_tz, to_tz = parsed
            self.assertEqual(to_tz, "Asia/Tokyo")
            self.assertTrue(from_tz)

    def test_current_time_routing(self) -> None:
        hit = route_command("time in tokyo")
        self.assertTrue(hit.startswith("timezone_convert "))
        self.assertIn("Asia/Tokyo", hit)

        hit = route_offline_extras("what time is it in tokyo")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertTrue(hit.startswith("timezone_convert "))

        self.assertFalse(wants_data_ask("what time is it in tokyo"))

    def test_router_time_in_tokyo(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("time in tokyo")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.skill.startswith("timezone_convert "))
        self.assertIn("Asia/Tokyo", result.skill)

    def test_nl_to_argv(self) -> None:
        argv = nl_to_argv("July 13 at 9:00am PDT in IST")
        self.assertEqual(argv[0], "2026-07-13 09:00")
        self.assertEqual(argv[1:4], ["--from", "America/Los_Angeles", "--to"])
        self.assertEqual(argv[4], "Asia/Kolkata")


class TimezoneConvertTests(unittest.TestCase):
    def test_convert_july_13_pdt_to_ist(self) -> None:
        payload = convert_datetime(
            datetime(2026, 7, 13, 9, 0),
            from_tz="PDT",
            to_tz="IST",
        )
        self.assertIn("9:30 PM IST", payload["to_local"])
        self.assertIn("9:00 AM PDT", payload["from_local"])
        rendered = format_result(payload)
        self.assertIn("Timezone Conversion", rendered)
        self.assertIn("PDT", rendered)
        self.assertIn("IST", rendered)


class TimezoneRoutingTests(unittest.TestCase):
    def test_wants_timezone(self) -> None:
        self.assertTrue(wants_timezone_convert("what is this in ist July 13 at 9:00am PDT"))
        self.assertTrue(wants_timezone_convert("convert 9am PDT to IST"))
        self.assertFalse(wants_timezone_convert("what is 100 USD in INR"))

    def test_is_timezone_convert_request(self) -> None:
        self.assertTrue(is_timezone_convert_request("9am PDT to IST"))
        self.assertTrue(is_timezone_convert_request("July 13 at 9:00am PDT to IST"))
        self.assertFalse(is_timezone_convert_request("100 USD to INR"))
        self.assertFalse(is_timezone_convert_request("50 euros to dollars"))

    def test_route_convert_disambiguation(self) -> None:
        tz_hit = route_convert("convert 9am PDT to IST")
        self.assertIsNotNone(tz_hit)
        assert tz_hit is not None
        self.assertTrue(tz_hit.startswith("timezone_convert "))

        cur_hit = route_convert("convert 100 USD to INR")
        self.assertIsNotNone(cur_hit)
        assert cur_hit is not None
        self.assertTrue(cur_hit.startswith("currency_convert "))

        euros_hit = route_convert("50 euros to dollars")
        self.assertIsNotNone(euros_hit)
        assert euros_hit is not None
        self.assertTrue(euros_hit.startswith("currency_convert "))

    def test_route_command(self) -> None:
        hit = route_command("July 13 at 9:00am PDT in IST")
        self.assertTrue(hit.startswith("timezone_convert "))
        self.assertIn("--from", hit)
        self.assertIn("--to", hit)

    def test_symbolic_route(self) -> None:
        hit = route_timezone_convert("what is this in ist July 13 at 9:00am PDT")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertTrue(hit.startswith("timezone_convert "))

    def test_symbolic_beats_data_ask(self) -> None:
        phrase = "what is this in ist July 13 at 9:00am PDT"
        hit = route_offline_extras(phrase)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertTrue(hit.startswith("timezone_convert "))
        self.assertFalse(wants_data_ask(phrase))
        self.assertEqual(data_ask_route(phrase), "")

    def test_symbolic_convert_timezone_beats_currency(self) -> None:
        phrase = "convert July 13 at 9:00am PDT to IST"
        hit = route_offline_extras(phrase)
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertTrue(hit.startswith("timezone_convert "))

    def test_router_symbolic_only(self) -> None:
        phrase = "July 13 at 9:00am PDT in IST"
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route(phrase)
        self.assertIsNotNone(result)
        assert result is not None
        self.assertTrue(result.skill.startswith("timezone_convert "))


class TimezoneCliRoutingTests(unittest.TestCase):
    def test_cli_convert_timezone(self) -> None:
        from arka.cli import _run_convert

        with mock.patch("arka.cli.run_script", return_value=0) as run_script:
            code = _run_convert(["9am", "PDT", "to", "IST"])
        self.assertEqual(code, 0)
        run_script.assert_called_once_with(
            "arka_timezone_convert.py",
            ["convert", "9am", "PDT", "to", "IST"],
        )

    def test_cli_convert_currency(self) -> None:
        from arka.cli import _run_convert

        with mock.patch("arka.cli.run_script", return_value=0) as run_script:
            code = _run_convert(["100", "USD", "to", "INR"])
        self.assertEqual(code, 0)
        run_script.assert_called_once_with(
            "arka_currency.py",
            ["convert", "100", "USD", "to", "INR"],
        )


if __name__ == "__main__":
    unittest.main()
