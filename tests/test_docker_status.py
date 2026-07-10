"""Tests for docker status skill."""

from __future__ import annotations

import os
import unittest
from unittest import mock

from arka.integrations import docker_status as ds
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

    def test_router_symbolic(self) -> None:
        with mock.patch.dict(os.environ, {"ROUTE_MODE": "symbolic_only"}, clear=False):
            result = route("show running docker containers")
        self.assertIsNotNone(result)
        assert result is not None
        self.assertEqual(result.skill.split()[0], "docker_status")


def argparse_namespace():
    from argparse import Namespace

    return Namespace()


if __name__ == "__main__":
    unittest.main()
