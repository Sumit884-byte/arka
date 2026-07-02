#!/usr/bin/env python3
"""Watch a folder and auto-extract new zip archives."""

from __future__ import annotations

import shutil
import zipfile
from pathlib import Path

from _common import log, run_forever, watch_dir

SEEN: set[str] = set()


def _extract_zip(path: Path) -> None:
    dest = path.with_suffix("")
    if dest.exists():
        log(f"aie/zip: skip {path.name} (folder exists)")
        return
    dest.mkdir(parents=True, exist_ok=True)
    with zipfile.ZipFile(path, "r") as zf:
        zf.extractall(dest)
    log(f"aie/zip: extracted {path.name} → {dest.name}/")


def _scan() -> None:
    root = watch_dir()
    if not root.is_dir():
        return
    for path in sorted(root.glob("*.zip")):
        key = str(path.resolve())
        if key in SEEN:
            continue
        SEEN.add(key)
        try:
            if path.stat().st_size == 0:
                continue
            _extract_zip(path)
        except (OSError, zipfile.BadZipFile) as exc:
            log(f"aie/zip: failed {path.name}: {exc}")


def main() -> int:
    root = watch_dir()
    try:
        root.mkdir(parents=True, exist_ok=True)
        for path in root.glob("*.zip"):
            SEEN.add(str(path.resolve()))
    except OSError as exc:
        log(f"aie/zip: cannot access {root}: {exc}")
        return 1
    return run_forever("zip", _scan)


if __name__ == "__main__":
    raise SystemExit(main())
