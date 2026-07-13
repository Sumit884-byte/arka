"""Tests for Arka self-improvement loop."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arka.agent import self_improve
from arka.routing.symbolic import route_offline_extras


class SelfImproveRepoTests(unittest.TestCase):
    def test_is_arka_repo(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            self.assertFalse(self_improve._is_arka_repo(root))
            (root / "pyproject.toml").write_text("[project]\n", encoding="utf-8")
            (root / "llm.txt").write_text("# test\n", encoding="utf-8")
            (root / "src" / "arka").mkdir(parents=True)
            self.assertTrue(self_improve._is_arka_repo(root))

    def test_arka_repo_root_from_checkout(self) -> None:
        real_root = Path(__file__).resolve().parents[1]
        with mock.patch("arka.paths.checkout_root", return_value=real_root):
            detected = self_improve.arka_repo_root()
        self.assertEqual(detected, real_root.resolve())


class SelfImproveRoutingTests(unittest.TestCase):
    def test_route_command_phrases(self) -> None:
        cases = (
            ("improve arka", "self_improve"),
            ("self improve", "self_improve"),
            ("arka improve itself", "self_improve"),
            ("loop to fix arka", "self_improve"),
            ("loop self fix failing tests", "self_improve fix failing tests"),
            ("self improve add tests for repo_context", "self_improve add tests for repo_context"),
        )
        for phrase, expected in cases:
            with self.subTest(phrase=phrase):
                hit = self_improve.route_command(phrase)
                self.assertEqual(hit, expected, msg=f"{phrase!r} -> {hit!r}")

    def test_symbolic_extras_routes_self_improve(self) -> None:
        hit = route_offline_extras("improve arka")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.split()[0], "self_improve")


class SelfImproveGoalTests(unittest.TestCase):
    def test_build_goal_includes_context_and_diag(self) -> None:
        root = Path("/tmp/arka")
        diag = self_improve.DiagnosticResult("pytest -q", 1, "FAILED tests/test_x.py")
        goal = self_improve.build_goal(
            "fix tests",
            context="AGENT RULES\n- read llm.txt",
            diag=diag,
            root=root,
        )
        self.assertIn("fix tests", goal)
        self.assertIn("AGENT RULES", goal)
        self.assertIn("FAILED tests/test_x.py", goal)

    def test_git_blocklist_hook(self) -> None:
        blocked = self_improve._git_blocklist_hook("git commit -m 'oops'")
        self.assertIsNotNone(blocked)
        assert blocked is not None
        self.assertEqual(blocked[0], 2)
        allowed = self_improve._git_blocklist_hook("git status")
        self.assertIsNone(allowed)


class SelfImproveLoopTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "arka"
        self.root.mkdir()
        (self.root / "pyproject.toml").write_text("[project]\nname='arka'\n", encoding="utf-8")
        (self.root / "llm.txt").write_text(
            "AGENT RULES\n- read llm.txt\nRECENT FILE CHANGES\n(none)\n",
            encoding="utf-8",
        )
        (self.root / "src" / "arka").mkdir(parents=True)
        self.config = Path(self.tmp.name) / "config"
        self.config.mkdir(parents=True, exist_ok=True)

    def test_ensure_arka_project_auto_init(self) -> None:
        with (
            mock.patch("arka.agent.self_improve.arka_repo_root", return_value=self.root),
            mock.patch("arka.core.code_project.config_dir", return_value=self.config),
        ):
            os.environ.pop("ARKA_CODE_PROJECT", None)
            resolved = self_improve.ensure_arka_project(auto_init=True)
        self.assertEqual(resolved, self.root.resolve())

    def test_run_self_improve_passing_diag_short_circuit(self) -> None:
        diag = self_improve.DiagnosticResult("pytest -q", 0, "passed")
        with (
            mock.patch("arka.agent.self_improve.arka_repo_root", return_value=self.root),
            mock.patch("arka.core.code_project.config_dir", return_value=self.config),
            mock.patch("arka.agent.self_improve.run_diagnostics", return_value=diag),
            mock.patch("arka.agent.goal.run_goal") as mock_goal,
        ):
            os.environ.pop("ARKA_CODE_PROJECT", None)
            rc = self_improve.run_self_improve("", max_rounds=1, max_steps=5)
        self.assertEqual(rc, 0)
        mock_goal.assert_not_called()

    def test_run_self_improve_invokes_goal_on_failure(self) -> None:
        diag_fail = self_improve.DiagnosticResult("pytest -q", 1, "1 failed")
        diag_ok = self_improve.DiagnosticResult("pytest -q", 0, "ok")
        with (
            mock.patch("arka.agent.self_improve.arka_repo_root", return_value=self.root),
            mock.patch("arka.core.code_project.config_dir", return_value=self.config),
            mock.patch(
                "arka.agent.self_improve.run_diagnostics",
                side_effect=[diag_fail, diag_ok],
            ),
            mock.patch("arka.agent.goal.run_goal", return_value=0) as mock_goal,
            mock.patch("arka.agent.self_improve._sync_changelog"),
        ):
            os.environ.pop("ARKA_CODE_PROJECT", None)
            rc = self_improve.run_self_improve("fix tests", max_rounds=1, max_steps=3)
        self.assertEqual(rc, 0)
        mock_goal.assert_called_once()
        call_kwargs = mock_goal.call_args.kwargs
        self.assertIn("SELF-IMPROVEMENT MODE", call_kwargs.get("system_extra", ""))
        self.assertIs(call_kwargs.get("cmd_hook"), self_improve._git_blocklist_hook)

    def test_run_self_improve_requires_agent_mode(self) -> None:
        with mock.patch("arka.core.mode.get_mode", return_value="ask"):
            rc = self_improve.run_self_improve()
        self.assertEqual(rc, 1)


if __name__ == "__main__":
    unittest.main()
