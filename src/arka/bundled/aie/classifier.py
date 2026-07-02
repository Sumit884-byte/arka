#!/usr/bin/env python3
"""Auto-sort new files in Downloads by type."""

from __future__ import annotations

import shutil
from pathlib import Path

from _common import log, run_forever, watch_dir

RULES: list[tuple[str, tuple[str, ...]]] = [
    ("images", (".png", ".jpg", ".jpeg", ".gif", ".webp", ".heic", ".svg", ".bmp", ".tiff")),
    ("documents", (".pdf", ".doc", ".docx", ".txt", ".md", ".rtf", ".odt", ".pages")),
    ("spreadsheets", (".csv", ".xls", ".xlsx", ".ods", ".numbers")),
    ("presentations", (".ppt", ".pptx", ".key", ".odp")),
    ("archives", (".zip", ".tar", ".gz", ".tgz", ".bz2", ".7z", ".rar")),
    ("installers", (".dmg", ".pkg", ".deb", ".rpm", ".msi", ".exe", ".app")),
    ("code", (".py", ".js", ".ts", ".tsx", ".jsx", ".json", ".yaml", ".yml", ".toml", ".sh", ".fish", ".html", ".css")),
    ("media", (".mp4", ".mkv", ".mov", ".mp3", ".wav", ".m4a", ".aac", ".flac")),
]

SEEN: set[str] = set()


def _bucket(path: Path) -> str | None:
    ext = path.suffix.lower()
    for name, exts in RULES:
        if ext in exts:
            return name
    return None


def _classify(path: Path) -> None:
    if not path.is_file() or path.name.startswith("."):
        return
    bucket = _bucket(path)
    if not bucket:
        return
    dest_dir = path.parent / bucket
    dest_dir.mkdir(parents=True, exist_ok=True)
    dest = dest_dir / path.name
    if dest.exists():
        return
    shutil.move(str(path), str(dest))
    log(f"aie/classify: {path.name} → {bucket}/")


def _scan() -> None:
    root = watch_dir()
    if not root.is_dir():
        return
    for path in root.iterdir():
        key = str(path.resolve())
        if key in SEEN:
            continue
        SEEN.add(key)
        try:
            _classify(path)
        except OSError as exc:
            log(f"aie/classify: failed {path.name}: {exc}")


def main() -> int:
    root = watch_dir()
    try:
        root.mkdir(parents=True, exist_ok=True)
        for path in root.iterdir():
            SEEN.add(str(path.resolve()))
    except OSError as exc:
        log(f"aie/classify: cannot access {root}: {exc}")
        return 1
    return run_forever("classify", _scan)


if __name__ == "__main__":
    raise SystemExit(main())
