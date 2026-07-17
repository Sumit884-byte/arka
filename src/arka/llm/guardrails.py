"""Local cost/performance guardrails for development inference."""

from __future__ import annotations
import argparse
import json
import os
from pathlib import Path
from arka.paths import cache_dir


def _path() -> Path:
    return cache_dir() / "llm-guardrails.json"


def limits() -> dict[str, float]:
    return {
        "cost_usd": float(os.environ.get("ARKA_COST_LIMIT_USD", "0")),
        "tokens": float(os.environ.get("ARKA_TOKEN_LIMIT", "0")),
        "latency_ms": float(os.environ.get("ARKA_LATENCY_LIMIT_MS", "0")),
    }


def state() -> dict:
    try:
        return json.loads(_path().read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"cost_usd": 0.0, "tokens": 0, "requests": 0, "last_latency_ms": 0.0}


def preflight(prompt: str, *, hosted: bool) -> tuple[bool, str]:
    if not hosted:
        return True, "local"
    current = state()
    cap = limits()
    estimate = max(1, len(prompt) // 4)
    if cap["tokens"] and current["tokens"] + estimate > cap["tokens"]:
        return False, "token budget exceeded"
    if cap["cost_usd"] and current["cost_usd"] + estimate * 0.00001 > cap["cost_usd"]:
        return False, "cost budget exceeded"
    return True, "ok"


def record(prompt: str, *, latency_ms: float, hosted: bool) -> None:
    if not hosted:
        return
    data = state()
    tokens = max(1, len(prompt) // 4)
    data["tokens"] += tokens
    data["cost_usd"] += tokens * 0.00001
    data["requests"] += 1
    data["last_latency_ms"] = round(latency_ms, 1)
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(data), encoding="utf-8")
    except OSError:
        # Guardrail accounting must never turn a successful model response into
        # a failure in read-only containers; callers still have the limits in
        # memory for this process.
        return


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="arka guardrails")
    p.add_argument("command", choices=("status", "reset"), nargs="?", default="status")
    a = p.parse_args(argv)
    if a.command == "reset":
        _path().unlink(missing_ok=True)
    print(json.dumps({"limits": limits(), "usage": state()}, indent=2))
    return 0
