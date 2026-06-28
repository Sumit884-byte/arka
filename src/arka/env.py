"""Load .env into os.environ (cross-platform)."""

from __future__ import annotations

import os
from pathlib import Path

from arka.paths import cache_dir, config_dir, env_file


def load_env(extra: Path | None = None) -> None:
    paths: list[Path] = []
    if extra:
        paths.append(extra)
    paths.append(env_file())
    legacy = Path.home() / ".config" / "fish" / ".env"
    if legacy.is_file():
        paths.append(legacy)

    seen: set[Path] = set()
    for path in paths:
        path = path.expanduser()
        if path in seen or not path.is_file():
            continue
        seen.add(path)
        for line in path.read_text(encoding="utf-8").splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            key, _, val = line.partition("=")
            key = key.strip()
            val = val.strip().strip("'\"")
            if key and key not in os.environ:
                os.environ[key] = val

    os.environ.setdefault("ARKA_CONFIG_DIR", str(config_dir()))
    os.environ.setdefault("ARKA_CACHE_DIR", str(cache_dir()))
