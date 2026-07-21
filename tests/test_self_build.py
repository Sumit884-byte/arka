"""Tests for Arka MCP-orchestrated self-build loop."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arka.agent import self_build
from arka.routing.symbolic import route_offline_extras, route_self_build


class SelfBuildRoutingTests(unittest.TestCase):
    def test_route_command_phrases(self) -> None:
        cases = (
            ("self build", "self_build"),
            ("improve self", "self_build"),
            ("build arka with mcp", "self_build"),
            ("use mcp to fix arka", "self_build"),
            ("improve arka using mcp", "self_build"),
            ("mcp self improve", "self_build"),
            ("self improve using mcp routing", "self_build routing"),
            ("self build routing --apply", "self_build routing --apply"),
            ("self build status", "self_build status"),
        )
        for phrase, expected in cases:
            with self.subTest(phrase=phrase):
                hit = self_build.route_command(phrase)
                self.assertEqual(hit, expected, msg=f"{phrase!r} -> {hit!r}")

    def test_symbolic_route_self_build(self) -> None:
        hit = route_self_build("improve arka using mcp")
        self.assertEqual(hit, "self_build")

    def test_offline_extras_routes_self_build(self) -> None:
        hit = route_offline_extras("use mcp to fix arka")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.split()[0], "self_build")


class SelfBuildMcpTests(unittest.TestCase):
    def test_mcp_audit_uses_handlers(self) -> None:
        root = Path(__file__).resolve().parents[1]

        def fake_call(name: str, arguments: dict) -> str:
            if name == "arka_repo_health" and arguments.get("action") == "scan":
                return json.dumps({"count": 2, "checks": []})
            if name == "arka_repo_health" and arguments.get("action") == "run":
                return json.dumps({"ok": True, "passed": 2, "failed": 0, "skipped": 0, "results": []})
            if name == "arka_repo_map":
                return "src/arka/agent/self_build.py"
            if name == "arka_route":
                return "self_build routing"
            raise AssertionError(f"unexpected call {name} {arguments}")

        with mock.patch("arka.integrations.mcp_server.call_mcp_tool", side_effect=fake_call):
            audit = self_build.mcp_audit(root, target="routing")
        self.assertEqual(audit.scan.get("count"), 2)
        self.assertTrue(audit.run.get("ok"))
        self.assertIn("self_build.py", audit.repo_map)

    def test_call_mcp_tool_in_process(self) -> None:
        from arka.integrations.mcp_server import call_mcp_tool

        with mock.patch(
            "arka.integrations.mcp_server._handle_arka_repo_health",
            return_value='{"ok": true}',
        ):
            text = call_mcp_tool("arka_repo_health", {"action": "scan"})
        self.assertEqual(text, '{"ok": true}')

    def test_handle_arka_self_build_status(self) -> None:
        from arka.integrations.mcp_server import _handle_arka_self_build

        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch("arka.agent.self_build.self_build_root", return_value=Path(tmp)):
                payload = json.loads(_handle_arka_self_build({"action": "status"}))
        self.assertIn("count", payload)
        self.assertIn("dir", payload)


class SelfBuildSessionTests(unittest.TestCase):
    def test_session_save_and_list(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            with mock.patch("arka.agent.self_build.self_build_root", return_value=root):
                self_build._save({"id": "abc123", "status": "planned", "target": "routing"})
                rows = self_build.list_sessions(limit=5)
                self.assertEqual(len(rows), 1)
                self.assertEqual(rows[0]["id"], "abc123")
                loaded = self_build.session_status("abc123")
                assert loaded is not None
                self.assertEqual(loaded["status"], "planned")


class SelfBuildRunTests(unittest.TestCase):
    def test_run_self_build_plan_only(self) -> None:
        root = Path(__file__).resolve().parents[1]
        audit = self_build.McpAudit(
            scan={"count": 1},
            run={"ok": True, "passed": 1, "failed": 0, "skipped": 0, "results": []},
            repo_map="src/arka",
        )
        plan = mock.Mock()
        plan.focus = "routing"
        plan.proposal = "add test"
        plan.files = ["src/arka/routing/symbolic.py"]
        plan.tests = ["pytest -q tests/test_self_build.py"]

        with tempfile.TemporaryDirectory() as tmp:
            with (
                mock.patch("arka.agent.self_build.self_build_root", return_value=Path(tmp)),
                mock.patch("arka.agent.self_improve.ensure_arka_project", return_value=root),
                mock.patch("arka.agent.self_build.mcp_audit", return_value=audit),
                mock.patch("arka.agent.self_improve._read_repo_context", return_value="ctx"),
                mock.patch("arka.agent.self_improve.run_diagnostics") as diag_mock,
                mock.patch("arka.agent.self_improve._routing_analysis", return_value=[]),
                mock.patch("arka.agent.self_improve._docs_check", return_value=(True, "ok")),
                mock.patch("arka.agent.self_improve.generate_plan", return_value=plan),
                mock.patch("arka.agent.self_improve.format_plan_output", return_value="plan out"),
                mock.patch("arka.agent.self_improve.record_attempt") as record_mock,
            ):
                diag_mock.return_value = mock.Mock(passed=True)
                code = self_build.run_self_build("routing", apply=False)
        self.assertEqual(code, 0)
        record_mock.assert_called_once()

    def test_run_self_build_apply_requires_agent_mode(self) -> None:
        root = Path(__file__).resolve().parents[1]
        with (
            mock.patch("arka.agent.self_improve.ensure_arka_project", return_value=root),
            mock.patch("arka.core.mode.get_mode", return_value="normal"),
        ):
            code = self_build.run_self_build("routing", apply=True)
        self.assertEqual(code, 1)


if __name__ == "__main__":
    unittest.main()
