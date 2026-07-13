"""Tests for Arka operation modes (ask, plan, agent, debug, multitask)."""

from __future__ import annotations

import os
import tempfile
import unittest
from unittest import mock

from arka.core.mode import (
    DEFAULT_MODE,
    ask_mode_skill,
    build_plan,
    get_mode,
    load_mode,
    mode_allows_execution,
    route_mode_nl,
    set_mode,
)


class ModePersistenceTests(unittest.TestCase):
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

    def test_default_mode_is_agent(self) -> None:
        self.assertEqual(get_mode(), DEFAULT_MODE)

    def test_set_and_load_mode(self) -> None:
        set_mode("debug")
        self.assertEqual(get_mode(), "debug")
        os.environ.pop("ARKA_MODE", None)
        self.assertEqual(get_mode(), "debug")
        loaded = load_mode()
        self.assertEqual(loaded, "debug")
        self.assertEqual(os.environ.get("ARKA_MODE"), "debug")

    def test_env_overrides_file(self) -> None:
        set_mode("plan")
        os.environ["ARKA_MODE"] = "ask"
        self.assertEqual(get_mode(), "ask")

    def test_invalid_mode_raises(self) -> None:
        with self.assertRaises(ValueError):
            set_mode("invalid")


class ModeBehaviorTests(unittest.TestCase):
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
        set_mode("agent")

    def test_ask_mode_blocks_risky_skill(self) -> None:
        set_mode("ask")
        allowed, reason = mode_allows_execution("generate_password save wifi")
        self.assertFalse(allowed)
        self.assertIn("read-only", reason)

    def test_ask_mode_allows_calc(self) -> None:
        set_mode("ask")
        allowed, _ = mode_allows_execution("calc integrate sin(x)")
        self.assertTrue(allowed)

    def test_ask_mode_redirects_download(self) -> None:
        set_mode("ask")
        skill = ask_mode_skill("download_file https://example.com/x", "download this file")
        self.assertTrue(skill.startswith("web_answer "))

    def test_plan_mode_blocks_execution(self) -> None:
        set_mode("plan")
        allowed, reason = mode_allows_execution("calc 2+2")
        self.assertFalse(allowed)
        self.assertIn("plan mode", reason)

    def test_agent_mode_allows_skills(self) -> None:
        set_mode("agent")
        allowed, _ = mode_allows_execution("generate_password save wifi")
        self.assertTrue(allowed)


class ModeSymbolicRoutingTests(unittest.TestCase):
    def test_route_mode_nl_phrases(self) -> None:
        cases = {
            "set mode to debug": "mode debug",
            "switch to ask mode": "mode ask",
            "plan mode": "mode plan",
            "show mode": "mode",
            "what mode": "mode",
        }
        for phrase, expected in cases.items():
            with self.subTest(phrase=phrase):
                self.assertEqual(route_mode_nl(phrase), expected)

    def test_offline_extras_includes_mode(self) -> None:
        from arka.routing.symbolic import route_offline_extras

        self.assertEqual(route_offline_extras("set mode to plan"), "mode plan")


class ModePlanTests(unittest.TestCase):
    def test_build_plan_with_route(self) -> None:
        from arka.router import Route

        steps = build_plan("download playlist", Route("youtube_bulk download PLx", source="offline"))
        self.assertGreaterEqual(len(steps), 3)
        self.assertIn("youtube_bulk", steps[1].action)

    def test_build_plan_without_route(self) -> None:
        steps = build_plan("what is rust?", None)
        self.assertEqual(steps[0].index, 1)
        self.assertIn("web_answer", steps[1].action)


class ModeCliIntegrationTests(unittest.TestCase):
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

    def test_cli_mode_show(self) -> None:
        from arka.core.mode import main as mode_main

        set_mode("debug")
        code = mode_main(["mode"])
        self.assertEqual(code, 0)

    def test_cli_mode_set(self) -> None:
        from arka.core.mode import main as mode_main

        code = mode_main(["mode", "ask"])
        self.assertEqual(code, 0)
        self.assertEqual(get_mode(), "ask")

    def test_try_mode_nl_in_cli(self) -> None:
        from arka.cli import _try_mode_nl

        code = _try_mode_nl("set mode to plan")
        self.assertEqual(code, 0)
        self.assertEqual(get_mode(), "plan")


class ModeExecuteTests(unittest.TestCase):
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

    def test_execute_request_plan_mode_no_dispatch(self) -> None:
        from arka.cli import _execute_request
        from arka.router import Route

        set_mode("plan")
        with mock.patch("arka.cli.route", return_value=Route("calc 2+2", source="offline")):
            with mock.patch("arka.dispatch.run_skill") as run_skill:
                code = _execute_request("calc 2+2")
        self.assertEqual(code, 0)
        run_skill.assert_not_called()


if __name__ == "__main__":
    unittest.main()
