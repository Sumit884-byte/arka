"""Tests for Harvard ARK Agent CLI integration."""

from __future__ import annotations

import json
import tempfile
import unittest
from pathlib import Path
from unittest import mock

from arka.integrations import harvard_ark as ha
from arka.routing.symbolic import route_harvard_ark


class HarvardArkRoutingTests(unittest.TestCase):
    def test_wants_harvard_ark(self) -> None:
        self.assertTrue(ha.wants_harvard_ark("harvard ark chat"))
        self.assertTrue(ha.wants_harvard_ark("ask primekg about diabetes"))
        self.assertTrue(ha.wants_harvard_ark("biomedical knowledge graph"))
        self.assertTrue(ha.wants_harvard_ark("ark agent cli"))
        self.assertFalse(ha.wants_harvard_ark("improve arka"))
        self.assertFalse(ha.wants_harvard_ark("weather in mumbai"))

    def test_route_command(self) -> None:
        self.assertEqual(ha.route_command("install harvard ark"), "harvard_ark install")
        self.assertEqual(ha.route_command("harvard ark list graphs"), "harvard_ark list")
        self.assertEqual(ha.route_command("harvard_ark install"), "harvard_ark install")
        self.assertEqual(
            ha.route_command("ask primekg about metformin"),
            "harvard_ark chat metformin",
        )
        self.assertEqual(ha.route_command("improve arka"), "")

    def test_main_harvard_ark_install_routes_to_install(self) -> None:
        with mock.patch.object(ha, "cmd_install", return_value=0) as install:
            rc = ha.main(["harvard_ark", "install"])
        self.assertEqual(rc, 0)
        install.assert_called_once()

    def test_nl_to_argv(self) -> None:
        self.assertEqual(ha.nl_to_argv("harvard ark install"), ["install"])
        self.assertEqual(ha.nl_to_argv("list primekg graphs"), ["list"])

    def test_route_harvard_ark_symbolic(self) -> None:
        hit = route_harvard_ark("ask primekg about diabetes")
        self.assertIsNotNone(hit)
        assert hit is not None
        self.assertTrue(hit.startswith("harvard_ark "))


class HarvardArkInstallTests(unittest.TestCase):
    def test_list_graphs_reads_metadata(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            data = root / "data" / "primekg"
            data.mkdir(parents=True)
            (data / "graph.json").write_text(
                json.dumps(
                    {
                        "id": 1,
                        "name": "PrimeKG",
                        "description": "Precision medicine KG",
                        "order": 1,
                    }
                ),
                encoding="utf-8",
            )
            with mock.patch.object(ha, "install_dir", return_value=root):
                graphs = ha.list_graphs()
            self.assertEqual(len(graphs), 1)
            self.assertEqual(graphs[0]["slug"], "primekg")
            self.assertEqual(graphs[0]["name"], "PrimeKG")

    def test_cmd_install_clones_and_installs(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            dest = Path(tmp) / "ark-agent-cli"
            calls: list[list[str]] = []

            def fake_run(cmd: list[str], *, cwd=None, env=None, capture=False):
                calls.append(list(cmd))
                class R:
                    returncode = 0
                    stdout = ""
                    stderr = ""

                if cmd[:2] == ["git", "clone"]:
                    dest.mkdir(parents=True)
                    (dest / "package.json").write_text("{}", encoding="utf-8")
                    (dest / ".env.example").write_text("ANTHROPIC_API_KEY=\n", encoding="utf-8")
                if cmd[:2] == ["pnpm", "install"]:
                    (dest / "node_modules").mkdir()
                return R()

            with mock.patch.object(ha, "install_dir", return_value=dest):
                with mock.patch.object(ha, "ensure_prerequisites", return_value=[]):
                    with mock.patch.object(ha, "sync_env_file", return_value=True):
                        with mock.patch.object(ha, "_run", side_effect=fake_run):
                            rc = ha.cmd_install()
            self.assertEqual(rc, 0)
            self.assertTrue(any(c[:2] == ["git", "clone"] for c in calls))
            self.assertTrue(any(c[:2] == ["pnpm", "install"] for c in calls))

    def test_ensure_prerequisites_installs_via_brew(self) -> None:
        calls: list[list[str]] = []

        def fake_run(cmd: list[str], *, cwd=None, env=None, capture=False):
            calls.append(list(cmd))
            class R:
                returncode = 0
                stdout = ""
                stderr = ""

            return R()

        with mock.patch.object(ha, "check_prerequisites", side_effect=[[], []]):
            with mock.patch.object(ha, "_platform", return_value="macos"):
                with mock.patch.object(ha.shutil, "which", side_effect=lambda t: "/opt/brew/bin/brew" if t == "brew" else "/usr/bin/" + t):
                    with mock.patch.object(ha, "_run", side_effect=fake_run):
                        missing = ha.ensure_prerequisites()
        self.assertEqual(missing, [])
        self.assertFalse(any(c[:2] == ["brew", "install"] for c in calls))

        with mock.patch.object(
            ha,
            "check_prerequisites",
            side_effect=[["pnpm (pnpm >= 10)"], []],
        ):
            with mock.patch.object(ha, "_platform", return_value="macos"):
                with mock.patch.object(ha.shutil, "which", side_effect=lambda t: "/opt/brew/bin/brew" if t == "brew" else None):
                    with mock.patch.object(ha, "_run", side_effect=fake_run):
                        missing = ha.ensure_prerequisites()
        self.assertEqual(missing, [])
        self.assertTrue(any(c[:2] == ["brew", "install"] and "pnpm" in c for c in calls))

    def test_cmd_chat_requires_install(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            with mock.patch.object(ha, "install_dir", return_value=Path(tmp)):
                with mock.patch.object(ha, "is_installed", return_value=False):
                    self.assertEqual(ha.cmd_chat(["diabetes"]), 1)

    def test_cmd_chat_launches_cli(self) -> None:
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp)
            (root / "package.json").write_text("{}", encoding="utf-8")
            (root / "node_modules").mkdir()
            with mock.patch.object(ha, "install_dir", return_value=root):
                with mock.patch.object(ha, "is_installed", return_value=True):
                    with mock.patch.object(ha, "cli_exec_prefix", return_value=["pnpm", "cli"]):
                        with mock.patch.object(ha, "check_prerequisites", return_value=[]):
                            with mock.patch.object(ha, "sync_env_file", return_value=True):
                                with mock.patch.object(ha, "_run", return_value=mock.Mock(returncode=0)) as run:
                                    rc = ha.cmd_chat(["what treats diabetes"])
            self.assertEqual(rc, 0)
            run.assert_called_once()
            self.assertEqual(run.call_args[0][0], ["pnpm", "cli"])


if __name__ == "__main__":
    unittest.main()
