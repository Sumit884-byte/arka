"""Optional Butterfish shell integration (interactive Goal Mode)."""

from __future__ import annotations

import os
import shutil
import subprocess
import sys


def find_butterfish() -> str | None:
    return shutil.which("butterfish")


def butterfish_available() -> bool:
    return find_butterfish() is not None


def _auto_install_enabled() -> bool:
    """When true, install without prompting (ARKA_AUTO_INSTALL=1 or goal -y)."""
    return os.environ.get("ARKA_AUTO_INSTALL", "").strip().lower() in (
        "1",
        "true",
        "yes",
        "all",
    )


def _install_plan() -> list[tuple[str, list[str]]]:
    """Return (label, argv) install attempts in preference order."""
    plan: list[tuple[str, list[str]]] = []
    if shutil.which("brew"):
        plan.append(("Homebrew", ["brew", "install", "bakks/tap/butterfish"]))
    if shutil.which("go"):
        plan.append(
            (
                "Go",
                ["go", "install", "github.com/bakks/butterfish/cmd/butterfish@latest"],
            )
        )
    return plan


def _go_bin_on_path() -> None:
    go_bin = os.path.join(os.environ.get("GOPATH", os.path.expanduser("~/go")), "bin")
    if go_bin not in os.environ.get("PATH", ""):
        os.environ["PATH"] = f"{go_bin}:{os.environ.get('PATH', '')}"


def ensure_butterfish(*, auto_yes: bool = False) -> str | None:
    """Return butterfish path; optionally ask user and install if missing."""
    existing = find_butterfish()
    if existing:
        return existing

    plan = _install_plan()
    if not plan:
        print(
            "Butterfish not found and no installer available (need brew or go).\n"
            "  macOS: brew install bakks/tap/butterfish\n"
            "  Go:    go install github.com/bakks/butterfish/cmd/butterfish@latest",
            file=sys.stderr,
        )
        return None

    should_install = auto_yes or _auto_install_enabled()
    if not should_install:
        if not sys.stdin.isatty():
            print(
                "Butterfish not installed (non-interactive). "
                "Set ARKA_AUTO_INSTALL=1 or run: goal -y --butterfish …",
                file=sys.stderr,
            )
            return None
        try:
            answer = input("Install Butterfish for Goal Mode? [y/N]: ").strip()
        except EOFError:
            return None
        should_install = answer.lower().startswith("y")

    if not should_install:
        print("Skipped Butterfish install.", file=sys.stderr)
        return None

    for label, cmd in plan:
        print(f"Installing Butterfish via {label}: {' '.join(cmd)}", file=sys.stderr)
        try:
            proc = subprocess.run(cmd, timeout=600)
        except (OSError, subprocess.TimeoutExpired) as exc:
            print(f"  Install failed: {exc}", file=sys.stderr)
            continue
        if proc.returncode != 0:
            print(f"  Install exited {proc.returncode}", file=sys.stderr)
            continue
        _go_bin_on_path()
        found = find_butterfish()
        if found:
            print(f"✓ Butterfish ready: {found}", file=sys.stderr)
            return found

    print("Could not install Butterfish. Try manually:", file=sys.stderr)
    for _, cmd in plan:
        print(f"  {' '.join(cmd)}", file=sys.stderr)
    return None


def launch_shell(*, goal: str = "", unsafe: bool = False, auto_yes: bool = False) -> int:
    """Start interactive Butterfish shell (Goal Mode is !goal inside the shell)."""
    bf = ensure_butterfish(auto_yes=auto_yes)
    if not bf:
        return 127

    prefix = "!!" if unsafe else "!"
    print("Butterfish Goal Mode (interactive shell)", file=sys.stderr)
    print(f"  Type {prefix}<your goal> after the shell starts.", file=sys.stderr)
    if goal.strip():
        print(f"  Suggested goal: {prefix}{goal.strip()}", file=sys.stderr)
    print("  Exit Goal Mode with Ctrl-C when done.", file=sys.stderr)
    print("", file=sys.stderr)

    env = os.environ.copy()
    if goal.strip():
        env["ARKA_BUTTERFISH_SUGGESTED_GOAL"] = goal.strip()

    try:
        return subprocess.call([bf, "shell"], env=env)
    except OSError as exc:
        print(f"Could not start butterfish: {exc}", file=sys.stderr)
        return 1
