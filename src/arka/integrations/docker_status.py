#!/usr/bin/env python3
"""Docker container, image, and log status from the terminal."""

from __future__ import annotations

import argparse
import re
import shlex
import subprocess
import sys
from shutil import which

try:
    from arka.paths import load_env_file

    load_env_file()
except ImportError:

    def load_env_file() -> None:
        pass


_TRIGGER_RE = re.compile(
    r"(?i)\b("
    r"docker\s+(?:status|containers?|ps|logs?|images?|health)|"
    r"list\s+docker\s+containers?|show\s+docker|"
    r"container\s+logs?|running\s+containers?"
    r")\b"
)
_LOGS_RE = re.compile(r"(?i)\b(?:docker\s+)?logs?\b")
_PS_RE = re.compile(r"(?i)\b(?:docker\s+)?(?:ps|containers?|status)\b")
_IMAGES_RE = re.compile(r"(?i)\b(?:docker\s+)?images?\b")
_HEALTH_RE = re.compile(r"(?i)\b(?:docker\s+)?health\b")


def _docker_bin() -> str | None:
    return which("docker")


def _run(cmd: list[str], *, timeout: int = 60) -> tuple[int, str, str]:
    try:
        proc = subprocess.run(
            cmd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
        return proc.returncode, proc.stdout or "", proc.stderr or ""
    except subprocess.TimeoutExpired:
        return 124, "", "Command timed out"
    except OSError as exc:
        return 1, "", str(exc)


def docker_available() -> bool:
    if not _docker_bin():
        return False
    code, _, _ = _run([_docker_bin() or "docker", "info"], timeout=15)
    return code == 0


def health_payload() -> dict[str, object]:
    """Structured Docker daemon health for MCP / automation clients."""
    docker = _docker_bin()
    if not docker:
        return {
            "docker_cli": False,
            "daemon_running": False,
            "running_containers": 0,
            "detail": "Docker CLI not found",
        }
    code, _, err = _run([docker, "info"], timeout=15)
    daemon_running = code == 0
    detail = ""
    if not daemon_running:
        detail = err.strip().splitlines()[0] if err.strip() else "not running"
    code2, out, _ = _run([docker, "ps", "-q"], timeout=15)
    count = len([ln for ln in out.splitlines() if ln.strip()]) if code2 == 0 else 0
    return {
        "docker_cli": True,
        "daemon_running": daemon_running,
        "running_containers": count,
        "detail": detail,
    }


def list_containers() -> dict[str, object]:
    """List running containers as structured rows."""
    docker = _docker_bin()
    if not docker:
        raise RuntimeError("Docker CLI not found. Install Docker Desktop or docker-engine.")
    if not docker_available():
        raise RuntimeError("Docker daemon is not running. Start Docker and retry.")
    code, out, err = _run(
        [docker, "ps", "--format", "{{.Names}}\t{{.Status}}\t{{.Image}}\t{{.Ports}}"],
        timeout=30,
    )
    if code != 0:
        raise RuntimeError((err or out or "docker ps failed").strip())
    containers: list[dict[str, str]] = []
    for line in (out or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        containers.append(
            {
                "name": parts[0].strip(),
                "status": parts[1].strip() if len(parts) > 1 else "",
                "image": parts[2].strip() if len(parts) > 2 else "",
                "ports": parts[3].strip() if len(parts) > 3 else "",
            }
        )
    return {"count": len(containers), "containers": containers}


def list_images(*, limit: int = 50) -> dict[str, object]:
    """List local Docker images as structured rows."""
    docker = _docker_bin()
    if not docker:
        raise RuntimeError("Docker CLI not found.")
    code, out, err = _run(
        [docker, "images", "--format", "{{.Repository}}\t{{.Tag}}\t{{.ID}}\t{{.Size}}\t{{.CreatedSince}}"],
        timeout=30,
    )
    if code != 0:
        raise RuntimeError((err or out or "docker images failed").strip())
    limit = max(1, min(int(limit or 50), 200))
    images: list[dict[str, str]] = []
    for line in (out or "").splitlines():
        parts = line.split("\t")
        if len(parts) < 2:
            continue
        images.append(
            {
                "repository": parts[0].strip(),
                "tag": parts[1].strip() if len(parts) > 1 else "",
                "id": parts[2].strip() if len(parts) > 2 else "",
                "size": parts[3].strip() if len(parts) > 3 else "",
                "created": parts[4].strip() if len(parts) > 4 else "",
            }
        )
        if len(images) >= limit:
            break
    return {"count": len(images), "images": images}


def container_logs(name: str, *, tail: int = 50) -> dict[str, object]:
    """Return recent logs for a container."""
    docker = _docker_bin()
    if not docker:
        raise RuntimeError("Docker CLI not found.")
    container = (name or "").strip()
    if not container:
        raise ValueError("container name is required")
    limit = max(10, min(int(tail or 50), 500))
    code, out, err = _run([docker, "logs", "--tail", str(limit), container], timeout=45)
    text = (out + err).strip()
    if code != 0 and not text:
        raise RuntimeError(f"failed to read logs for {container}")
    return {"container": container, "tail": limit, "logs": text}


def _extract_container_name(text: str) -> str | None:
    patterns = (
        r"(?i)\b(?:for|from|container)\s+([a-zA-Z0-9][a-zA-Z0-9_.-]+)",
        r"(?i)\b([a-zA-Z0-9][a-zA-Z0-9_.-]+)\s+(?:container\s+)?logs?\b",
    )
    for pat in patterns:
        m = re.search(pat, text or "")
        if m:
            name = m.group(1)
            if name.lower() not in ("docker", "container", "containers", "logs", "log"):
                return name
    return None


def cmd_ps(_args: argparse.Namespace) -> int:
    try:
        payload = list_containers()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    containers = payload.get("containers") or []
    if not containers:
        print("No running containers.")
        return 0
    lines = ["Running containers:", ""]
    lines.append("NAMES\tSTATUS\tPORTS")
    for row in containers:
        lines.append(f"{row.get('name')}\t{row.get('status')}\t{row.get('ports')}")
    print("\n".join(lines))
    return 0


def cmd_images(_args: argparse.Namespace) -> int:
    try:
        payload = list_images()
    except RuntimeError as exc:
        print(str(exc), file=sys.stderr)
        return 1
    images = payload.get("images") or []
    if not images:
        print("No images found.")
        return 0
    lines = ["REPOSITORY:TAG\tSIZE\tCREATED"]
    for row in images:
        lines.append(
            f"{row.get('repository')}:{row.get('tag')}\t{row.get('size')}\t{row.get('created')}"
        )
    print("\n".join(lines))
    return 0


def cmd_logs(args: argparse.Namespace) -> int:
    try:
        payload = container_logs(args.container, tail=int(args.tail))
    except (RuntimeError, ValueError) as exc:
        print(str(exc), file=sys.stderr)
        return 1
    text = str(payload.get("logs") or "")
    print(text or f"No logs for {args.container}")
    return 0


def cmd_health(_args: argparse.Namespace) -> int:
    info = health_payload()
    if not info.get("docker_cli"):
        print("docker_cli=missing")
        print("daemon=unknown")
        return 1
    print("docker_cli=ok")
    if info.get("daemon_running"):
        print("daemon=running")
    else:
        detail = str(info.get("detail") or "not running")
        print(f"daemon=stopped ({detail[:120]})")
    print(f"running_containers={info.get('running_containers', 0)}")
    return 0 if info.get("daemon_running") else 1


def wants_docker_status(text: str) -> bool:
    return bool(_TRIGGER_RE.search(text or ""))


def route_command(text: str) -> str:
    if not wants_docker_status(text):
        return ""
    clean = (text or "").strip()
    if _LOGS_RE.search(clean):
        name = _extract_container_name(clean)
        if name:
            return f"docker_status logs {shlex.quote(name)}"
    if _IMAGES_RE.search(clean):
        return "docker_status images"
    if _HEALTH_RE.search(clean):
        return "docker_status health"
    if _PS_RE.search(clean) or _TRIGGER_RE.search(clean):
        return "docker_status ps"
    return "docker_status ps"


def main(argv: list[str] | None = None) -> int:
    load_env_file()
    parser = argparse.ArgumentParser(description="Docker status and logs")
    sub = parser.add_subparsers(dest="cmd")

    p_route = sub.add_parser("route", help="Map NL to docker_status command")
    p_route.add_argument("text", nargs="+")

    sub.add_parser("ps", help="List running containers").set_defaults(func=cmd_ps)
    sub.add_parser("images", help="List local images").set_defaults(func=cmd_images)
    sub.add_parser("health", help="Docker daemon health summary").set_defaults(func=cmd_health)

    p_logs = sub.add_parser("logs", help="Tail container logs")
    p_logs.add_argument("container")
    p_logs.add_argument("--tail", type=int, default=50)
    p_logs.set_defaults(func=cmd_logs)

    args = parser.parse_args(argv)
    if args.cmd == "route":
        route = route_command(" ".join(args.text))
        if route:
            print(route)
            return 0
        return 1
    if hasattr(args, "func"):
        return int(args.func(args))
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
