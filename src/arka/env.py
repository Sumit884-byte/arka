"""Load .env into os.environ (cross-platform)."""

from __future__ import annotations

import os
import re
from pathlib import Path

from arka.paths import arka_home, cache_dir, checkout_root, config_dir, env_file

_PLACEHOLDER_RE = re.compile(
    r"your_.*_here|^changeme$|^xxx+$|^replace[_-]?me$",
    re.IGNORECASE,
)


def _is_placeholder(val: str) -> bool:
    v = (val or "").strip()
    if not v:
        return True
    return bool(_PLACEHOLDER_RE.search(v))


def _apply_env_file(path: Path) -> None:
    for line in path.read_text(encoding="utf-8", errors="replace").splitlines():
        line = line.strip()
        if not line or line.startswith("#") or "=" not in line:
            continue
        key, _, val = line.partition("=")
        key = key.strip()
        val = val.strip().strip("'\"")
        val = re.sub(r"\s+#.*$", "", val).strip()
        if not key or _is_placeholder(val):
            continue
        current = os.environ.get(key, "").strip()
        if not current or _is_placeholder(current):
            os.environ[key] = val


def load_env(extra: Path | None = None) -> None:
    paths: list[Path] = []
    if extra:
        paths.append(extra)
    paths.append(env_file())
    legacy = Path.home() / ".config" / "fish" / ".env"
    if legacy.is_file():
        paths.append(legacy)
    root = checkout_root()
    if root:
        dev_env = root / ".env"
        if dev_env.is_file():
            paths.append(dev_env)
    home_env = arka_home() / ".env"
    if home_env.is_file():
        paths.append(home_env)

    seen: set[Path] = set()
    for path in paths:
        path = path.expanduser().resolve()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        _apply_env_file(path)

    os.environ.setdefault("ARKA_CONFIG_DIR", str(config_dir()))
    os.environ.setdefault("ARKA_CACHE_DIR", str(cache_dir()))
