"""Docker integration tests — run Arka CLI and MCP docker handlers inside containers."""

from __future__ import annotations

import json
import sys

import pytest

from tests import docker_harness as dh

CONTAINER_ENV = {
    "ARKA_AUTO_REFETCH": "0",
    "CONFIG_DIR": "/tmp/arka-docker-config",
    "CACHE_DIR": "/tmp/arka-docker-cache",
}


@pytest.mark.docker
@pytest.mark.docker_linux
def test_linux_container_arka_version(linux_cli_image: str) -> None:
    result = dh.run_linux_container(
        ["python", "-m", "arka", "--version"],
        image=linux_cli_image,
        env=CONTAINER_ENV,
    )
    assert result.returncode == 0
    assert "arka" in result.stdout.lower()


@pytest.mark.docker
@pytest.mark.docker_linux
def test_linux_container_plugin_doctor(linux_cli_image: str) -> None:
    result = dh.run_linux_container(
        ["python", "-m", "arka", "plugin", "doctor"],
        image=linux_cli_image,
        env=CONTAINER_ENV,
    )
    assert result.returncode in (0, 1)
    assert "Plugins checked:" in result.stdout


@pytest.mark.docker
@pytest.mark.docker_linux
def test_linux_container_docker_status_cli(linux_cli_image: str) -> None:
    result = dh.run_linux_container(
        ["python", "-m", "arka.integrations.docker_status", "health"],
        image=linux_cli_image,
        env=CONTAINER_ENV,
        mount_docker_sock=True,
    )
    assert "docker_cli=" in result.stdout
    if result.returncode == 0:
        assert "daemon=running" in result.stdout
    else:
        assert "daemon=stopped" in result.stdout or "docker_cli=missing" in result.stdout


@pytest.mark.docker
@pytest.mark.docker_linux
def test_linux_container_docker_status_route(linux_cli_image: str) -> None:
    result = dh.run_linux_container(
        [
            "python",
            "-m",
            "arka.integrations.docker_status",
            "route",
            "list",
            "docker",
            "containers",
        ],
        image=linux_cli_image,
        env=CONTAINER_ENV,
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "docker_status ps"


@pytest.mark.docker
@pytest.mark.docker_linux
def test_linux_container_mcp_docker_health(linux_cli_image: str) -> None:
    payload = dh.mcp_docker_in_linux_container(
        "health",
        image=linux_cli_image,
        mount_docker_sock=True,
    )
    assert payload["docker_cli"] is True
    assert "daemon_running" in payload
    assert "running_containers" in payload


@pytest.mark.docker
@pytest.mark.docker_linux
def test_linux_container_mcp_docker_ps(linux_cli_image: str, docker_daemon_available: bool) -> None:
    health = dh.mcp_docker_in_linux_container(
        "health",
        image=linux_cli_image,
        mount_docker_sock=True,
    )
    if not health.get("daemon_running"):
        pytest.skip("Docker daemon not reachable from Linux test container")
    payload = dh.mcp_docker_in_linux_container(
        "ps",
        image=linux_cli_image,
        mount_docker_sock=True,
    )
    assert "count" in payload
    assert "containers" in payload
    assert isinstance(payload["containers"], list)


@pytest.mark.docker
@pytest.mark.docker_linux
def test_linux_container_mcp_docker_images(linux_cli_image: str, docker_daemon_available: bool) -> None:
    health = dh.mcp_docker_in_linux_container(
        "health",
        image=linux_cli_image,
        mount_docker_sock=True,
    )
    if not health.get("daemon_running"):
        pytest.skip("Docker daemon not reachable from Linux test container")
    payload = dh.mcp_docker_in_linux_container(
        "images",
        image=linux_cli_image,
        mount_docker_sock=True,
        limit=5,
    )
    assert "count" in payload
    assert "images" in payload


@pytest.mark.docker
@pytest.mark.docker_linux
def test_host_mcp_matches_container_mcp_health(
    linux_cli_image: str,
    docker_daemon_available: bool,
) -> None:
    """Host arka_docker MCP and in-container handler should agree on daemon state."""
    if not docker_daemon_available:
        pytest.skip("Docker daemon is not available on host")
    host = dh.run_host_mcp_docker("health")
    container = dh.mcp_docker_in_linux_container(
        "health",
        image=linux_cli_image,
        mount_docker_sock=True,
    )
    assert host["docker_cli"] == container["docker_cli"]
    assert host["daemon_running"] == container["daemon_running"]


@pytest.mark.docker
@pytest.mark.docker_windows
def test_windows_container_arka_version(windows_cli_image: str) -> None:
    result = dh.run_windows_container(
        ["python", "-m", "arka", "--version"],
        image=windows_cli_image,
        env={"ARKA_AUTO_REFETCH": "0"},
    )
    assert result.returncode == 0
    assert "arka" in result.stdout.lower()


@pytest.mark.docker
@pytest.mark.docker_windows
def test_windows_container_plugin_doctor(windows_cli_image: str) -> None:
    result = dh.run_windows_container(
        ["python", "-m", "arka", "plugin", "doctor"],
        image=windows_cli_image,
        env={
            "ARKA_AUTO_REFETCH": "0",
            "CONFIG_DIR": "C:\\arka-docker-config",
            "CACHE_DIR": "C:\\arka-docker-cache",
        },
    )
    assert result.returncode in (0, 1)
    assert "Plugins checked:" in result.stdout


@pytest.mark.docker
@pytest.mark.docker_windows
def test_windows_container_docker_status_route(windows_cli_image: str) -> None:
    result = dh.run_windows_container(
        [
            "python",
            "-m",
            "arka.integrations.docker_status",
            "route",
            "show",
            "docker",
            "images",
        ],
        image=windows_cli_image,
        env={"ARKA_AUTO_REFETCH": "0"},
    )
    assert result.returncode == 0
    assert result.stdout.strip() == "docker_status images"


@pytest.mark.docker
@pytest.mark.docker_windows
def test_windows_container_mcp_docker_health(windows_cli_image: str) -> None:
    payload = dh.mcp_docker_in_windows_container("health", image=windows_cli_image)
    assert "docker_cli" in payload
    assert "daemon_running" in payload


@pytest.mark.windows_cli
@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows host only")
def test_windows_host_cli_version() -> None:
    import subprocess

    proc = subprocess.run(
        [sys.executable, "-m", "arka", "--version"],
        capture_output=True,
        text=True,
        env={"ARKA_AUTO_REFETCH": "0", **dict(__import__("os").environ)},
        timeout=30,
        check=False,
    )
    assert proc.returncode == 0
    assert "arka" in proc.stdout.lower()


@pytest.mark.windows_cli
@pytest.mark.skipif(not sys.platform.startswith("win"), reason="Windows host only")
def test_windows_host_mcp_docker_health() -> None:
    payload = dh.run_host_mcp_docker("health")
    assert "docker_cli" in payload
    assert json.dumps(payload)
