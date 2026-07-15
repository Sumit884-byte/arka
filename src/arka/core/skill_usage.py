"""Local, opt-out skill usage counters; no prompts or arguments are stored."""
from __future__ import annotations
import json
import os
import time
from collections import Counter
from pathlib import Path
from arka.paths import cache_dir

def _path() -> Path:
    return cache_dir() / "skill-usage.json"

def enabled() -> bool:
    return os.environ.get("ARKA_USAGE_TRACKING", "1").lower() not in {"0", "false", "off", "no"}

def record(skill: str, exit_code: int, duration_ms: float) -> None:
    if not enabled() or skill in {"usage", "skill_usage"}:
        return
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        data = json.loads(path.read_text(encoding="utf-8")) if path.is_file() else {"events": []}
    except (OSError, json.JSONDecodeError):
        data = {"events": []}
    data.setdefault("events", []).append({"skill": skill, "ok": exit_code == 0, "duration_ms": round(duration_ms, 1), "ts": int(time.time())})
    data["events"] = data["events"][-5000:]
    path.write_text(json.dumps(data), encoding="utf-8")

def report() -> dict:
    try:
        data = json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        data = {"events": []}
    events = data.get("events", [])
    counts = Counter(e.get("skill", "unknown") for e in events)
    return {"enabled": enabled(), "total": len(events), "skills": counts.most_common(), "path": str(_path())}
