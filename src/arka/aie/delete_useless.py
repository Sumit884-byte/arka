#!/usr/bin/env python3
"""Remove installer/archive clutter from Downloads."""

from __future__ import annotations

import sys
from pathlib import Path

from _common import downloads_dir, host_platform, log

JUNK_SUFFIXES = (
    ".zip",
    ".tar.gz",
    ".tgz",
    ".tar.bz2",
    ".tbz2",
    ".tar.xz",
    ".txz",
    ".deb",
    ".rpm",
    ".dmg",
    ".pkg",
    ".msi",
    ".exe",
    ".app",
)


def _is_junk(path: Path) -> bool:
    name = path.name.lower()
    return any(name.endswith(suffix) for suffix in JUNK_SUFFIXES)


def main() -> int:
    root = downloads_dir()
    if not root.is_dir():
        log(f"aie/cleanup: downloads folder not found: {root}")
        return 1
    removed = 0
    for path in sorted(root.iterdir()):
        if not path.is_file() or not _is_junk(path):
            continue
        try:
            path.unlink()
            removed += 1
            log(f"aie/cleanup: removed {path.name}")
        except OSError as exc:
            log(f"aie/cleanup: failed {path.name}: {exc}")
    log(f"aie/cleanup: done ({removed} file(s) removed from {root}) on {host_platform()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
