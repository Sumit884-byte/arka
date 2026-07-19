"""Tests for Arka astronomy skill."""

from __future__ import annotations

import unittest
from datetime import datetime, timezone
from unittest.mock import patch

from arka.agent.astronomy import nl_to_argv
from arka.routing.symbolic import route_astronomy


class TestAstronomyNlToArgv(unittest.TestCase):
    def test_what_is_betelgeuse(self) -> None:
        self.assertEqual(nl_to_argv("what is Betelgeuse"), ["what", "Betelgeuse"])

    def test_moon_phase_tonight(self) -> None:
        self.assertEqual(nl_to_argv("moon phase tonight"), ["moon"])

    def test_iss_pass_times(self) -> None:
        self.assertEqual(nl_to_argv("ISS pass times"), ["iss"])

    def test_astronomy_direct(self) -> None:
        self.assertEqual(nl_to_argv("astronomy what Mars"), ["what", "Mars"])

    def test_batch_catalog_routes(self) -> None:
        self.assertEqual(nl_to_argv("list all planets and galaxies"), ["list", "all"])
        self.assertEqual(nl_to_argv("show planets"), ["list", "planets"])
        self.assertEqual(nl_to_argv("list galaxies"), ["list", "galaxies"])

    def test_what_star_is_sirius(self) -> None:
        self.assertEqual(nl_to_argv("what star is Sirius"), ["what", "Sirius"])

    def test_not_weather(self) -> None:
        self.assertEqual(nl_to_argv("weather forecast"), [])


class TestAstronomyLookup(unittest.TestCase):
    def test_lookup_betelgeuse(self) -> None:
        from arka.agent.astronomy import _load_lib

        lib = _load_lib()
        out = lib.lookup_object("Betelgeuse")
        self.assertIn("Betelgeuse", out)
        self.assertIn("Orion", out)

    def test_moon_phase_local(self) -> None:
        from arka.agent.astronomy import _load_lib

        lib = _load_lib()
        info = lib.moon_phase(datetime(2024, 1, 11, 12, 0, tzinfo=timezone.utc))
        self.assertIn("phase_name", info)
        self.assertGreater(info["illumination_percent"], 0)


class TestAstronomyRouting(unittest.TestCase):
    def test_route_moon(self) -> None:
        hit = route_astronomy("moon phase tonight")
        self.assertEqual(hit, "astronomy moon")

    def test_route_betelgeuse(self) -> None:
        hit = route_astronomy("what is Betelgeuse")
        self.assertEqual(hit, "astronomy what Betelgeuse")


class TestAstronomyIssOffline(unittest.TestCase):
    def test_iss_report_offline_fallback(self) -> None:
        from arka.agent.astronomy import _load_lib

        lib = _load_lib()
        with patch.object(lib, "fetch_iss_position", return_value=None):
            with patch.object(lib, "fetch_iss_passes", return_value=None):
                out = lib.format_iss_report("28.6,77.2")
        self.assertIn("unavailable", out.lower())


if __name__ == "__main__":
    unittest.main()
