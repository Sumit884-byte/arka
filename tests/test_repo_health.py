"""Tests for repo health skill."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arka.agent import repo_health as rh
from arka.router import route


class RepoHealthTests(unittest.TestCase):
    def test_wants_repo_health(self) -> None:
        self.assertTrue(rh.wants_repo_health("check repo health"))
        self.assertTrue(rh.wants_repo_health("run project tests"))
        self.assertFalse(rh.wants_repo_health("weather in mumbai"))

    def test_detect_pytest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
            (root / "tests").mkdir()
            with mock.patch.object(rh, "shutil_which", return_value="/usr/bin/pytest"):
                checks = rh.detect_checks(root)
            names = [c.name for c in checks]
            self.assertIn("pytest", names)

    def test_scan_text_lists_checks(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text('{"scripts":{"test":"jest","lint":"eslint ."}}', encoding="utf-8")
            text = rh.scan_text(root)
            self.assertIn("npm test", text)
            self.assertIn("npm run lint", text)

    def test_scan_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text(
                '{"scripts":{"test":"jest","lint":"eslint ."}}', encoding="utf-8"
            )
            payload = rh.scan_payload(root)
            self.assertEqual(payload["path"], str(root.resolve()))
            names = [c["name"] for c in payload["checks"]]
            self.assertIn("npm test", names)

    def test_route_scan_and_run(self) -> None:
        self.assertEqual(rh.route_command("repo health check"), "repo_health scan")
        self.assertEqual(rh.route_command("run project tests"), "repo_health run --test")

    def test_router_symbolic(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("check repo health")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "repo_health")


if __name__ == "__main__":
    unittest.main()
