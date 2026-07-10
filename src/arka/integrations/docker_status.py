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
    docker = _docker_bin()
    if not docker:
        print("Docker CLI not found. Install Docker Desktop or docker-engine.", file=sys.stderr)
        return 1
    if not docker_available():
        print("Docker daemon is not running. Start Docker and retry.", file=sys.stderr)
        return 1
    code, out, err = _run(
        [docker, "ps", "--format", "table {{.Names}}\t{{.Status}}\t{{.Ports}}"],
        timeout=30,
    )
    text = (out or err).strip()
    if not text:
        print("No running containers.")
        return 0
    lines = ["Running containers:", ""]
    lines.append(text)
    print("\n".join(lines))
    return code


def cmd_images(_args: argparse.Namespace) -> int:
    docker = _docker_bin()
    if not docker:
        print("Docker CLI not found.", file=sys.stderr)
        return 1
    code, out, err = _run(
        [docker, "images", "--format", "table {{.Repository}}:{{.Tag}}\t{{.Size}}\t{{.CreatedSince}}"],
        timeout=30,
    )
    text = (out or err).strip()
    print(text or "No images found.")
    return code


def cmd_logs(args: argparse.Namespace) -> int:
    docker = _docker_bin()
    if not docker:
        print("Docker CLI not found.", file=sys.stderr)
        return 1
    name = (args.container or "").strip()
    if not name:
        print("Usage: docker_status logs <container> [--tail N]", file=sys.stderr)
        return 1
    tail = max(10, int(args.tail))
    code, out, err = _run([docker, "logs", "--tail", str(tail), name], timeout=45)
    text = (out + err).strip()
    print(text or f"No logs for {name}")
    return code


def cmd_health(_args: argparse.Namespace) -> int:
    docker = _docker_bin()
    if not docker:
        print("docker_cli=missing")
        print("daemon=unknown")
        return 1
    if not which("docker"):
        print("docker_cli=missing")
        return 1
    print("docker_cli=ok")
    code, _, err = _run([docker, "info"], timeout=15)
    if code == 0:
        print("daemon=running")
    else:
        detail = err.strip().splitlines()[0] if err.strip() else "not running"
        print(f"daemon=stopped ({detail[:120]})")
    code2, out, _ = _run([docker, "ps", "-q"], timeout=15)
    count = len([ln for ln in out.splitlines() if ln.strip()]) if code2 == 0 else 0
    print(f"running_containers={count}")
    return 0 if code == 0 else 1


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
