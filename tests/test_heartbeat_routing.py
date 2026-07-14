"""Tests for heartbeat NL routing."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from arka.integrations import heartbeat as hb
from arka.router import route
from arka.routing.symbolic import route_offline_extras


class HeartbeatRoutingTests(unittest.TestCase):
    def test_wants_heartbeat(self) -> None:
        self.assertTrue(hb.wants_heartbeat("show agent heartbeat"))
        self.assertTrue(hb.wants_heartbeat("heartbeat history"))
        self.assertFalse(hb.wants_heartbeat("weather in paris"))

    def test_route_status_and_history(self) -> None:
        self.assertEqual(hb.route_command("check agent heartbeat"), "heartbeat status")
        self.assertEqual(hb.route_command("show recent activity history"), "heartbeat history")
        self.assertEqual(hb.route_command("heartbeat ping cli.test"), "heartbeat ping cli.test")

    def test_symbolic_extras(self) -> None:
        hit = route_offline_extras("agent heartbeat status")
        self.assertEqual(hit, "heartbeat status")

    def test_router_symbolic(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("show agent heartbeat")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "heartbeat")


if __name__ == "__main__":
    unittest.main()
