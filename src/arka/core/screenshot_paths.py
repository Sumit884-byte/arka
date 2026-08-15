"""Standard screenshot paths with timestamp suffixes and latest-image lookup."""

from __future__ import annotations

import os
import re
from datetime import datetime
from pathlib import Path

_TIMESTAMP_SUFFIX = re.compile(
    r"-(?P<ts>\d{8}-\d{6})(?:-(?P<seq>\d{2}))?\.(?P<ext>png|jpe?g|webp|gif|bmp)$",
    re.IGNORECASE,
)
_IMAGE_EXTENSIONS = frozenset({".png", ".jpg", ".jpeg", ".webp", ".gif", ".bmp"})


def screenshot_timestamp(when: datetime | None = None) -> str:
    """Return ``YYYYMMDD-HHMMSS`` for screenshot filenames."""
    return (when or datetime.now()).strftime("%Y%m%d-%H%M%S")


def slugify_prefix(prefix: str) -> str:
    slug = re.sub(r"[^\w\-]+", "-", (prefix or "").strip().lower())
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "screenshot"


def default_screenshot_dir() -> Path:
    env = os.environ.get("ARKA_SCREENSHOT_DIR", "").strip()
    if env:
        return Path(env).expanduser()
    try:
        from arka.paths import config_dir

        return config_dir() / "screenshots"
    except ImportError:
        return Path.home() / ".config" / "arka" / "screenshots"


def screenshot_dir(directory: Path | str | None = None) -> Path:
    """Resolve and create the screenshot output directory."""
    target = Path(directory).expanduser() if directory else default_screenshot_dir()
    target.mkdir(parents=True, exist_ok=True)
    return target


def screenshot_path(
    prefix: str = "screenshot",
    directory: Path | str | None = None,
    *,
    ext: str = ".png",
    when: datetime | None = None,
) -> Path:
    """Build ``{prefix}-{YYYYMMDD-HHMMSS}.png`` under ``directory``."""
    target = screenshot_dir(directory)
    slug = slugify_prefix(prefix)
    suffix = ext if ext.startswith(".") else f".{ext}"
    stamp = screenshot_timestamp(when)
    candidate = target / f"{slug}-{stamp}{suffix}"
    if not candidate.exists():
        return candidate
    for index in range(2, 1000):
        alt = target / f"{slug}-{stamp}-{index:02d}{suffix}"
        if not alt.exists():
            return alt
    return candidate


def resolve_screenshot_output(
    output: str | None,
    *,
    prefix: str,
    default_dir: Path | str | None = None,
) -> Path:
    """Map CLI ``--output`` to a timestamped screenshot path."""
    if not output:
        return screenshot_path(prefix, default_dir)
    path = Path(output).expanduser()
    if path.suffix.lower() in _IMAGE_EXTENSIONS:
        return screenshot_path(path.stem or prefix, path.parent)
    return screenshot_path(prefix, path)


def parse_screenshot_timestamp(path: Path | str) -> datetime | None:
    """Parse the trailing timestamp from a standardized screenshot filename."""
    match = _TIMESTAMP_SUFFIX.search(Path(path).name)
    if not match:
        return None
    try:
        return datetime.strptime(match.group("ts"), "%Y%m%d-%H%M%S")
    except ValueError:
        return None


def _matches_prefix(path: Path, prefix: str | None) -> bool:
    if not prefix:
        return path.suffix.lower() in _IMAGE_EXTENSIONS
    slug = slugify_prefix(prefix)
    name = path.name.lower()
    return name.startswith(f"{slug}-") or name == f"{slug}.png"


def list_screenshots(directory: Path | str, *, prefix: str | None = None) -> list[Path]:
    """List screenshot files newest-first (timestamp suffix, then mtime)."""
    base = Path(directory).expanduser()
    if not base.is_dir():
        return []
    candidates = [path for path in base.iterdir() if path.is_file() and _matches_prefix(path, prefix)]
    return sorted(
        candidates,
        key=lambda path: (
            parse_screenshot_timestamp(path) or datetime.fromtimestamp(0),
            path.stat().st_mtime,
        ),
        reverse=True,
    )


def latest_screenshot(directory: Path | str, *, prefix: str | None = None) -> Path | None:
    """Return the newest screenshot in ``directory``, optionally filtered by prefix."""
    shots = list_screenshots(directory, prefix=prefix)
    return shots[0] if shots else None


def docs_screenshot_context(*, directory: Path | str | None = None, limit: int = 5) -> str:
    """Markdown snippet listing recent screenshots for README/doc writers."""
    shots = list_screenshots(directory or default_screenshot_dir())[: max(1, limit)]
    if not shots:
        return ""
    lines = [
        "Latest captured screenshots (prefer the most recent path when embedding UI images):",
    ]
    for shot in shots:
        lines.append(f"- `{shot}`")
    lines.append(f"Primary image: `{shots[0]}`")
    return "\n".join(lines)
