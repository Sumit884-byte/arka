"""Shared pytest fixtures."""

from __future__ import annotations

import pytest

from tests import docker_harness as dh


def pytest_configure(config: pytest.Config) -> None:
    config.addinivalue_line("markers", "docker: requires Docker CLI and daemon")
    config.addinivalue_line("markers", "docker_linux: Linux container integration tests")
    config.addinivalue_line("markers", "docker_windows: Windows container integration tests")
    config.addinivalue_line("markers", "windows_cli: Windows host CLI smoke tests")


@pytest.fixture(scope="session")
def docker_daemon_available() -> bool:
    return dh.docker_info_ok()


@pytest.fixture(scope="session")
def linux_cli_image(docker_daemon_available: bool) -> str:
    if not docker_daemon_available:
        pytest.skip("Docker daemon is not available")
    return dh.build_linux_cli_image()


@pytest.fixture(scope="session")
def windows_cli_image() -> str:
    if not dh.windows_containers_available():
        pytest.skip("Windows containers are not available on this host")
    return dh.build_windows_cli_image()
