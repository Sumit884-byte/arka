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
            ("self memory", "self_improve memory"),
            ("self status", "self_improve status"),
            ("arka improve itself", "self_improve"),
            ("loop to fix arka", "self_improve"),
            ("loop self fix failing tests", "self_improve fix failing tests"),
            ("self improve add tests for repo_context", "self_improve add tests for repo_context"),
            ("self improve arka quiz memory", "self_improve quiz memory"),
            ("improve arka llm fallback", "self_improve llm fallback"),
            ("arka self improve routing", "self_improve routing"),
            ("self improve routing", "self_improve routing"),
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

    def test_build_goal_includes_plan(self) -> None:
        root = Path("/tmp/arka")
        plan = self_improve.ImprovementPlan(
            focus="routing",
            proposal="add timezone guard",
            files=["src/arka/agent/data_ask.py"],
            tests=["pytest -q tests/test_data_ask.py"],
        )
        goal = self_improve.build_goal(
            "routing",
            context="ctx",
            diag=None,
            root=root,
            plan=plan,
        )
        self.assertIn("add timezone guard", goal)
        self.assertIn("data_ask.py", goal)

    def test_git_blocklist_hook(self) -> None:
        blocked = self_improve._git_blocklist_hook("git commit -m 'oops'")
        self.assertIsNotNone(blocked)
        assert blocked is not None
        self.assertEqual(blocked[0], 2)
        allowed = self_improve._git_blocklist_hook("git status")
        self.assertIsNone(allowed)

    def test_blocks_env_writes(self) -> None:
        blocked = self_improve._git_blocklist_hook("echo x >> .env")
        self.assertIsNotNone(blocked)

    def test_run_diagnostics_scopes_to_tests_dir(self) -> None:
        import inspect

        src = inspect.getsource(self_improve.run_diagnostics)
        self.assertIn("pytest -q tests/", src)


class SelfImprovePlanTests(unittest.TestCase):
    def test_format_plan_output_dry_run(self) -> None:
        plan = self_improve.ImprovementPlan(
            focus="routing",
            analyzed=["symbolic.py (12 handlers)"],
            proposal="add guard in data_ask",
            files=["src/arka/agent/data_ask.py"],
            tests=["pytest -q tests/test_data_ask.py"],
        )
        diag = self_improve.DiagnosticResult("pytest -q", 0, "passed")
        out = self_improve.format_plan_output(
            plan,
            apply=False,
            diag=diag,
            routing_notes=["symbolic.py (40 route_* handlers)"],
            target="routing",
        )
        self.assertIn("━━━ Arka Self-Improve", out)
        self.assertIn("--apply", out)
        self.assertIn("add guard in data_ask", out)
        self.assertNotIn("running goal agent", out)
        self.assertNotIn("PROJECT SUMMARY", out)

    def test_heuristic_plan_for_routing(self) -> None:
        real_root = Path(__file__).resolve().parents[1]
        plan = self_improve._heuristic_plan(
            "routing",
            context="AGENT RULES\n",
            diag=self_improve.DiagnosticResult("pytest", 0, "ok"),
            routing_notes=["symbolic.py (40 route_* handlers)"],
            root=real_root,
        )
        self.assertEqual(plan.focus, "routing")
        self.assertTrue(plan.files)
        self.assertIn("symbolic.py", plan.analyzed[0])

    def test_parse_plan_json(self) -> None:
        raw = '{"focus":"llm","analyzed":["fallback.py"],"proposal":"fix retry","files":["src/arka/llm/fallback.py"],"tests":["pytest -q"]}'
        plan = self_improve._parse_plan_json(raw)
        self.assertIsNotNone(plan)
        assert plan is not None
        self.assertEqual(plan.focus, "llm")
        self.assertEqual(plan.proposal, "fix retry")

    def test_memory_record_and_load(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            mem = Path(tmp) / "self-improve-memory.json"
            with mock.patch("arka.agent.self_improve.memory_path", return_value=mem):
                plan = self_improve.ImprovementPlan(focus="test", proposal="do thing", files=["a.py"])
                self_improve.record_attempt(plan, outcome="planned")
                data = self_improve.load_memory()
                self.assertEqual(len(data["attempts"]), 1)
                ctx = self_improve.recent_attempts_context("test")
                self.assertIn("do thing", ctx)


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

    def test_run_self_improve_plan_only_skips_goal(self) -> None:
        diag = self_improve.DiagnosticResult("pytest -q", 0, "passed")
        plan = self_improve.ImprovementPlan(focus="general", proposal="ok", analyzed=["x"])
        with (
            mock.patch("arka.agent.self_improve.arka_repo_root", return_value=self.root),
            mock.patch("arka.core.code_project.config_dir", return_value=self.config),
            mock.patch("arka.agent.self_improve.run_diagnostics", return_value=diag),
            mock.patch("arka.agent.self_improve.generate_plan", return_value=plan),
            mock.patch("arka.agent.self_improve.record_attempt"),
            mock.patch("arka.agent.goal.run_goal") as mock_goal,
        ):
            os.environ.pop("ARKA_CODE_PROJECT", None)
            rc = self_improve.run_self_improve("", max_rounds=1, max_steps=5, apply=False)
        self.assertEqual(rc, 0)
        mock_goal.assert_not_called()

    def test_run_self_improve_apply_invokes_goal_on_failure(self) -> None:
        diag_fail = self_improve.DiagnosticResult("pytest -q", 1, "1 failed")
        diag_ok = self_improve.DiagnosticResult("pytest -q", 0, "ok")
        plan = self_improve.ImprovementPlan(
            focus="fix tests",
            proposal="fix it",
            files=["tests/test_x.py"],
            analyzed=["diag"],
        )
        with (
            mock.patch("arka.agent.self_improve.arka_repo_root", return_value=self.root),
            mock.patch("arka.core.code_project.config_dir", return_value=self.config),
            mock.patch("arka.core.mode.get_mode", return_value="agent"),
            mock.patch(
                "arka.agent.self_improve.run_diagnostics",
                side_effect=[diag_fail, diag_fail, diag_ok],
            ),
            mock.patch("arka.agent.self_improve.generate_plan", return_value=plan),
            mock.patch("arka.agent.goal.run_goal", return_value=0) as mock_goal,
            mock.patch("arka.agent.self_improve._sync_changelog"),
            mock.patch("arka.agent.self_improve.record_attempt"),
        ):
            os.environ.pop("ARKA_CODE_PROJECT", None)
            rc = self_improve.run_self_improve("fix tests", max_rounds=1, max_steps=3, apply=True)
        self.assertEqual(rc, 0)
        mock_goal.assert_called_once()
        call_kwargs = mock_goal.call_args.kwargs
        self.assertIn("SELF-IMPROVEMENT MODE", call_kwargs.get("system_extra", ""))
        self.assertIs(call_kwargs.get("cmd_hook"), self_improve._git_blocklist_hook)

    def test_run_self_improve_apply_requires_agent_mode(self) -> None:
        with mock.patch("arka.core.mode.get_mode", return_value="ask"):
            rc = self_improve.run_self_improve(apply=True)
        self.assertEqual(rc, 1)

    def test_plan_only_works_in_ask_mode(self) -> None:
        diag = self_improve.DiagnosticResult("pytest -q", 0, "passed")
        plan = self_improve.ImprovementPlan(focus="routing", proposal="x", analyzed=["y"])
        with (
            mock.patch("arka.core.mode.get_mode", return_value="ask"),
            mock.patch("arka.agent.self_improve.arka_repo_root", return_value=self.root),
            mock.patch("arka.core.code_project.config_dir", return_value=self.config),
            mock.patch("arka.agent.self_improve.run_diagnostics", return_value=diag),
            mock.patch("arka.agent.self_improve.generate_plan", return_value=plan),
            mock.patch("arka.agent.self_improve.record_attempt"),
        ):
            rc = self_improve.run_self_improve("routing", apply=False)
        self.assertEqual(rc, 0)

    def test_parse_improve_argv(self) -> None:
        target, apply, extras = self_improve.parse_improve_argv(["improve", "routing", "--apply", "-y"])
        self.assertEqual(target, "routing")
        self.assertTrue(apply)
        self.assertTrue(extras.get("yes"))

        target, apply, _ = self_improve.parse_improve_argv(["memory", "detect", "--apply"])
        self.assertEqual(target, "memory detect")
        self.assertTrue(apply)

        target, apply, _ = self_improve.parse_improve_argv(["--apply", "routing"])
        self.assertEqual(target, "routing")
        self.assertTrue(apply)

        target, apply, _ = self_improve.parse_improve_argv(["memory detect --apply"])
        self.assertEqual(target, "memory detect")
        self.assertTrue(apply)

    def test_format_plan_output_no_double_apply(self) -> None:
        plan = self_improve.ImprovementPlan(
            focus="memory detect --apply",
            proposal="fix memory",
            analyzed=["x"],
        )
        out = self_improve.format_plan_output(plan, apply=False, target="memory detect --apply")
        self.assertIn("Next: arka self improve memory detect --apply", out)
        self.assertNotIn("--apply --apply", out)

    def test_format_plan_output_apply_mode(self) -> None:
        plan = self_improve.ImprovementPlan(focus="routing", proposal="x", analyzed=["y"])
        out = self_improve.format_plan_output(plan, apply=True, target="routing")
        self.assertIn("Next: applying changes via goal agent", out)
        self.assertNotIn("--apply", out)

    def test_route_command_strips_apply(self) -> None:
        hit = self_improve.route_command("self improve memory detect --apply")
        self.assertEqual(hit, "self_improve memory detect --apply")

    def test_run_self_improve_apply_from_embedded_flag(self) -> None:
        diag = self_improve.DiagnosticResult("pytest -q", 0, "passed")
        plan = self_improve.ImprovementPlan(focus="memory detect", proposal="fix", analyzed=["x"])
        with (
            mock.patch("arka.agent.self_improve.arka_repo_root", return_value=self.root),
            mock.patch("arka.core.code_project.config_dir", return_value=self.config),
            mock.patch("arka.core.mode.get_mode", return_value="agent"),
            mock.patch(
                "arka.agent.self_improve.run_diagnostics",
                side_effect=[diag, diag, diag],
            ),
            mock.patch("arka.agent.self_improve.generate_plan", return_value=plan),
            mock.patch("arka.agent.goal.run_goal", return_value=0) as mock_goal,
            mock.patch("arka.agent.self_improve._sync_changelog"),
            mock.patch("arka.agent.self_improve.record_attempt"),
        ):
            os.environ.pop("ARKA_CODE_PROJECT", None)
            rc = self_improve.run_self_improve("memory detect --apply", max_rounds=1, max_steps=3)
        self.assertEqual(rc, 0)
        mock_goal.assert_called_once()

    def test_arka_repo_root_ignores_unrelated_git_cwd(self) -> None:
        real_root = Path(__file__).resolve().parents[1]
        other = Path(self.tmp.name) / "other-project"
        other.mkdir()
        (other / ".git").mkdir()
        with (
            mock.patch("arka.paths.checkout_root", return_value=real_root),
            mock.patch("arka.paths.arka_home", return_value=real_root),
            mock.patch("arka.agent.repo_context.git_root", return_value=other),
        ):
            detected = self_improve.arka_repo_root()
        self.assertEqual(detected, real_root.resolve())


if __name__ == "__main__":
    unittest.main()
