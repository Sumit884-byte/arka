"""Tests for user-facing output helpers and debug gating."""

from __future__ import annotations

import io
import os
import tempfile
import unittest
from contextlib import redirect_stderr
from pathlib import Path
from unittest import mock

from arka.core import output
from arka.core.mode import set_mode


class OutputHelperTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = os.path.join(self.tmp.name, "arka")
        os.makedirs(self.config, exist_ok=True)
        self.mode_patch = mock.patch("arka.core.mode.config_dir")
        self.mock_config_dir = self.mode_patch.start()
        self.addCleanup(self.mode_patch.stop)
        from pathlib import Path

        self.mock_config_dir.return_value = Path(self.config)
        os.environ.pop("ARKA_MODE", None)

    def test_summarize_pytest_ok(self) -> None:
        self.assertEqual(output.summarize_pytest("12 passed in 1.2s", passed=True), "OK")

    def test_summarize_pytest_import_error(self) -> None:
        text = (
            "FAILED tests/test_memory_detect.py\n"
            "ImportError: cannot import name 'foo' from 'arka.core.memory_detect'"
        )
        summary = output.summarize_pytest(text, passed=False)
        self.assertIn("1 failure", summary)
        self.assertIn("foo", summary)

    def test_summarize_goal_truncates(self) -> None:
        long_goal = "Improve the Arka codebase " + ("x" * 200)
        short = output.summarize_goal(long_goal)
        self.assertLessEqual(len(short), 80)
        self.assertTrue(short.endswith("…"))

    def test_summarize_goal_strips_llm_context(self) -> None:
        goal = "Improve the Arka codebase. === llm.txt context === PROJECT SUMMARY secret stuff"
        short = output.summarize_goal(goal)
        self.assertEqual(short, "Improve the Arka codebase.")

    def test_debug_msg_silent_in_agent_mode(self) -> None:
        set_mode("agent")
        buf = io.StringIO()
        with redirect_stderr(buf):
            output.debug_msg("secret diagnostics")
        self.assertEqual(buf.getvalue(), "")

    def test_debug_msg_shown_in_debug_mode(self) -> None:
        set_mode("debug")
        buf = io.StringIO()
        with redirect_stderr(buf):
            output.debug_msg("secret diagnostics")
        self.assertIn("secret diagnostics", buf.getvalue())

    def test_user_msg_always_prints(self) -> None:
        set_mode("agent")
        buf = io.StringIO()
        with redirect_stderr(buf):
            output.user_msg("visible status")
        self.assertIn("visible status", buf.getvalue())


class SelfImproveOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "arka"
        self.root.mkdir()
        (self.root / "pyproject.toml").write_text("[project]\nname='arka'\n", encoding="utf-8")
        (self.root / "llm.txt").write_text(
            "PROJECT SUMMARY\nArka is an agent.\n"
            "ARCHITECTURE\nmodules: cli, agent\n"
            "AGENT RULES\n- read llm.txt\n",
            encoding="utf-8",
        )
        (self.root / "src" / "arka").mkdir(parents=True)
        self.config = Path(self.tmp.name) / "config"
        self.config.mkdir(parents=True, exist_ok=True)
        self.mode_patch = mock.patch("arka.core.mode.config_dir")
        self.mock_config_dir = self.mode_patch.start()
        self.addCleanup(self.mode_patch.stop)
        self.mock_config_dir.return_value = self.config
        os.environ.pop("ARKA_MODE", None)
        set_mode("agent")

    def test_plan_output_excludes_llm_sections(self) -> None:
        from arka.agent import self_improve

        diag = self_improve.DiagnosticResult(
            "pytest -q",
            1,
            "FAILED tests/test_x.py\nImportError: cannot import name 'missing'",
        )
        plan = self_improve.ImprovementPlan(
            focus="general",
            proposal="fix import in tests/test_x.py",
            analyzed=["diag"],
        )
        out = self_improve.format_plan_output(
            plan,
            apply=False,
            diag=diag,
            routing_notes=[],
            target="",
        )
        self.assertIn("━━━ Arka Self-Improve", out)
        self.assertNotIn("PROJECT SUMMARY", out)
        self.assertNotIn("ARCHITECTURE", out)
        self.assertIn("fix import", out)

    def test_run_self_improve_stdout_clean(self) -> None:
        from arka.agent import self_improve

        diag = self_improve.DiagnosticResult("pytest -q", 0, "passed")
        plan = self_improve.ImprovementPlan(focus="routing", proposal="sync routes", analyzed=["x"])
        stdout = io.StringIO()
        stderr = io.StringIO()
        with (
            mock.patch("arka.agent.self_improve.arka_repo_root", return_value=self.root),
            mock.patch("arka.core.code_project.config_dir", return_value=self.config),
            mock.patch("arka.agent.self_improve.run_diagnostics", return_value=diag),
            mock.patch("arka.agent.self_improve.generate_plan", return_value=plan),
            mock.patch("arka.agent.self_improve.record_attempt"),
            redirect_stderr(stderr),
        ):
            os.environ.pop("ARKA_CODE_PROJECT", None)
            with mock.patch("sys.stdout", stdout):
                rc = self_improve.run_self_improve("routing", apply=False)
        self.assertEqual(rc, 0)
        combined = stdout.getvalue() + stderr.getvalue()
        self.assertNotIn("PROJECT SUMMARY", combined)
        self.assertNotIn("ARCHITECTURE", combined)
        self.assertNotIn("Goal agent:", combined)

    def test_run_self_improve_debug_shows_internal_status(self) -> None:
        from arka.agent import self_improve

        set_mode("debug")
        diag = self_improve.DiagnosticResult("pytest -q", 0, "passed")
        plan = self_improve.ImprovementPlan(focus="general", proposal="ok", analyzed=["x"])
        stderr = io.StringIO()
        with (
            mock.patch("arka.agent.self_improve.arka_repo_root", return_value=self.root),
            mock.patch("arka.core.code_project.config_dir", return_value=self.config),
            mock.patch("arka.agent.self_improve.run_diagnostics", return_value=diag),
            mock.patch("arka.agent.self_improve.generate_plan", return_value=plan),
            mock.patch("arka.agent.self_improve.record_attempt"),
            redirect_stderr(stderr),
        ):
            os.environ.pop("ARKA_CODE_PROJECT", None)
            rc = self_improve.run_self_improve("", apply=False)
        self.assertEqual(rc, 0)
        err = stderr.getvalue()
        self.assertIn("Arka self-improve", err)
        self.assertIn("plan-only", err)


class GoalOutputTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = os.path.join(self.tmp.name, "arka")
        os.makedirs(self.config, exist_ok=True)
        self.mode_patch = mock.patch("arka.core.mode.config_dir")
        self.mock_config_dir = self.mode_patch.start()
        self.addCleanup(self.mode_patch.stop)
        from pathlib import Path

        self.mock_config_dir.return_value = Path(self.config)
        os.environ.pop("ARKA_MODE", None)

    def test_goal_agent_hides_full_prompt_in_normal_mode(self) -> None:
        from arka.agent.goal import run_goal

        set_mode("agent")
        huge_goal = (
            "Improve the Arka codebase. === llm.txt === PROJECT SUMMARY " + ("x" * 500)
        )
        stderr = io.StringIO()
        with (
            mock.patch("arka.agent.goal._llm", return_value='{"status":"done","cmd":"","why":"done"}'),
            mock.patch("arka.agent.goal._dir_context", return_value=("", "")),
            mock.patch("arka.agent.goal._fish_history", return_value=""),
            mock.patch("arka.agent.goal._skills_list", return_value="test"),
            redirect_stderr(stderr),
        ):
            os.chdir(self.tmp.name)
            rc = run_goal(huge_goal, max_steps=1)
        self.assertEqual(rc, 0)
        err = stderr.getvalue()
        self.assertNotIn("PROJECT SUMMARY", err)
        self.assertIn("Goal agent:", err)

    def test_goal_agent_shows_full_prompt_in_debug_mode(self) -> None:
        from arka.agent.goal import run_goal

        set_mode("debug")
        huge_goal = "Improve the Arka codebase.\n=== llm.txt ===\nPROJECT SUMMARY\nsecret"
        stderr = io.StringIO()
        with (
            mock.patch("arka.agent.goal._llm", return_value='{"status":"done","cmd":"","why":"done"}'),
            mock.patch("arka.agent.goal._dir_context", return_value=("", "")),
            mock.patch("arka.agent.goal._fish_history", return_value=""),
            mock.patch("arka.agent.goal._skills_list", return_value="test"),
            redirect_stderr(stderr),
        ):
            os.chdir(self.tmp.name)
            rc = run_goal(huge_goal, max_steps=1)
        self.assertEqual(rc, 0)
        err = stderr.getvalue()
        self.assertIn("PROJECT SUMMARY", err)


if __name__ == "__main__":
    unittest.main()
