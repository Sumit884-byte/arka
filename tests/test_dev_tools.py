"""Tests for developer-tools routing and local CI/review helpers."""

from __future__ import annotations

import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arka.agent import dev_tools as dt
from arka.router import route


class DevToolsTests(unittest.TestCase):
    def test_route_command(self) -> None:
        self.assertEqual(dt.route_command("arka ci"), "ci")
        self.assertEqual(dt.route_command("arka ci --full"), "ci --full")
        self.assertEqual(dt.route_command("arka ci --fix"), "ci --fix")
        self.assertEqual(dt.route_command("review staged"), "review --staged")
        self.assertEqual(dt.route_command("route audit"), "route_audit")
        self.assertEqual(dt.route_command("skill new my_tool --template dev"), "skill new my_tool --template dev")
        self.assertEqual(dt.route_command("check developer setup"), "dev_doctor")
        self.assertEqual(dt.route_command("show api testing tools like Postman"), "dev_tools list")
        self.assertEqual(dt.route_command("check Docker Kubernetes Terraform tools"), "dev_tools list")
        self.assertEqual(dt.route_command("install Arka pre-commit checks"), "hooks install")
        self.assertEqual(dt.route_command("restore my previous git hook"), "hooks restore")

    def test_router_symbolic(self) -> None:
        with mock.patch.dict("os.environ", {"ROUTE_MODE": "symbolic_only"}, clear=False):
            self.assertEqual(route("arka ci").skill.split()[0], "ci")
            self.assertEqual(route("review staged").skill.split()[0], "review")
            self.assertEqual(route("route audit").skill.split()[0], "route_audit")
            self.assertEqual(route("show Postman and Insomnia API testing tools").skill, "dev_tools list")

    def test_ci_gates_full_adds_full_pytest(self) -> None:
        names = [gate.name for gate in dt.ci_gates(full=True)]
        self.assertEqual(names[:2], ["ruff", "pytest"])
        self.assertIn("pytest-full", names)
        self.assertEqual(dt.ci_gates()[0].command[:3], [dt._python(), "-m", "ruff"])
        self.assertEqual(dt.ci_gates(changed=["src/arka/x.py"])[0].name, "ruff-changed")

    def test_changed_ci_deduplicates_status_paths(self) -> None:
        with mock.patch.object(dt, "_run", side_effect=[(0, "src/arka/x.py\n", ""), (0, " M src/arka/x.py\n?? tests/test_x.py\n", "")]), mock.patch.object(dt, "ci_gates", return_value=[]):
            payload = dt.run_ci(Path("."), changed_only=True)
        assert payload["path"] == str(Path("."))

    def test_review_hints(self) -> None:
        text = dt._security_and_test_gap_hints("shell=True route parser", ["src/arka/cli.py"])
        self.assertTrue(any("security" in hint for hint in text))
        self.assertTrue(any("test-gap" in hint for hint in text))

    def test_review_fail_on_hints(self) -> None:
        args = type("Args", (), {"path": ".", "base": "", "staged": False, "fail_on_hints": True})()
        with mock.patch.object(dt, "review_text", return_value="security: inspect secrets"):
            assert dt.cmd_review(args) == 1

    def test_review_json(self) -> None:
        import contextlib
        import io
        args = type("Args", (), {"path": ".", "base": "", "staged": False, "fail_on_hints": False, "json": True})()
        output = io.StringIO()
        with mock.patch.object(dt, "review_text", return_value="security: inspect secrets"), contextlib.redirect_stdout(output):
            assert dt.cmd_review(args) == 0
        assert '"hints"' in output.getvalue()

    def test_hooks_install_and_status(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / ".git" / "hooks").mkdir(parents=True)
            install = type("Args", (), {"path": str(root), "action": "install", "force": False})()
            assert dt.cmd_hooks(install) == 0
            assert "python -m arka" in (root / ".git" / "hooks" / "pre-commit").read_text()
            status = type("Args", (), {"path": str(root), "action": "status", "force": False})()
            assert dt.cmd_hooks(status) == 0

    def test_hooks_force_backs_up_existing(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            hook = root / ".git" / "hooks" / "pre-commit"
            hook.parent.mkdir(parents=True)
            hook.write_text("#!/bin/sh\necho existing\n")
            args = type("Args", (), {"path": str(root), "action": "install", "force": True})()
            assert dt.cmd_hooks(args) == 0
            assert "existing" in hook.with_name("pre-commit.arka-backup").read_text()
            restore = type("Args", (), {"path": str(root), "action": "restore", "force": False})()
            assert dt.cmd_hooks(restore) == 0
            assert "existing" in hook.read_text()

    def test_security_scan_includes_untracked(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "secret.py").write_text('API_KEY = "1234567890"\n')
            with mock.patch.object(dt, "_run", side_effect=[(0, "", ""), (0, "?? secret.py\n", "")]):
                findings = dt.security_scan(root)
            self.assertTrue(any(item["file"] == "secret.py" for item in findings))

    def test_doctor_json(self) -> None:
        import contextlib
        import io
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            assert dt.cmd_doctor(type("Args", (), {"path": ".", "json": True})()) in (0, 1)
        assert "checks" in output.getvalue()
        assert "developer_tools" in output.getvalue()

    def test_developer_tool_catalog_contains_api_browser_and_devops(self) -> None:
        names = {row["name"] for row in dt.developer_tool_catalog()}
        assert {"Postman", "Insomnia", "Chrome DevTools", "Firefox Developer Edition", "Docker", "Kubernetes", "GitHub Actions", "Terraform", "Prometheus", "Jenkins"} <= names

    def test_developer_tools_command_json(self) -> None:
        import contextlib
        import io
        output = io.StringIO()
        with contextlib.redirect_stdout(output):
            assert dt.cmd_tools(type("Args", (), {"json": True})()) == 0
        assert "Postman" in output.getvalue()

    def test_scaffold_skill(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            target = dt.scaffold_skill(root, name="my_tool", template="dev")
            self.assertTrue((target / "skill.json").is_file())
            self.assertTrue((target / "run.py").is_file())
            self.assertTrue((target / "README.md").is_file())


if __name__ == "__main__":
    unittest.main()
