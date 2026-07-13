"""Tests for optimized llm.txt repo context skill."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arka.agent import repo_context as rc
from arka.router import route


class RepoContextTests(unittest.TestCase):
    def test_wants_repo_context(self) -> None:
        self.assertTrue(rc.wants_repo_context("how does arka routing work"))
        self.assertTrue(rc.wants_repo_context("where is symbolic.py in the codebase"))
        self.assertTrue(rc.wants_repo_context("explore the codebase"))
        self.assertTrue(rc.wants_repo_context("what files changed"))
        self.assertFalse(rc.wants_repo_context("map this repo"))
        self.assertFalse(rc.wants_repo_context("deep project structure map"))
        self.assertFalse(rc.wants_repo_context("weather in mumbai"))

    def test_route_command(self) -> None:
        self.assertEqual(
            rc.route_command("how is arka organized"),
            "repo_context show how is arka organized",
        )
        self.assertEqual(rc.route_command("map this repo"), "")

    def test_parse_sections(self) -> None:
        text = (
            "================================================================================\n"
            "AGENT RULES\n"
            "================================================================================\n\n"
            "rule one\n\n"
            "================================================================================\n"
            "ARCHITECTURE\n"
            "================================================================================\n\n"
            "router here\n"
        )
        sections = rc.parse_sections(text)
        self.assertIn("AGENT RULES", sections)
        self.assertIn("ARCHITECTURE", sections)
        self.assertIn("rule one", sections["AGENT RULES"])

    def test_query_context_prefers_llm_txt(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            llm = root / "llm.txt"
            llm.write_text(
                "================================================================================\n"
                "AGENT RULES\n"
                "================================================================================\n\n"
                "Read ONLY this file.\n\n"
                "================================================================================\n"
                "ARCHITECTURE\n"
                "================================================================================\n\n"
                "routing/symbolic.py handles offline NL routes.\n",
                encoding="utf-8",
            )
            out = rc.query_context("how does routing work", root=root)
            self.assertIn("AGENT RULES", out)
            self.assertIn("routing/symbolic.py", out)

    def test_sync_index_appends_changelog(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git").mkdir()
            llm = root / "llm.txt"
            llm.write_text(
                "header\n\n"
                "================================================================================\n"
                "RECENT FILE CHANGES (CHANGELOG)\n"
                "================================================================================\n\n"
                "(no indexed changes yet)\n\n"
                "================================================================================\n"
                "END\n"
                "================================================================================\n",
                encoding="utf-8",
            )
            (root / "src").mkdir()
            (root / "src" / "demo.py").write_text("print('hi')\n", encoding="utf-8")

            with mock.patch.object(rc, "_head_commit", return_value="abc123def456"):
                with mock.patch.object(
                    rc,
                    "git_changed_since",
                    return_value=[("M", "src/demo.py")],
                ):
                    with mock.patch.object(rc, "_save_global_index"):
                        result = rc.sync_index(root, quiet=True)

            self.assertTrue(result.get("ok"))
            updated = llm.read_text(encoding="utf-8")
            self.assertIn("modified src/demo.py", updated)
            local = json.loads((root / ".arka-index").read_text(encoding="utf-8"))
            self.assertEqual(local["last_commit"], "abc123def456")

    def test_router_symbolic(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("how does arka routing work")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "repo_context")


if __name__ == "__main__":
    unittest.main()
