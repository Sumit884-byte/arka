"""Tests for language-agnostic lint project helper."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arka.agent import lint_project as lp
from arka.router import route


class LintProjectTests(unittest.TestCase):
    def test_route_command(self) -> None:
        self.assertEqual(lp.route_command("lint this repo"), "lint_project")
        self.assertEqual(lp.route_command("lint this project --full"), "lint_project --full")
        self.assertEqual(lp.route_command("lint this codebase --fix"), "lint_project --fix")

    def test_router_symbolic(self) -> None:
        with mock.patch.dict("os.environ", {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("lint this repo")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "lint_project")

    def test_detects_package_json_lint(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{"scripts":{"lint":"eslint ."}}', encoding="utf-8")
            checks = lp.detect_checks(root)
            self.assertTrue(any(chk.name == "npm run lint" for chk in checks))

    def test_run_lint_prefers_lint_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{"scripts":{"lint":"eslint ."}}', encoding="utf-8")
            with mock.patch("arka.agent.lint_project._run", return_value=(0, "ok", "")) as run:
                payload = lp.run_lint(root)
            self.assertTrue(payload["ok"])
            self.assertTrue(run.called)


if __name__ == "__main__":
    unittest.main()
