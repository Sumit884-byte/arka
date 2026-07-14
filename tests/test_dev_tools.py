"""Tests for developer-tools routing and local CI/review helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arka.agent import dev_tools as dt
from arka.router import route


class DevToolsTests(unittest.TestCase):
    def test_route_command(self) -> None:
        self.assertEqual(dt.route_command("arka ci"), "ci")
        self.assertEqual(dt.route_command("arka ci --full"), "ci --full")
        self.assertEqual(dt.route_command("arka ci --fix"), "ci --fix")
        self.assertEqual(dt.route_command("review staged"), "review --staged")
        self.assertEqual(dt.route_command("route audit"), "route_audit")
        self.assertEqual(dt.route_command("skill new my_tool --template dev"), "skill new my_tool --template dev")

    def test_router_symbolic(self) -> None:
        with mock.patch.dict("os.environ", {"ROUTE_MODE": "symbolic_only"}, clear=False):
            self.assertEqual(route("arka ci").skill.split()[0], "ci")
            self.assertEqual(route("review staged").skill.split()[0], "review")
            self.assertEqual(route("route audit").skill.split()[0], "route_audit")

    def test_ci_gates_full_adds_full_pytest(self) -> None:
        names = [gate.name for gate in dt.ci_gates(full=True)]
        self.assertEqual(names[:2], ["ruff", "pytest"])
        self.assertIn("pytest-full", names)

    def test_review_hints(self) -> None:
        text = dt._security_and_test_gap_hints("shell=True route parser", ["src/arka/cli.py"])
        self.assertTrue(any("security" in hint for hint in text))
        self.assertTrue(any("test-gap" in hint for hint in text))

    def test_scaffold_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = dt.scaffold_skill(root, name="my_tool", template="dev")
            self.assertTrue((target / "skill.json").is_file())
            self.assertTrue((target / "run.py").is_file())
            self.assertTrue((target / "README.md").is_file())


if __name__ == "__main__":
    unittest.main()
