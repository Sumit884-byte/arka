"""Prerequisites for SigNoz Foundry deploy — Docker and foundryctl."""

from __future__ import annotations

import argparse
import json
import os
import platform
import shutil
import subprocess
import sys
import time
import urllib.error
import urllib.request
from pathlib import Path


FOUNDRY_INSTALL_URL = "https://signoz.io/foundry.sh"
FOUNDRY_BIN_DIRS = (
    Path.home() / ".foundry" / "bin",
    Path.home() / ".local" / "bin",
    Path("/usr/local/bin"),
)


def _auto_install_enabled() -> bool:
    return os.environ.get("ARKA_AUTO_INSTALL", "").strip().lower() in {
        "1",
        "true",
        "yes",
        "all",
    }


def _confirm(prompt: str, *, auto_yes: bool) -> bool:
    if auto_yes or _auto_install_enabled():
        return True
    if not sys.stdin.isatty():
        print(f"{prompt} (non-interactive — pass -y or set ARKA_AUTO_INSTALL=1)", file=sys.stderr)
        return False
    try:
        answer = input(f"{prompt} [y/N]: ").strip()
    except EOFError:
        return False
    return answer.lower().startswith("y")


def platform_label() -> str:
    if sys.platform == "darwin":
        return "macos"
    if sys.platform.startswith("linux"):
        return "linux"
    if sys.platform == "win32":
        return "windows"
    return sys.platform


def docker_cli_path() -> str | None:
    return shutil.which("docker")


def docker_daemon_running(*, timeout: float = 30.0) -> bool:
    docker = docker_cli_path()
    if not docker:
        return False
    try:
        proc = subprocess.run(
            [docker, "info"],
            capture_output=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return False
    return proc.returncode == 0


def docker_status() -> dict[str, str]:
    cli = docker_cli_path()
    if not cli:
        return {"docker_cli": "missing", "docker_daemon": "missing"}
    if docker_daemon_running():
        return {"docker_cli": "ok", "docker_daemon": "running"}
    return {"docker_cli": "ok", "docker_daemon": "stopped"}


def foundryctl_path() -> str | None:
    found = shutil.which("foundryctl")
    if found:
        return found
    for directory in FOUNDRY_BIN_DIRS:
        candidate = directory / "foundryctl"
        if candidate.is_file():
            return str(candidate)
    return None


def resolve_casting_yaml() -> Path | None:
    env_path = os.environ.get("ARKA_SIGNOZ_CASTING", "").strip()
    if env_path:
        path = Path(env_path).expanduser()
        if path.is_file():
            return path.resolve()

    try:
        from arka.paths import arka_home, checkout_root
    except ImportError:
        checkout_root = arka_home = None  # type: ignore[assignment,misc]

    for base in filter(None, (checkout_root() if checkout_root else None, arka_home() if arka_home else None)):
        candidate = base / "casting.yaml"
        if candidate.is_file():
            return candidate.resolve()
    return None


def _docker_install_plan() -> list[tuple[str, list[str]]]:
    label = platform_label()
    plan: list[tuple[str, list[str]]] = []

    if label == "macos" and shutil.which("brew"):
        plan.append(("Homebrew (Docker Desktop)", ["brew", "install", "--cask", "docker"]))

    if label == "linux":
        if shutil.which("apt-get"):
            plan.append(
                (
                    "apt (docker.io)",
                    ["sudo", "apt-get", "update"],
                )
            )
            plan.append(("apt (docker.io)", ["sudo", "apt-get", "install", "-y", "docker.io"]))
        elif shutil.which("dnf"):
            plan.append(("dnf (docker)", ["sudo", "dnf", "install", "-y", "docker"]))
        elif shutil.which("yum"):
            plan.append(("yum (docker)", ["sudo", "yum", "install", "-y", "docker"]))

    return plan


def _docker_manual_instructions() -> str:
    label = platform_label()
    if label == "macos":
        return (
            "Install Docker Desktop for Mac:\n"
            "  brew install --cask docker\n"
            "  open -a Docker\n"
            "Or download: https://docs.docker.com/desktop/setup/install/mac-install/"
        )
    if label == "linux":
        return (
            "Install Docker Engine for Linux:\n"
            "  sudo apt-get update && sudo apt-get install -y docker.io\n"
            "  sudo systemctl enable --now docker\n"
            "Docs: https://docs.docker.com/engine/install/"
        )
    if label == "windows":
        return (
            "Install Docker Desktop for Windows:\n"
            "  winget install Docker.DockerDesktop\n"
            "Docs: https://docs.docker.com/desktop/setup/install/windows-install/"
        )
    return "Install Docker Desktop from https://docs.docker.com/get-docker/"


def _launch_docker_desktop() -> None:
    if platform_label() != "macos":
        return
    docker_app = Path("/Applications/Docker.app")
    if not docker_app.is_dir():
        return
    print("→ Opening Docker Desktop (first launch may take a minute)…", file=sys.stderr)
    subprocess.run(["open", "-a", "Docker"], check=False)


def _wait_for_docker_daemon(*, seconds: float = 90.0, poll: float = 3.0) -> bool:
    deadline = time.monotonic() + seconds
    while time.monotonic() < deadline:
        if docker_daemon_running(timeout=10.0):
            return True
        time.sleep(poll)
    return False


def ensure_docker(*, auto_yes: bool = False, wait: bool = True) -> bool:
    """Return True when the Docker CLI exists and the daemon responds."""
    if docker_daemon_running():
        print("✓ Docker daemon is running", file=sys.stderr)
        return True

    cli = docker_cli_path()
    if cli and not docker_daemon_running():
        print("Docker is installed but the daemon is not running.", file=sys.stderr)
        if platform_label() == "macos":
            _launch_docker_desktop()
            if wait and _wait_for_docker_daemon():
                print("✓ Docker daemon is running", file=sys.stderr)
                return True
        print(
            "Start Docker Desktop (or `sudo systemctl start docker` on Linux), then retry.",
            file=sys.stderr,
        )
        return False

    plan = _docker_install_plan()
    if not plan:
        print(_docker_manual_instructions(), file=sys.stderr)
        return False

    if not _confirm("Install Docker?", auto_yes=auto_yes):
        print("Skipped Docker install.", file=sys.stderr)
        return False

    for label, cmd in plan:
        print(f"→ Installing Docker via {label}: {' '.join(cmd)}", file=sys.stderr)
        try:
            proc = subprocess.run(cmd, timeout=900)
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"  Install failed: {exc}", file=sys.stderr)
            continue
        if proc.returncode != 0:
            print(f"  Install exited {proc.returncode}", file=sys.stderr)
            continue

        if platform_label() == "macos":
            _launch_docker_desktop()
            print(
                "Docker Desktop was installed. Complete setup in the menu-bar app on first launch.",
                file=sys.stderr,
            )
            if wait and _wait_for_docker_daemon():
                print("✓ Docker daemon is running", file=sys.stderr)
                return True
            print(
                "Docker Desktop is installed but not ready yet.\n"
                "  1. Open Docker from Applications (or menu bar)\n"
                "  2. Wait until Docker reports Running\n"
                "  3. Re-run: arka signoz setup",
                file=sys.stderr,
            )
            return False

        if docker_daemon_running() or (wait and _wait_for_docker_daemon(seconds=30.0)):
            print("✓ Docker daemon is running", file=sys.stderr)
            return True

    print("Could not install Docker automatically. Try manually:", file=sys.stderr)
    print(_docker_manual_instructions(), file=sys.stderr)
    return False


def _prepend_foundry_bin(path: str) -> None:
    directory = str(Path(path).parent)
    current = os.environ.get("PATH", "")
    if directory not in current.split(os.pathsep):
        os.environ["PATH"] = f"{directory}{os.pathsep}{current}"


def _foundry_install_cmd() -> list[str]:
    if shutil.which("bash"):
        return ["bash", "-c", f"curl -fsSL {FOUNDRY_INSTALL_URL} | bash"]
    return ["sh", "-c", f"curl -fsSL {FOUNDRY_INSTALL_URL} | sh"]


def ensure_foundryctl(*, auto_yes: bool = False) -> str | None:
    existing = foundryctl_path()
    if existing:
        print(f"✓ foundryctl ready: {existing}", file=sys.stderr)
        _prepend_foundry_bin(existing)
        return existing

    if not shutil.which("curl"):
        print(
            "foundryctl not found and curl is unavailable.\n"
            f"  curl -fsSL {FOUNDRY_INSTALL_URL} | bash",
            file=sys.stderr,
        )
        return None

    if not _confirm("Install foundryctl (SigNoz Foundry)?", auto_yes=auto_yes):
        print("Skipped foundryctl install.", file=sys.stderr)
        return None

    cmd = _foundry_install_cmd()
    print(f"→ Installing foundryctl: {' '.join(cmd)}", file=sys.stderr)
    try:
        proc = subprocess.run(cmd, timeout=600)
    except (OSError, subprocess.TimeoutExpired) as exc:
        print(f"foundryctl install failed: {exc}", file=sys.stderr)
        return None
    if proc.returncode != 0:
        print(f"foundryctl install exited {proc.returncode}", file=sys.stderr)
        return None

    for directory in FOUNDRY_BIN_DIRS:
        _prepend_foundry_bin(str(directory / "foundryctl"))

    found = foundryctl_path()
    if found:
        print(f"✓ foundryctl ready: {found}", file=sys.stderr)
        return found

    print(
        "foundryctl install finished but binary not on PATH.\n"
        f"  curl -fsSL {FOUNDRY_INSTALL_URL} | bash\n"
        "Then open a new shell or add ~/.foundry/bin to PATH.",
        file=sys.stderr,
    )
    return None


def run_foundry(
    casting: Path,
    *,
    gauge_only: bool = False,
    cast: bool = False,
) -> int:
    ctl = foundryctl_path()
    if not ctl:
        print("foundryctl not found — run: arka signoz setup", file=sys.stderr)
        return 127

    if gauge_only or not cast:
        cmd = [ctl, "gauge", "-f", str(casting)]
        print(f"→ {' '.join(cmd)}", file=sys.stderr)
        return subprocess.run(cmd).returncode

    cmd = [ctl, "cast", "-f", str(casting)]
    print(f"→ {' '.join(cmd)}", file=sys.stderr)
    return subprocess.run(cmd).returncode


def signoz_ui_setup_status(ui_url: str | None = None) -> str:
    """Return complete, pending, or unreachable for SigNoz first-time UI setup."""
    base = (ui_url or os.environ.get("SIGNOZ_UI_URL", "http://localhost:8080")).rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/api/v1/version", timeout=3) as resp:
            data = json.loads(resp.read().decode())
            if data.get("setupCompleted") is True:
                return "complete"
            return "pending"
    except (OSError, urllib.error.URLError, json.JSONDecodeError, ValueError):
        return "unreachable"


def signoz_mcp_status(mcp_url: str | None = None) -> str:
    """Return ok or unreachable for the SigNoz MCP server health check."""
    base = (mcp_url or os.environ.get("SIGNOZ_MCP_URL", "http://localhost:8000")).rstrip("/")
    try:
        with urllib.request.urlopen(f"{base}/livez", timeout=3) as resp:
            if resp.read().decode().strip().lower() == "ok":
                return "ok"
            return "unknown"
    except (OSError, urllib.error.URLError):
        return "unreachable"


def prereq_status_lines() -> list[tuple[str, str]]:
    lines: list[tuple[str, str]] = []
    for key, value in docker_status().items():
        lines.append((key, value))
    ctl = foundryctl_path()
    lines.append(("foundryctl", "ok" if ctl else "missing"))
    casting = resolve_casting_yaml()
    lines.append(("casting_yaml", str(casting) if casting else "missing"))
    return lines


def cmd_setup(args: argparse.Namespace) -> int:
    auto_yes = bool(getattr(args, "yes", False))
    skip_cast = bool(getattr(args, "skip_cast", False))
    check_only = bool(getattr(args, "check_only", False))

    print(f"SigNoz setup ({platform_label()})", file=sys.stderr)

    for key, value in prereq_status_lines():
        print(f"{key}\t{value}")

    if check_only:
        ok = docker_daemon_running() and bool(foundryctl_path()) and bool(resolve_casting_yaml())
        if not ok:
            print("hint\trun: arka signoz setup -y", file=sys.stderr)
        return 0 if ok else 1

    if not ensure_docker(auto_yes=auto_yes):
        return 1

    if not ensure_foundryctl(auto_yes=auto_yes):
        return 1

    casting = resolve_casting_yaml()
    if not casting:
        print(
            "casting.yaml not found in repo root. Clone the Arka repo or set ARKA_SIGNOZ_CASTING.",
            file=sys.stderr,
        )
        return 1

    gauge_rc = run_foundry(casting, gauge_only=True)
    if gauge_rc != 0:
        return gauge_rc

    if skip_cast:
        print("✓ Prerequisites OK (skipped foundryctl cast — use without --skip-cast to deploy)", file=sys.stderr)
        return 0

    if not _confirm(f"Deploy SigNoz with foundryctl cast -f {casting.name}?", auto_yes=auto_yes):
        print("Skipped cast. Run later: foundryctl cast -f casting.yaml", file=sys.stderr)
        return 0

    return run_foundry(casting, cast=True)
