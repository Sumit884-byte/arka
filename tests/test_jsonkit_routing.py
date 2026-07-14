"""Tests for jsonkit NL routing."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path

from arka.core import jsonkit as jk
from arka.router import route
from arka.routing.symbolic import route_offline_extras


class JsonkitRoutingTests(unittest.TestCase):
    def test_wants_jsonkit(self) -> None:
        self.assertTrue(jk.wants_jsonkit("validate json package.json"))
        self.assertTrue(jk.wants_jsonkit("pretty print json"))
        self.assertFalse(jk.wants_jsonkit("check repo health"))

    def test_route_validate_and_pretty(self) -> None:
        self.assertEqual(jk.route_command("validate json config.json"), "jsonkit validate config.json")
        self.assertEqual(jk.route_command("pretty print json data.json"), "jsonkit pretty data.json")
        self.assertEqual(jk.route_command("minify json out.json"), "jsonkit minify out.json")

    def test_json_input_reads_file(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.json"
            path.write_text('{"ok": true}', encoding="utf-8")
            payload = jk.validate_payload(jk._json_input(str(path)))
        self.assertTrue(payload["valid"])

    def test_symbolic_extras(self) -> None:
        hit = route_offline_extras("validate json package.json")
        self.assertEqual(hit, "jsonkit validate package.json")

    def test_router_symbolic(self) -> None:
        with unittest.mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("pretty print json config.json")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "jsonkit")


if __name__ == "__main__":
    unittest.main()
