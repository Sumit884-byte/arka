"""Session cache for hardware probe results (avoids repeated system_profiler calls)."""

from __future__ import annotations

import os
import time
from dataclasses import asdict
from typing import Any

try:
    from arka.paths import config_dir
except ImportError:

    def config_dir() -> Path:  # type: ignore[misc]
        from pathlib import Path

        return Path.home() / ".config" / "arka"


from pathlib import Path

_SESSION_HW: dict[str, Any] | None = None
_SESSION_TS: float = 0.0
_PROBE_COUNT: int = 0


def hardware_cache_enabled() -> bool:
    return os.environ.get("ARKA_HARDWARE_CACHE", "1").strip().lower() not in {
        "0",
        "false",
        "no",
        "off",
    }


def cache_ttl_seconds() -> float:
    raw = os.environ.get("ARKA_HARDWARE_CACHE_TTL", "300").strip()
    try:
        return max(1.0, float(raw))
    except ValueError:
        return 300.0


def hardware_cache_path() -> Path:
    return config_dir() / "hardware_cache.json"


def probe_count() -> int:
    """Number of live hardware probes since process start (for tests)."""
    return _PROBE_COUNT


def clear_hardware_cache() -> None:
    global _SESSION_HW, _SESSION_TS, _PROBE_COUNT
    _SESSION_HW = None
    _SESSION_TS = 0.0
    _PROBE_COUNT = 0


def get_cached_hardware() -> Any | None:
    """Return cached HardwareSnapshot if still fresh, else None."""
    if not hardware_cache_enabled():
        return None

    from arka.llm.model_advisor import HardwareSnapshot

    global _SESSION_HW, _SESSION_TS
    now = time.time()
    ttl = cache_ttl_seconds()

    if _SESSION_HW is not None and (now - _SESSION_TS) < ttl:
        return HardwareSnapshot(**dict(_SESSION_HW))

    path = hardware_cache_path()
    if not path.is_file():
        return None
    try:
        import json

        data = json.loads(path.read_text(encoding="utf-8"))
        if not isinstance(data, dict):
            return None
        cached_at = float(data.get("cached_at", 0))
        snap = data.get("hardware")
        if not isinstance(snap, dict) or (now - cached_at) >= ttl:
            return None
        _SESSION_HW = dict(snap)
        _SESSION_TS = cached_at
        return HardwareSnapshot(**dict(snap))
    except (OSError, ValueError, TypeError, json.JSONDecodeError):
        return None


def remember_hardware(hw: Any) -> None:
    """Store a hardware snapshot in session and disk cache."""
    if not hardware_cache_enabled():
        return

    global _SESSION_HW, _SESSION_TS
    snap = asdict(hw)
    _SESSION_HW = dict(snap)
    _SESSION_TS = time.time()

    try:
        import json

        path = hardware_cache_path()
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(
            json.dumps({"cached_at": _SESSION_TS, "hardware": snap}, indent=2),
            encoding="utf-8",
        )
    except OSError:
        pass


def note_hardware_probe() -> None:
    global _PROBE_COUNT
    _PROBE_COUNT += 1
