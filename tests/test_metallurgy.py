"""Tests for Arka metallurgy skill."""

from __future__ import annotations

import unittest
from unittest.mock import patch

from arka.agent.metallurgy import nl_to_argv
from arka.routing.symbolic import route_metallurgy


class TestMetallurgyNlToArgv(unittest.TestCase):
    def test_properties_steel_304(self) -> None:
        self.assertEqual(
            nl_to_argv("properties of steel 304"),
            ["properties", "steel 304"],
        )

    def test_alloy_composition_brass(self) -> None:
        self.assertEqual(
            nl_to_argv("alloy composition brass"),
            ["composition", "brass"],
        )

    def test_heat_treatment_aluminum(self) -> None:
        self.assertEqual(
            nl_to_argv("heat treatment steps for aluminum"),
            ["heat", "aluminum"],
        )

    def test_metallurgy_direct(self) -> None:
        self.assertEqual(
            nl_to_argv("metallurgy properties 316"),
            ["properties", "316"],
        )

    def test_not_chemistry_lab(self) -> None:
        self.assertEqual(nl_to_argv("steps to run a PCR protocol"), [])


class TestMetallurgyLookup(unittest.TestCase):
    def test_lookup_304(self) -> None:
        from arka.agent.metallurgy import _load_lib

        lib = _load_lib()
        out = lib.lookup_alloy("304")
        self.assertIn("304", out)
        self.assertIn("Cr", out)

    def test_composition_brass(self) -> None:
        from arka.agent.metallurgy import _load_lib

        lib = _load_lib()
        out = lib.lookup_composition("brass")
        self.assertIn("Cu", out)
        self.assertIn("Zn", out)

    def test_heat_treatment_bundled(self) -> None:
        from arka.agent.metallurgy import _load_lib

        lib = _load_lib()
        out = lib.lookup_heat_treatment("heat treatment aluminum 6061")
        self.assertIn("6061", out)
        self.assertIn("## Steps", out)


class TestMetallurgyRouting(unittest.TestCase):
    def test_route_properties(self) -> None:
        hit = route_metallurgy("properties of steel 304")
        self.assertEqual(hit, "metallurgy properties 'steel 304'")

    def test_route_heat(self) -> None:
        hit = route_metallurgy("heat treatment steps for aluminum")
        self.assertEqual(hit, "metallurgy heat aluminum")


class TestMetallurgyApiFallback(unittest.TestCase):
    def test_alloyfyi_used_when_no_bundled_match(self) -> None:
        from arka.agent.metallurgy import _load_lib

        lib = _load_lib()
        fake = {
            "name": "Test Alloy",
            "family_name": "Test",
            "composition": {"Fe": "100%"},
            "tensile_strength_mpa": "500",
            "description": "Remote alloy.",
        }
        with patch.object(lib, "match_alloy", return_value=None):
            with patch.object(lib, "fetch_alloyfyi", return_value=fake):
                out = lib.lookup_alloy("obscure-alloy-xyz")
        self.assertIn("Test Alloy", out)
        self.assertIn("AlloyFYI", out)


if __name__ == "__main__":
    unittest.main()
