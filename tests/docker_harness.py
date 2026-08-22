"""Helpers for running Arka CLI and MCP handlers inside Docker containers."""

from __future__ import annotations

import json
import os
import subprocess
import sys
from dataclasses import dataclass
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[1]
LINUX_DOCKERFILE = REPO_ROOT / "tests" / "docker" / "Dockerfile.linux-cli"
WINDOWS_DOCKERFILE = REPO_ROOT / "tests" / "docker" / "Dockerfile.windows-cli"
LINUX_IMAGE = os.environ.get("ARKA_CLI_TEST_IMAGE_LINUX", "arka-cli-test:linux")
WINDOWS_IMAGE = os.environ.get("ARKA_CLI_TEST_IMAGE_WINDOWS", "arka-cli-test:windows")
BUILD_TIMEOUT = int(os.environ.get("ARKA_DOCKER_BUILD_TIMEOUT", "600"))
RUN_TIMEOUT = int(os.environ.get("ARKA_DOCKER_RUN_TIMEOUT", "120"))


@dataclass(frozen=True)
class ContainerResult:
    returncode: int
    stdout: str
    stderr: str


def docker_bin() -> str | None:
    from shutil import which

    return which("docker")


def docker_info_ok() -> bool:
    docker = docker_bin()
    if not docker:
        return False
    try:
        proc = subprocess.run(
            [docker, "info"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def docker_sock_path() -> str | None:
    for candidate in (Path("/var/run/docker.sock"), Path.home() / ".docker/run/docker.sock"):
        if candidate.exists():
            return str(candidate)
    return None


def on_windows_host() -> bool:
    return sys.platform == "win32"


def windows_containers_available() -> bool:
    """True when this Windows host can run Windows containers."""
    if not on_windows_host() or not docker_info_ok():
        return False
    docker = docker_bin()
    assert docker is not None
    try:
        proc = subprocess.run(
            [docker, "info", "--format", "{{.OSType}}"],
            capture_output=True,
            text=True,
            timeout=20,
            check=False,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0 and proc.stdout.strip().lower() == "windows"


def _run(cmd: list[str], *, timeout: int = RUN_TIMEOUT) -> ContainerResult:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
            check=False,
        )
    except subprocess.TimeoutExpired as exc:
        stdout = exc.stdout.decode() if isinstance(exc.stdout, bytes) else (exc.stdout or "")
        stderr = exc.stderr.decode() if isinstance(exc.stderr, bytes) else (exc.stderr or "")
        return ContainerResult(124, stdout, stderr or "Command timed out")
    except OSError as exc:
        return ContainerResult(1, "", str(exc))
    return ContainerResult(proc.returncode, proc.stdout or "", proc.stderr or "")


def build_linux_cli_image(*, force: bool = False) -> str:
    docker = docker_bin()
    if not docker:
        raise RuntimeError("docker CLI not found")
    if not force:
        inspect = _run([docker, "image", "inspect", LINUX_IMAGE], timeout=30)
        if inspect.returncode == 0 and not os.environ.get("ARKA_DOCKER_BUILD_NO_CACHE"):
            return LINUX_IMAGE
    build_cmd = [
        docker,
        "build",
        "-f",
        str(LINUX_DOCKERFILE),
        "-t",
        LINUX_IMAGE,
        str(REPO_ROOT),
    ]
    if os.environ.get("ARKA_DOCKER_BUILD_NO_CACHE"):
        build_cmd.insert(2, "--no-cache")
    build = _run(
        build_cmd,
        timeout=BUILD_TIMEOUT,
    )
    if build.returncode != 0:
        detail = (build.stderr or build.stdout).strip()
        raise RuntimeError(f"failed to build {LINUX_IMAGE}: {detail[:500]}")
    return LINUX_IMAGE


def build_windows_cli_image(*, force: bool = False) -> str:
    docker = docker_bin()
    if not docker:
        raise RuntimeError("docker CLI not found")
    if not windows_containers_available():
        raise RuntimeError("Windows containers are not available on this host")
    if not force:
        inspect = _run([docker, "image", "inspect", WINDOWS_IMAGE], timeout=30)
        if inspect.returncode == 0:
            return WINDOWS_IMAGE
    build = _run(
        [
            docker,
            "build",
            "-f",
            str(WINDOWS_DOCKERFILE),
            "-t",
            WINDOWS_IMAGE,
            str(REPO_ROOT),
        ],
        timeout=BUILD_TIMEOUT,
    )
    if build.returncode != 0:
        detail = (build.stderr or build.stdout).strip()
        raise RuntimeError(f"failed to build {WINDOWS_IMAGE}: {detail[:500]}")
    return WINDOWS_IMAGE


def run_linux_container(
    command: list[str],
    *,
    image: str | None = None,
    mount_docker_sock: bool = False,
    env: dict[str, str] | None = None,
) -> ContainerResult:
    docker = docker_bin()
    if not docker:
        raise RuntimeError("docker CLI not found")
    tag = image or LINUX_IMAGE
    cmd = [docker, "run", "--rm"]
    for key, value in (env or {}).items():
        cmd.extend(["-e", f"{key}={value}"])
    if mount_docker_sock:
        sock = docker_sock_path()
        if sock:
            cmd.extend(["-v", f"{sock}:/var/run/docker.sock"])
    cmd.append(tag)
    cmd.extend(command)
    return _run(cmd)


def run_windows_container(
    command: list[str],
    *,
    image: str | None = None,
    env: dict[str, str] | None = None,
) -> ContainerResult:
    docker = docker_bin()
    if not docker:
        raise RuntimeError("docker CLI not found")
    tag = image or WINDOWS_IMAGE
    cmd = [docker, "run", "--rm", "--platform", "windows/amd64"]
    for key, value in (env or {}).items():
        cmd.extend(["-e", f"{key}={value}"])
    cmd.append(tag)
    cmd.extend(command)
    return _run(cmd)


def mcp_docker_in_linux_container(
    action: str,
    *,
    image: str | None = None,
    mount_docker_sock: bool = False,
    **arguments: object,
) -> dict[str, object]:
    payload = {"action": action, **arguments}
    script = (
        "import json; "
        "from arka.integrations.mcp_server import _handle_arka_docker; "
        f"print(_handle_arka_docker({payload!r}))"
    )
    result = run_linux_container(
        ["python", "-c", script],
        image=image,
        mount_docker_sock=mount_docker_sock,
        env={"ARKA_AUTO_REFETCH": "0"},
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"MCP docker handler failed in container: {detail[:500]}")
    return json.loads(result.stdout)


def mcp_docker_in_windows_container(
    action: str,
    *,
    image: str | None = None,
    **arguments: object,
) -> dict[str, object]:
    payload = {"action": action, **arguments}
    script = (
        "import json; "
        "from arka.integrations.mcp_server import _handle_arka_docker; "
        f"print(_handle_arka_docker({payload!r}))"
    )
    result = run_windows_container(
        ["python", "-c", script],
        image=image,
        env={"ARKA_AUTO_REFETCH": "0"},
    )
    if result.returncode != 0:
        detail = (result.stderr or result.stdout).strip()
        raise RuntimeError(f"MCP docker handler failed in Windows container: {detail[:500]}")
    return json.loads(result.stdout)


def run_host_mcp_docker(action: str, **arguments: object) -> dict[str, object]:
    """Invoke the same MCP handler the server exposes via arka_docker."""
    from arka.integrations.mcp_server import _handle_arka_docker

    payload = {"action": action, **arguments}
    return json.loads(_handle_arka_docker(payload))
