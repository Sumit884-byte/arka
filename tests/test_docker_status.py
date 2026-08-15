"""Tests for docker status skill."""

from __future__ import annotations

import json
import os
import unittest
from unittest import mock

import pytest

from arka.integrations import docker_status as ds
from arka.integrations.mcp_server import _handle_arka_docker
from arka.router import route


class DockerStatusTests(unittest.TestCase):
    def test_wants_docker_status(self) -> None:
        self.assertTrue(ds.wants_docker_status("show docker containers"))
        self.assertTrue(ds.wants_docker_status("docker logs for api"))
        self.assertFalse(ds.wants_docker_status("bookmark manager"))

    def test_route_ps_logs_images(self) -> None:
        self.assertEqual(ds.route_command("list docker containers"), "docker_status ps")
        self.assertEqual(ds.route_command("docker logs for nginx"), "docker_status logs nginx")
        self.assertEqual(ds.route_command("show docker images"), "docker_status images")

    def test_health_missing_cli(self) -> None:
        with mock.patch.object(ds, "_docker_bin", return_value=None):
            code = ds.cmd_health(argparse_namespace())
        self.assertEqual(code, 1)

    def test_health_payload_missing_cli(self) -> None:
        with mock.patch.object(ds, "_docker_bin", return_value=None):
            payload = ds.health_payload()
        self.assertFalse(payload["docker_cli"])
        self.assertFalse(payload["daemon_running"])

    def test_list_containers_requires_daemon(self) -> None:
        with mock.patch.object(ds, "_docker_bin", return_value="docker"), mock.patch.object(
            ds, "docker_available", return_value=False
        ):
            with self.assertRaises(RuntimeError):
                ds.list_containers()

    def test_router_symbolic(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("show running docker containers")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "docker_status")

    def test_cmd_health_running_daemon(self) -> None:
        with mock.patch.object(
            ds,
            "health_payload",
            return_value={
                "docker_cli": True,
                "daemon_running": True,
                "running_containers": 3,
                "detail": "",
            },
        ):
            with mock.patch("sys.stdout", new_callable=mock.MagicMock) as stdout:
                code = ds.cmd_health(argparse_namespace())
        self.assertEqual(code, 0)
        output = "".join(call.args[0] for call in stdout.write.call_args_list)
        self.assertIn("docker_cli=ok", output)
        self.assertIn("daemon=running", output)
        self.assertIn("running_containers=3", output)

    def test_mcp_docker_health_matches_payload(self) -> None:
        sample = {
            "docker_cli": True,
            "daemon_running": False,
            "running_containers": 0,
            "detail": "stopped",
        }
        with mock.patch.object(ds, "health_payload", return_value=sample):
            raw = _handle_arka_docker({"action": "health"})
        self.assertEqual(json.loads(raw), sample)

    def test_mcp_docker_invalid_action(self) -> None:
        with self.assertRaises(ValueError):
            _handle_arka_docker({"action": "restart"})


@pytest.mark.docker
@pytest.mark.docker_linux
def test_docker_status_health_in_linux_container(linux_cli_image: str) -> None:
    from tests import docker_harness as dh

    result = dh.run_linux_container(
        ["python", "-m", "arka.integrations.docker_status", "ps"],
        image=linux_cli_image,
        env={
            "ARKA_AUTO_REFETCH": "0",
            "CONFIG_DIR": "/tmp/arka-docker-config",
            "CACHE_DIR": "/tmp/arka-docker-cache",
        },
        mount_docker_sock=True,
    )
    if result.returncode == 0:
        assert "Running containers:" in result.stdout or "No running containers." in result.stdout
    else:
        assert "Docker daemon is not running" in result.stderr or "Docker CLI not found" in result.stderr


def argparse_namespace():
    from argparse import Namespace

    return Namespace()


if __name__ == "__main__":
    unittest.main()
