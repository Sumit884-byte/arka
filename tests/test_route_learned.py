"""Tests for learned NL routing."""

from __future__ import annotations

import json
import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arka.routing import learned as lr
from arka.router import route


class LearnedRoutesTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.path = Path(self.tmp.name) / "learned_routes.json"
        self.path.write_text(json.dumps({"version": 1, "routes": []}), encoding="utf-8")

    def tearDown(self) -> None:
        self.tmp.cleanup()

    def _patch_path(self):
        return mock.patch.object(lr, "learned_routes_path", return_value=self.path)

    def test_learn_and_match_exact(self) -> None:
        with self._patch_path():
            lr.learn_route("deploy staging", "agent_code run deploy.sh")
            self.assertEqual(lr.match_learned("deploy staging"), "agent_code run deploy.sh")

    def test_match_with_remainder(self) -> None:
        with self._patch_path():
            lr.learn_route("check servers", "system_monitor")
            self.assertEqual(
                lr.match_learned("check servers in prod"),
                "system_monitor in prod",
            )

    def test_args_placeholder(self) -> None:
        with self._patch_path():
            lr.learn_route("summarize repo", "github_repo activity {args}")
            self.assertEqual(
                lr.match_learned("summarize repo Sumit884-byte/arka"),
                "github_repo activity Sumit884-byte/arka",
            )

    def test_delete_route(self) -> None:
        with self._patch_path():
            entry = lr.learn_route("ping ops", "system_monitor")
            rid = entry["id"]
            self.assertTrue(lr.delete_route(rid))
            self.assertEqual(lr.match_learned("ping ops"), "")

    def test_parse_teach_request(self) -> None:
        parsed = lr.parse_teach_request('teach route "deploy staging" to "agent_code run deploy.sh"')
        self.assertEqual(parsed, ("deploy staging", "agent_code run deploy.sh"))

    def test_route_management_list(self) -> None:
        with self._patch_path():
            self.assertEqual(lr.route_management_command("list learned routes"), "route_learn list")

    def test_router_uses_learned_route(self) -> None:
        with self._patch_path():
            lr.learn_route("my status dashboard", "system_monitor")
            with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
                with mock.patch("arka.fish_bridge.fish_route_preview", return_value=None):
                    with mock.patch("arka.router.fish_config", return_value=None):
                        result = route("my status dashboard")
            self.assertIsNotNone(result)
            assert result is not None
            self.assertEqual(result.skill, "system_monitor")
            self.assertEqual(result.source, "offline")


if __name__ == "__main__":
    unittest.main()
