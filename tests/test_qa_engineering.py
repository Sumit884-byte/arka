"""Tests for QA Engineering skill."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arka.agent import qa_engineering as qa
from arka.router import route


class QAEngineeringTests(unittest.TestCase):
    def test_wants_qa_engineering(self) -> None:
        self.assertTrue(qa.wants_qa_engineering("run qa on this"))
        self.assertTrue(qa.wants_qa_engineering("qa checklist for feature login"))
        self.assertFalse(qa.wants_qa_engineering("weather in paris"))

    def test_route_command(self) -> None:
        self.assertEqual(qa.route_command("run qa on this"), "qa_engineering plan")
        self.assertEqual(qa.route_command("triage test failures"), "qa_engineering triage")
        self.assertEqual(qa.route_command("test coverage report"), "qa_engineering coverage")
        self.assertEqual(qa.route_command("extreme constraints for checkout"), 'qa_engineering extreme --feature "checkout"')
        self.assertEqual(qa.route_command("production ready constraints for checkout"), 'qa_engineering extreme --feature "checkout"')
        self.assertEqual(qa.route_command("production readiness"), "qa_engineering extreme")
        self.assertEqual(qa.route_command("mutation testing plan"), "qa_engineering extreme")
        self.assertIn("checklist", qa.route_command("qa checklist for feature checkout"))
        self.assertIn("explore", qa.route_command("exploratory testing for payments"))

    def test_detect_test_stack_pytest(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
            (root / "tests").mkdir()
            stack = qa.detect_test_stack(root)
            self.assertIn("pytest", stack["frameworks"])
            self.assertTrue(stack["smoke_commands"])

    def test_plan_payload_layers(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text(
                '{"scripts":{"test":"jest"},"devDependencies":{"@playwright/test":"1.0.0"}}',
                encoding="utf-8",
            )
            payload = qa.plan_payload(root, feature="checkout")
            layers = {row["layer"] for row in payload["layers"]}
            self.assertIn("unit", layers)
            self.assertIn("smoke", layers)
            self.assertEqual(payload["feature"], "checkout")

    def test_extreme_payload_names_high_rigor_constraints(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "pyproject.toml").write_text("[project]\nname='demo'\n", encoding="utf-8")
            (root / "tests").mkdir()
            payload = qa.extreme_payload(root, feature="payments")
            names = {row["name"] for row in payload["constraints"]}
            groups = {row["group"] for row in payload["constraint_groups"]}
            self.assertIn("Unit tests", names)
            self.assertIn("Gherkin / acceptance tests", names)
            self.assertIn("Integration and contract tests", names)
            self.assertIn("Static analysis and lint", names)
            self.assertIn("Secrets and data privacy", names)
            self.assertIn("Observability", names)
            self.assertIn("Runbook and rollback", names)
            self.assertIn("Configuration and environments", names)
            self.assertIn("Quality metrics", names)
            self.assertIn("Mutation testing", names)
            self.assertIn("Test coverage", names)
            self.assertIn("Security and privacy", groups)
            self.assertIn("Reliability and operations", groups)
            self.assertGreaterEqual(len(names), 20)
            self.assertTrue(any("pytest" in cmd for cmd in payload["suggested_commands"]))

    def test_extreme_text_is_evidence_oriented(self) -> None:
        text = qa.extreme_text(qa.extreme_payload(feature="auth"))
        self.assertIn("Extreme production-readiness constraints: auth", text)
        self.assertIn("No quality, performance, security, SLO, or readiness claim is made without evidence", text)
        self.assertIn("Mutation testing", text)
        self.assertIn("Security and privacy", text)
        self.assertIn("Release readiness", text)

    def test_checklist_payload(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = qa.checklist_payload(root, feature="auth")
            sections = payload["checklist"]
            self.assertIn("automated", sections)
            self.assertIn("manual", sections)
            self.assertTrue(any("auth" in item for item in sections["manual"]))

    def test_report_payload_markdown(self) -> None:
        payload = qa.report_payload(title="Login fails", steps="1. Open app", expected="Success", actual="500")
        self.assertIn("# Login fails", payload["markdown"])
        self.assertIn("500", payload["markdown"])

    def test_explore_payload(self) -> None:
        payload = qa.explore_payload(feature="search")
        self.assertIn("search", payload["charter"]["mission"])

    def test_coverage_payload_no_runner(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            payload = qa.coverage_payload(root)
            self.assertEqual(payload["path"], str(root.resolve()))

    def test_router_symbolic(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("qa checklist for feature billing")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "qa_engineering")

    def test_triage_payload_without_git(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch("arka.agent.qa_engineering.git_root", return_value=None):
                payload = qa.triage_payload(root)
            self.assertFalse(payload["ok"])
            self.assertIn("git", payload["error"].lower())


if __name__ == "__main__":
    unittest.main()
