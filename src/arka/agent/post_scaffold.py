"""Whitelisted post-scaffold hooks for trusted Arka templates."""
from __future__ import annotations

import re
import shutil
import subprocess
import threading
from dataclasses import dataclass
from pathlib import Path

NPM_INSTALL_TIMEOUT = 180
NPM_AUDIT_TIMEOUT = 60
DEV_SERVER_START_TIMEOUT = 30

SCAFFOLD_3D_TEMPLATE = "3d-react-vite"

TRUSTED_TEMPLATES = frozenset({SCAFFOLD_3D_TEMPLATE})

_PACKAGE_COUNT_RE = re.compile(r"added\s+(\d+)\s+packages?", re.I)
_AUDIT_COUNT_RE = re.compile(r"audited\s+(\d+)\s+packages?", re.I)
_VITE_URL_RE = re.compile(r"https?://(?:127\.0\.0\.1|localhost):\d+/?", re.I)

_OFFLINE_MARKERS = (
    "enotfound",
    "econnrefused",
    "network is unreachable",
    "getaddrinfo",
    "fetch failed",
    "network error",
    "unable to connect",
    "offline",
    "etimedout",
)


@dataclass(frozen=True)
class NpmInstallResult:
    ok: bool
    package_count: int | None = None
    message: str = ""


def template_created_package_json(template: str, created: list[str]) -> bool:
    return template in TRUSTED_TEMPLATES and "package.json" in created


def parse_package_count(output: str) -> int | None:
    match = _PACKAGE_COUNT_RE.search(output)
    if match:
        return int(match.group(1))
    match = _AUDIT_COUNT_RE.search(output)
    if match:
        return int(match.group(1))
    return None


def parse_vite_local_url(line: str) -> str | None:
    match = _VITE_URL_RE.search(line)
    if not match:
        return None
    return match.group(0).rstrip("/") + "/"


def _looks_offline(output: str) -> bool:
    lowered = output.lower()
    return any(marker in lowered for marker in _OFFLINE_MARKERS)


def run_trusted_npm_install(cwd: Path, *, timeout: int = NPM_INSTALL_TIMEOUT) -> NpmInstallResult:
    """Run npm install for a trusted scaffold template directory."""
    try:
        proc = subprocess.run(
            ["npm", "install"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except subprocess.TimeoutExpired:
        return NpmInstallResult(
            ok=False,
            message=f"timed out after {timeout}s — check your network and retry `npm install`",
        )
    except OSError as exc:
        return NpmInstallResult(ok=False, message=str(exc))

    output = (proc.stdout or "") + (proc.stderr or "")
    if proc.returncode == 0:
        return NpmInstallResult(ok=True, package_count=parse_package_count(output))

    detail = (proc.stderr or proc.stdout or "").strip()
    if _looks_offline(detail):
        return NpmInstallResult(
            ok=False,
            message="network unavailable — connect and run `npm install` manually",
        )
    if detail:
        first_line = detail.splitlines()[0]
        return NpmInstallResult(ok=False, message=first_line)
    return NpmInstallResult(ok=False, message=f"npm exited {proc.returncode}")


def run_npm_audit_warn(cwd: Path, *, timeout: int = NPM_AUDIT_TIMEOUT) -> None:
    """Optional high-severity audit warning; never blocks scaffold success."""
    try:
        proc = subprocess.run(
            ["npm", "audit", "--audit-level=high"],
            cwd=cwd,
            capture_output=True,
            text=True,
            timeout=timeout,
        )
    except (OSError, subprocess.TimeoutExpired):
        return
    if proc.returncode != 0:
        detail = (proc.stdout or proc.stderr or "").strip()
        if detail:
            print(f"⚠ npm audit reported high-severity issues:\n{detail}")


def start_dev_server(cwd: Path, *, timeout: float = DEV_SERVER_START_TIMEOUT) -> tuple[bool, str]:
    """Start npm run dev in the background; return when a local URL appears."""
    print("○ Starting dev server (npm run dev)…")
    try:
        proc = subprocess.Popen(
            ["npm", "run", "dev"],
            cwd=cwd,
            stdout=subprocess.PIPE,
            stderr=subprocess.STDOUT,
            text=True,
            bufsize=1,
        )
    except OSError as exc:
        return False, f"Could not start dev server: {exc}"

    url_holder: list[str | None] = [None]
    tail: list[str] = []

    def _reader() -> None:
        assert proc.stdout is not None
        for line in proc.stdout:
            tail.append(line.rstrip())
            if len(tail) > 12:
                tail.pop(0)
            found = parse_vite_local_url(line)
            if found:
                url_holder[0] = found
                return

    reader = threading.Thread(target=_reader, daemon=True)
    reader.start()
    reader.join(timeout=timeout)

    if url_holder[0]:
        print(f"✓ Dev server ready: {url_holder[0]}")
        print("(Dev server running in background.)")
        return True, url_holder[0]

    if proc.poll() is not None and proc.returncode not in (None, 0):
        detail = "\n".join(tail).strip()
        return False, detail or f"npm run dev exited {proc.returncode}"

    return False, "Dev server did not print a local URL — run `npm run dev` manually."


def post_scaffold_hook(
    template: str,
    repo: Path,
    *,
    created: list[str],
    run_dev: bool = False,
    prompt_dev: bool = True,
    prompt_fn=None,
) -> None:
    """Run whitelisted post-scaffold steps for trusted templates only."""
    if not template_created_package_json(template, created):
        return

    print("○ Installing dependencies (npm install)…")
    if not shutil.which("npm"):
        print("✗ npm not found — install Node.js, then run `npm install` manually.")
        print("Next: `npm run dev` inside the project directory.")
        return

    result = run_trusted_npm_install(repo)
    if result.ok:
        suffix = f" ({result.package_count} packages)" if result.package_count is not None else ""
        print(f"✓ npm install complete{suffix}")
        run_npm_audit_warn(repo)
    else:
        print(f"✗ npm install failed — {result.message}")
        print("Scaffold files were created; run `npm install` manually when ready.")
        return

    if run_dev:
        ok, message = start_dev_server(repo)
        if not ok:
            print(f"✗ {message}")
            print("Next: `npm run dev` inside the project directory.")
        return

    if prompt_dev and prompt_fn is not None:
        answer = prompt_fn("Next: `npm run dev` — run now? [y/N]: ")
        if answer in {"y", "yes"}:
            ok, message = start_dev_server(repo)
            if not ok:
                print(f"✗ {message}")
                print("Next: `npm run dev` inside the project directory.")
            return

    print("Next: `npm run dev` inside the project directory.")
