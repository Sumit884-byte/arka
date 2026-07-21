"""Tests for Jules-style async coding sessions."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arka.agent import jules
from arka.routing.symbolic import route_offline_extras


class JulesRoutingTests(unittest.TestCase):
    def test_route_command_phrases(self) -> None:
        cases = (
            ("jules list", "jules list"),
            ("list jules sessions", "jules list"),
            ("fix github issue #42", "jules issue 42"),
            ("work on issue 7", "jules issue 7"),
            ("fix issue #99 async", "jules issue 99"),
            ("work on add login tests async", "jules assign 'add login tests'"),
            ("background coding fix the parser", "jules assign 'fix the parser'"),
            ("jules assign refactor auth module", "jules assign refactor auth module"),
            ("cancel jules abc123def0", "jules cancel abc123def0"),
            ("check jules abc123def0", "jules resume abc123def0"),
            ("create pr for jules abc123def0", "jules pr abc123def0"),
        )
        for phrase, expected in cases:
            with self.subTest(phrase=phrase):
                hit = jules.route_command(phrase)
                self.assertEqual(hit, expected, msg=f"{phrase!r} -> {hit!r}")

    def test_symbolic_extras_routes_jules(self) -> None:
        hit = route_offline_extras("fix github issue #12")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertEqual(hit.split()[0], "jules")


class JulesSessionTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        root = Path(self.tmpdir.name)
        self._patch = mock.patch.object(jules, "jules_root", return_value=root)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_assign_sync_stores_result(self) -> None:
        with mock.patch.object(jules, "_run_goal_captured", return_value=("done ok", 0)):
            os.environ["JULES_SYNC"] = "1"
            try:
                data, err = jules.assign("add unit tests for routing")
            finally:
                os.environ.pop("JULES_SYNC", None)
        self.assertIsNone(err)
        assert data is not None
        self.assertEqual(data["status"], "done")
        self.assertIn("done ok", data.get("result", ""))

    def test_list_and_cancel(self) -> None:
        with mock.patch.object(jules, "_run_goal_captured", return_value=("ok", 0)):
            os.environ["JULES_SYNC"] = "1"
            try:
                data, _ = jules.assign("small task")
            finally:
                os.environ.pop("JULES_SYNC", None)
        assert data is not None
        rows = jules.list_sessions()
        self.assertTrue(any(row["id"] == data["id"] for row in rows))
        ok, msg = jules.cancel_session(data["id"])
        self.assertFalse(ok)
        self.assertIn("already", msg)

    def test_cancel_pending(self) -> None:
        session_id = "testpending1"
        jules._save(
            {
                "id": session_id,
                "kind": "assign",
                "task": "pending",
                "goal": "pending",
                "status": "pending",
                "created": 1.0,
            }
        )
        ok, msg = jules.cancel_session(session_id)
        self.assertTrue(ok)
        self.assertIn("cancelled", msg)
        loaded = jules.session_status(session_id)
        assert loaded is not None
        self.assertEqual(loaded["status"], "cancelled")

    def test_build_issue_goal_includes_title(self) -> None:
        goal = jules.build_issue_goal(
            {"number": 5, "title": "Login fails", "body": "Steps to reproduce", "url": "https://x/y/5"},
            repo="org/repo",
        )
        self.assertIn("#5", goal)
        self.assertIn("Login fails", goal)
        self.assertIn("org/repo", goal)


class JulesIssueTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        root = Path(self.tmpdir.name)
        self._patch = mock.patch.object(jules, "jules_root", return_value=root)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_assign_issue_requires_gh(self) -> None:
        with mock.patch.object(jules, "_gh_available", return_value=False):
            data, err = jules.assign_issue(1)
        self.assertIsNone(data)
        self.assertIn("GitHub CLI", err or "")

    def test_assign_issue_sync(self) -> None:
        issue = {
            "number": 9,
            "title": "Broken widget",
            "body": "It breaks",
            "url": "https://github.com/o/r/issues/9",
            "state": "OPEN",
            "labels": [],
        }
        with (
            mock.patch.object(jules, "_gh_available", return_value=True),
            mock.patch.object(jules, "_resolve_repo", return_value="o/r"),
            mock.patch.object(jules, "fetch_issue", return_value=issue),
            mock.patch.object(jules, "_create_branch", return_value=("jules/issue-9-abc123", None)),
            mock.patch.object(jules, "_run_goal_captured", return_value=("fixed", 0)),
            mock.patch.object(jules, "_maybe_create_pr", return_value="https://github.com/o/r/pull/1"),
        ):
            os.environ["JULES_SYNC"] = "1"
            try:
                data, err = jules.assign_issue(9, repo="o/r")
            finally:
                os.environ.pop("JULES_SYNC", None)
        self.assertIsNone(err)
        assert data is not None
        self.assertEqual(data["issue_number"], 9)
        self.assertEqual(data["status"], "done")
        self.assertEqual(data.get("pr_url"), "https://github.com/o/r/pull/1")


class JulesMcpTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmpdir = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmpdir.cleanup)
        root = Path(self.tmpdir.name)
        self._patch = mock.patch.object(jules, "jules_root", return_value=root)
        self._patch.start()
        self.addCleanup(self._patch.stop)

    def test_handle_arka_jules_assign(self) -> None:
        from arka.integrations.mcp_server import _handle_arka_jules

        with mock.patch.object(jules, "_run_goal_captured", return_value=("mcp done", 0)):
            payload = json.loads(
                _handle_arka_jules({"action": "assign", "task": "fix tests", "sync": True})
            )
        self.assertEqual(payload["status"], "done")
        self.assertIn("mcp done", payload.get("result", ""))


if __name__ == "__main__":
    unittest.main()
