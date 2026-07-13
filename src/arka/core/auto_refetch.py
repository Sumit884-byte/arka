"""Lightweight auto-refetch when the Arka checkout is behind origin."""

from __future__ import annotations

import subprocess
import sys
import time
from pathlib import Path

REFETCH_TTL_SECONDS = 3600


def _stamp_file() -> Path:
    from arka.paths import config_dir

    return config_dir() / "last-refetch"


def _touch_stamp() -> None:
    try:
        _stamp_file().write_text(str(time.time()), encoding="utf-8")
    except OSError:
        pass


def _stamp_stale(*, ttl: int = REFETCH_TTL_SECONDS) -> bool:
    path = _stamp_file()
    if not path.is_file():
        return True
    try:
        last = float(path.read_text(encoding="utf-8").strip())
    except (OSError, ValueError):
        return True
    return (time.time() - last) >= ttl


def _run_refetch(*, quiet: bool = True) -> int:
    from arka.paths import bundled_dir, checkout_root, ensure_layout

    root = checkout_root()
    if root is None:
        return 1

    if not quiet:
        print("→ git pull", file=sys.stderr)
    pull = subprocess.run(["git", "pull", "--ff-only"], cwd=root)
    if pull.returncode != 0:
        if not quiet:
            print("git pull failed", file=sys.stderr)
        return pull.returncode

    sync = root / "scripts" / "sync_bundled.py"
    if sync.is_file():
        if not quiet:
            print("→ sync bundled scripts", file=sys.stderr)
        r = subprocess.run([sys.executable, str(sync)], cwd=root)
        if r.returncode != 0:
            return r.returncode
    else:
        if not quiet:
            print(f"Missing {sync}", file=sys.stderr)
        return 1

    ensure_layout()
    try:
        from arka.agent.repo_context import sync_index

        idx = sync_index(root, quiet=True)
        if not quiet and idx.get("ok") and not idx.get("skipped"):
            print(f"→ llm.txt changelog: {idx.get('changed', 0)} file(s)", file=sys.stderr)
    except ImportError:
        pass
    if not quiet:
        print(f"✓ Refetch complete — bundle: {bundled_dir()}", file=sys.stderr)
    return 0


def maybe_auto_refetch(*, force: bool = False, quiet: bool = True) -> bool:
    """Pull + sync bundled if the checkout is behind origin. Returns True if refetch ran."""
    if not force and not _stamp_stale():
        return False

    try:
        from arka.paths import checkout_root
    except ImportError:
        _touch_stamp()
        return False

    root = checkout_root()
    if root is None or not (root / ".git").is_dir():
        _touch_stamp()
        return False

    fetch = subprocess.run(
        ["git", "fetch", "--quiet", "origin"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    if fetch.returncode != 0:
        _touch_stamp()
        return False

    behind = subprocess.run(
        ["git", "rev-list", "--count", "HEAD..@{u}"],
        cwd=root,
        capture_output=True,
        text=True,
    )
    count = behind.stdout.strip() if behind.returncode == 0 else ""
    if count in ("", "0"):
        _touch_stamp()
        return False

    if not quiet:
        print(f"→ Arka is {count} commit(s) behind — refetching…", file=sys.stderr)

    rc = _run_refetch(quiet=quiet)
    _touch_stamp()
    return rc == 0
