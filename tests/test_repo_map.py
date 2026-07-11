"""Tests for repo map skill."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arka.agent import repo_map as rm
from arka.router import route


class RepoMapTests(unittest.TestCase):
    def test_wants_repo_map(self) -> None:
        self.assertTrue(rm.wants_repo_map("map this repo"))
        self.assertTrue(rm.wants_repo_map("show project structure"))
        self.assertFalse(rm.wants_repo_map("weather in mumbai"))

    def test_detect_project_types(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
            (root / "package.json").write_text("{}", encoding="utf-8")
            types = rm.detect_project_types(root)
            self.assertIn("Python", types)
            self.assertIn("Node.js", types)

    def test_tree_skips_ignored_dirs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "src").mkdir()
            (root / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
            (root / "node_modules").mkdir()
            (root / "node_modules" / "pkg").mkdir()
            lines = rm.tree_lines(root, depth=2)
            joined = "\n".join(lines)
            self.assertIn("src/", joined)
            self.assertNotIn("node_modules", joined)

    def test_extract_symbols(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            path = Path(tmp) / "sample.py"
            path.write_text(
                "class Widget:\n    pass\n\ndef run():\n    pass\n\ndef _private():\n    pass\n",
                encoding="utf-8",
            )
            info = rm.extract_symbols(path)
            self.assertIsNotNone(info)
            assert info is not None
            self.assertIn("Widget", info.classes)
            self.assertIn("run", info.functions)
            self.assertNotIn("_private", info.functions)

    def test_map_text_includes_layout(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "README.md").write_text("# demo", encoding="utf-8")
            text = rm.map_text(root, include_symbols=False)
            self.assertIn("Repo map:", text)
            self.assertIn("README.md", text)

    def test_route_command(self) -> None:
        self.assertEqual(rm.route_command("repo map"), "repo_map --symbols")
        self.assertEqual(rm.route_command("deep project structure"), "repo_map --depth 3 --symbols")

    def test_router_symbolic(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("map this repo")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "repo_map")


if __name__ == "__main__":
    unittest.main()
