"""Tests for scoped code project workspace."""

from __future__ import annotations

import os
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arka.core import code_project


class CodeProjectPersistenceTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.config = Path(self.tmp.name) / "arka"
        self.config.mkdir(parents=True, exist_ok=True)
        self.patch = mock.patch("arka.core.code_project.config_dir")
        self.mock_config_dir = self.patch.start()
        self.addCleanup(self.patch.stop)
        self.mock_config_dir.return_value = self.config
        os.environ.pop(code_project._ENV_KEY, None)

    def test_init_and_status(self) -> None:
        project = Path(self.tmp.name) / "myapp"
        project.mkdir()
        root = code_project.init_project(project)
        self.assertEqual(root, project.resolve())
        self.assertEqual(code_project.get_active_root(), project.resolve())
        info = code_project.status_dict()
        self.assertTrue(info["initialized"])
        self.assertEqual(info["name"], "myapp")

    def test_clear_project(self) -> None:
        project = Path(self.tmp.name) / "app"
        project.mkdir()
        code_project.init_project(project)
        code_project.clear_project()
        self.assertIsNone(code_project.get_active_root())

    def test_env_override(self) -> None:
        project = Path(self.tmp.name) / "envapp"
        project.mkdir()
        os.environ[code_project._ENV_KEY] = str(project)
        self.assertEqual(code_project.get_active_root(), project.resolve())


class CodeProjectScopeTests(unittest.TestCase):
    def setUp(self) -> None:
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name) / "project"
        self.root.mkdir()
        (self.root / "src").mkdir()
        (self.root / "src" / "main.py").write_text("print('hi')\n", encoding="utf-8")
        self.patch = mock.patch("arka.core.code_project.config_dir")
        self.mock_config_dir = self.patch.start()
        self.addCleanup(self.patch.stop)
        self.config = Path(self.tmp.name) / "config"
        self.config.mkdir(parents=True, exist_ok=True)
        self.mock_config_dir.return_value = self.config
        code_project.init_project(self.root)

    def test_resolve_in_project_relative(self) -> None:
        resolved = code_project.resolve_in_project("src/main.py")
        self.assertEqual(resolved, (self.root / "src" / "main.py").resolve())

    def test_reject_parent_escape(self) -> None:
        with self.assertRaises(code_project.CodeProjectError):
            code_project.resolve_in_project("../outside.txt")

    def test_reject_absolute_outside(self) -> None:
        outside = Path(self.tmp.name) / "outside.txt"
        outside.write_text("x", encoding="utf-8")
        with self.assertRaises(code_project.CodeProjectError):
            code_project.resolve_in_project(outside)

    def test_symlink_escape_blocked(self) -> None:
        outside = Path(self.tmp.name) / "secret.txt"
        outside.write_text("secret", encoding="utf-8")
        link = self.root / "link.txt"
        link.symlink_to(outside)
        with self.assertRaises(code_project.CodeProjectError):
            code_project.resolve_in_project("link.txt")

    def test_gate_write_script_inside(self) -> None:
        ok, msg = code_project.gate_write_script_args(["src/new.py"])
        self.assertTrue(ok)
        self.assertEqual(msg, "")

    def test_gate_write_script_outside(self) -> None:
        ok, msg = code_project.gate_write_script_args(["../escape.py"])
        self.assertFalse(ok)
        self.assertIn("outside", msg)

    def test_gate_code_write_without_init(self) -> None:
        code_project.clear_project()
        ok, msg = code_project.gate_code_write("agent_code fix bug")
        self.assertFalse(ok)
        self.assertIn("init", msg)
        self.assertIn("cwd:", msg)

    def test_not_init_message_includes_cwd(self) -> None:
        msg = code_project.not_init_message(cwd=self.root)
        self.assertIn("arka code init .", msg)
        self.assertIn(str(self.root.resolve()), msg)

    def test_gate_code_init_allowed_without_project(self) -> None:
        code_project.clear_project()
        ok, msg = code_project.gate_code_write("code init .")
        self.assertTrue(ok)
        self.assertEqual(msg, "")

    def test_gate_goal_without_project_allows(self) -> None:
        code_project.clear_project()
        ok, msg = code_project.gate_code_write("goal list files")
        self.assertTrue(ok)

    def test_check_shell_scope_blocks_redirect(self) -> None:
        ok, msg = code_project.check_shell_scope("echo hi > ../outside.txt", root=self.root)
        self.assertFalse(ok)
        self.assertIn("outside", msg)

    def test_check_shell_scope_allows_inside(self) -> None:
        ok, msg = code_project.check_shell_scope("echo hi > src/new.txt", root=self.root)
        self.assertTrue(ok)


class CodeProjectRoutingTests(unittest.TestCase):
    def test_route_init_nl(self) -> None:
        hit = code_project.route_code_nl("initialize project for coding in ~/dev/myapp")
        self.assertEqual(hit, "code init ~/dev/myapp")

    def test_route_write_nl(self) -> None:
        hit = code_project.route_code_nl("write code add login endpoint")
        self.assertEqual(hit, "code write add login endpoint")

    def test_route_status_nl(self) -> None:
        hit = code_project.route_code_nl("code status")
        self.assertEqual(hit, "code status")


if __name__ == "__main__":
    unittest.main()
