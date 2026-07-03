#!/usr/bin/env python3
"""Disk space breakdown by category (videos, pictures, documents, etc.)."""

from __future__ import annotations

import argparse
import csv
import os
import platform
import shutil
import subprocess
from concurrent.futures import ThreadPoolExecutor, as_completed
from dataclasses import dataclass, field
from datetime import datetime, timezone
from pathlib import Path

from arka.core.compute import io_workers, log_compute_summary

HOME = Path.home()
CACHE = Path.home() / ".cache" / "fish-agent"
DEFAULT_CSV = CACHE / "disk_breakdown.csv"

CATEGORY_PATHS: list[tuple[str, list[str]]] = [
    ("Videos", ["Videos", "Movies"]),
    ("Pictures", ["Pictures", "Photos"]),
    ("Documents", ["Documents"]),
    ("Music", ["Music", "music"]),
    ("Downloads", ["Downloads"]),
    ("Desktop", ["Desktop"]),
    ("Projects & code", ["Projects", "Development", "dev", "code", "github", "GitHub"]),
    ("Cache", [".cache"]),
    ("App data", [".local/share"]),
    ("Snap apps", ["snap"]),
    ("Flatpak data", [".var"]),
    ("Config", [".config"]),
]

EXT_CATEGORIES: list[tuple[str, set[str]]] = [
    ("Videos", {".mp4", ".mkv", ".avi", ".mov", ".webm", ".m4v", ".wmv", ".flv", ".mpeg", ".mpg", ".3gp"}),
    ("Pictures", {".jpg", ".jpeg", ".png", ".gif", ".webp", ".bmp", ".svg", ".heic", ".heif", ".raw"}),
    ("Documents", {".pdf", ".doc", ".docx", ".odt", ".txt", ".rtf", ".xls", ".xlsx", ".ods", ".csv", ".ppt", ".pptx", ".md", ".epub"}),
    ("Music", {".mp3", ".flac", ".wav", ".m4a", ".aac", ".ogg", ".opus", ".wma"}),
    ("Archives", {".zip", ".tar", ".gz", ".bz2", ".xz", ".7z", ".rar", ".deb", ".rpm", ".appimage", ".iso"}),
    ("Code", {".py", ".js", ".ts", ".go", ".rs", ".java", ".c", ".cpp", ".fish", ".sh", ".html", ".css", ".json"}),
]


@dataclass
class BreakdownData:
    home: Path
    mount: str
    total: str
    used: str
    avail: str
    pct: str
    totals: dict[str, int] = field(default_factory=dict)
    paths: dict[str, list[str]] = field(default_factory=dict)
    notes: list[str] = field(default_factory=list)
    downloads_ext: dict[str, int] = field(default_factory=dict)
    scanned_at: str = ""


def fmt_size(n: int) -> str:
    size = max(0, float(n))
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if size < 1024.0 or unit == "TB":
            if unit == "B":
                return f"{int(size)} {unit}"
            return f"{size:.1f} {unit}"
        size /= 1024.0
    return f"{size:.1f} TB"


def _is_macos() -> bool:
    try:
        from arka.core.platform import cached_platform

        plat = cached_platform()
        if plat:
            return plat == "macos"
    except ImportError:
        pass
    return platform.system() == "Darwin"


def du_bytes(path: Path) -> int | None:
    if not path.exists():
        return 0
    try:
        if _is_macos():
            proc = subprocess.run(
                ["du", "-sk", str(path)],
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0:
                return int(proc.stdout.split()[0]) * 1024
        else:
            proc = subprocess.run(
                ["du", "-sb", str(path)],
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0:
                return int(proc.stdout.split()[0])
    except (FileNotFoundError, ValueError, IndexError):
        pass
    try:
        total = 0
        for root, _dirs, files in os.walk(path, onerror=lambda _e: None):
            for name in files:
                try:
                    total += (Path(root) / name).stat().st_size
                except OSError:
                    continue
        return total
    except OSError:
        return None


def df_summary(path: Path) -> tuple[str, str, str, str, str]:
    mount = str(path)
    try:
        proc = subprocess.run(["df", "-h", str(path)], capture_output=True, text=True)
        if proc.returncode == 0:
            parts = proc.stdout.strip().splitlines()[-1].split()
            if len(parts) >= 5:
                # Linux: ... Size Used Avail Use% Mount
                # macOS: ... Size Used Avail Capacity iused ifree %iused Mount
                return parts[1], parts[2], parts[3], parts[4], parts[-1]
    except FileNotFoundError:
        pass
    try:
        usage = shutil.disk_usage(path)
        total = fmt_size(usage.total)
        used = fmt_size(usage.used)
        avail = fmt_size(usage.free)
        pct = f"{usage.used / usage.total * 100:.0f}%" if usage.total else "?"
        return total, used, avail, pct, mount
    except OSError:
        pass
    return "?", "?", "?", "?", mount


def scan_extensions(root: Path, max_depth: int = 3) -> dict[str, int]:
    totals: dict[str, int] = {label: 0 for label, _ in EXT_CATEGORIES}
    totals["Other files"] = 0
    if not root.is_dir():
        return totals

    if not _is_macos():
        try:
            proc = subprocess.run(
                ["find", str(root), "-xdev", "-maxdepth", str(max_depth), "-type", "f", "-printf", "%s %f\n"],
                capture_output=True,
                text=True,
            )
            if proc.returncode == 0:
                for line in proc.stdout.splitlines():
                    parts = line.split(" ", 1)
                    if len(parts) != 2:
                        continue
                    try:
                        size = int(parts[0])
                    except ValueError:
                        continue
                    ext = Path(parts[1]).suffix.lower()
                    label = "Other files"
                    for cat, exts in EXT_CATEGORIES:
                        if ext in exts:
                            label = cat
                            break
                    totals[label] = totals.get(label, 0) + size
                return totals
        except FileNotFoundError:
            pass

    root_parts = len(root.resolve().parts)
    try:
        for dirpath, dirnames, filenames in os.walk(root, topdown=True, onerror=lambda _e: None):
            cur = Path(dirpath)
            depth = len(cur.resolve().parts) - root_parts
            if depth >= max_depth:
                dirnames.clear()
                continue
            for name in filenames:
                try:
                    size = (cur / name).stat().st_size
                except OSError:
                    continue
                ext = Path(name).suffix.lower()
                label = "Other files"
                for cat, exts in EXT_CATEGORIES:
                    if ext in exts:
                        label = cat
                        break
                totals[label] = totals.get(label, 0) + size
    except OSError:
        pass
    return totals


def category_sizes(home: Path) -> tuple[dict[str, int], dict[str, list[str]], list[str]]:
    """Measure known folders in parallel (no timeout — waits for du to finish)."""
    jobs: list[tuple[str, Path]] = []
    for cat, names in CATEGORY_PATHS:
        for name in names:
            p = home / name
            if p.exists():
                jobs.append((cat, p))

    totals: dict[str, int] = {}
    paths: dict[str, list[str]] = {}
    notes: list[str] = []

    with ThreadPoolExecutor(max_workers=io_workers(8)) as pool:
        fut_map = {pool.submit(du_bytes, p): (cat, p) for cat, p in jobs}
        for fut in as_completed(fut_map):
            cat, p = fut_map[fut]
            size = fut.result()
            rel = f"~/{p.relative_to(home)}"
            if size is None:
                notes.append(f"(could not measure {rel})")
                continue
            if size <= 0:
                continue
            totals[cat] = totals.get(cat, 0) + size
            paths.setdefault(cat, []).append(f"{rel} ({fmt_size(size)})")

    return totals, paths, notes


def collect_breakdown(root: Path | None = None) -> BreakdownData:
    home = (root or HOME).expanduser()
    if not home.exists():
        home = HOME
    home = home.resolve()
    total, used, avail, pct, mount = df_summary(home)
    totals, paths, notes = category_sizes(home)

    downloads_ext: dict[str, int] = {}
    dl = home / "Downloads"
    if dl.is_dir():
        downloads_ext = scan_extensions(dl, max_depth=3)

    return BreakdownData(
        home=home,
        mount=mount,
        total=total,
        used=used,
        avail=avail,
        pct=pct,
        totals=totals,
        paths=paths,
        notes=notes,
        downloads_ext=downloads_ext,
        scanned_at=datetime.now(timezone.utc).astimezone().isoformat(timespec="seconds"),
    )


def write_csv(data: BreakdownData, csv_path: Path) -> Path:
    """Write breakdown to CSV, replacing any existing file."""
    csv_path = csv_path.expanduser().resolve()
    csv_path.parent.mkdir(parents=True, exist_ok=True)

    scanned = sum(data.totals.values())
    ext_used = sum(data.downloads_ext.values())

    with csv_path.open("w", newline="", encoding="utf-8") as fh:
        w = csv.writer(fh)
        w.writerow(["section", "category", "path", "bytes", "size_human", "percent", "note"])
        w.writerow(["meta", "scanned_at", str(data.home), "", "", "", data.scanned_at])
        w.writerow(["overview", "mount", data.mount, "", "", "", ""])
        w.writerow(["overview", "total", "", "", data.total, "", ""])
        w.writerow(["overview", "used", "", "", data.used, data.pct, ""])
        w.writerow(["overview", "free", "", "", data.avail, "", ""])

        for cat, size in sorted(data.totals.items(), key=lambda x: x[1], reverse=True):
            pct_s = (size / scanned * 100) if scanned else 0
            where = "; ".join(data.paths.get(cat, []))
            w.writerow(["category", cat, where, size, fmt_size(size), f"{pct_s:.1f}", ""])

        for label, size in sorted(data.downloads_ext.items(), key=lambda x: x[1], reverse=True):
            if size <= 0:
                continue
            pct_d = (size / ext_used * 100) if ext_used else 0
            w.writerow(["downloads", label, "~/Downloads", size, fmt_size(size), f"{pct_d:.1f}", ""])

        for note in data.notes:
            w.writerow(["note", "", "", "", "", "", note])

    return csv_path


def format_report(data: BreakdownData, csv_path: Path | None = None) -> str:
    lines: list[str] = []
    lines.append(f"Disk ({data.mount}): {data.total} total, {data.used} used, {data.avail} free ({data.pct} full)")

    scanned = sum(data.totals.values())
    if data.totals:
        ranked = sorted(data.totals.items(), key=lambda x: x[1], reverse=True)[:3]
        parts = [f"{cat} {fmt_size(size)}" for cat, size in ranked]
        lines.append(f"Top storage: {', '.join(parts)}. ({data.used} used on disk)")
    lines.append("")

    if data.totals:
        lines.append(f"By category ({fmt_size(scanned)} measured in known folders):")
        for cat, size in sorted(data.totals.items(), key=lambda x: x[1], reverse=True):
            pct_s = (size / scanned * 100) if scanned else 0
            where = "; ".join(data.paths.get(cat, [])[:2])
            lines.append(f"  {cat:<16} {fmt_size(size):>8}  ({pct_s:4.0f}%)  {where}")
        lines.append("")

    ext_used = sum(data.downloads_ext.values())
    if ext_used > 0:
        lines.append(f"Downloads by file type ({fmt_size(ext_used)}):")
        for label, size in sorted(data.downloads_ext.items(), key=lambda x: x[1], reverse=True):
            if size <= 0:
                continue
            pct_d = size / ext_used * 100
            lines.append(f"  {label:<16} {fmt_size(size):>8}  ({pct_d:4.0f}%)")
        lines.append("")

    if data.notes:
        lines.append("Notes:")
        for note in data.notes:
            lines.append(f"  {note}")
        lines.append("")

    if csv_path:
        lines.append(f"CSV saved: {csv_path}")
    lines.append("Tip: arka disk  |  disk_usage ~/Videos  |  dust ~")
    return "\n".join(lines)


def breakdown_report(root: Path | None = None, csv_path: Path | None = None) -> tuple[str, Path]:
    data = collect_breakdown(root)
    out_csv = Path(csv_path or os.environ.get("DISK_CSV", DEFAULT_CSV))
    write_csv(data, out_csv)
    return format_report(data, out_csv), out_csv


def main() -> int:
    log_compute_summary()
    parser = argparse.ArgumentParser(description="Arka disk space breakdown")
    sub = parser.add_subparsers(dest="cmd")

    p_br = sub.add_parser("breakdown", help="Space by videos, pictures, documents, etc.")
    p_br.add_argument("path", nargs="?", default=str(HOME))
    p_br.add_argument("--csv", default="", help="CSV output path (default: ~/.cache/fish-agent/disk_breakdown.csv)")

    args = parser.parse_args()
    csv_arg = Path(args.csv) if getattr(args, "csv", "") else None

    if args.cmd == "breakdown":
        text, _saved = breakdown_report(Path(args.path), csv_arg)
        print(text)
        return 0

    text, _saved = breakdown_report(HOME, csv_arg)
    print(text)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
