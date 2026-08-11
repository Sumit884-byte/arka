"""Zero-config LLM cost arbitrage — hot-swap providers using live pricing."""

from __future__ import annotations

import argparse
import json
import os
import re
import signal
import subprocess
import sys
import threading
import time
from dataclasses import asdict, dataclass
from pathlib import Path
from typing import Any

from arka.llm.fallback import (
    env,
    fetch_openrouter_models_live,
    normalize_openrouter_model,
    ollama_model_ids,
    openrouter_model_meta,
    provider_available,
)
from arka.llm.provider_select import get_preferred, set_env_vars, set_preferred_provider

CACHE = Path.home() / ".cache" / "fish-agent"
STATE_PATH = CACHE / "llm-arbitrage.json"
PID_PATH = CACHE / "llm-arbitrage.pid"

# Heuristic USD-ish cost index (lower is cheaper). OpenRouter uses live meta.
_CLOUD_COST_INDEX: dict[str, float] = {
    "ollama": 0.0,
    "vllm": 0.0,
    "vllm-cloud": 0.5,
    "apple-fm": 0.0,
    "lmstudio": 0.0,
    "groq": 0.08,
    "gemini": 0.12,
    "openrouter": 0.0,
    "mistral": 0.4,
    "together": 0.35,
    "fireworks": 0.35,
    "openai": 2.0,
    "anthropic": 2.5,
    "cohere": 0.6,
    "perplexity": 0.5,
}

_MONITOR_STOP = threading.Event()


@dataclass(frozen=True)
class CostCandidate:
    provider: str
    model: str
    cost: float
    source: str


def _truthy(name: str, default: str = "0") -> bool:
    return env(name, default).lower() in {"1", "true", "yes", "on"}


def _interval_seconds() -> float:
    try:
        return max(15.0, float(env("ARKA_ARBITRAGE_INTERVAL", "60")))
    except ValueError:
        return 60.0


def _min_savings_ratio() -> float:
    try:
        return max(0.0, min(1.0, float(env("ARKA_ARBITRAGE_MIN_SAVINGS", "0.15"))))
    except ValueError:
        return 0.15


def _state_path() -> Path:
    return STATE_PATH


def load_state() -> dict[str, Any]:
    path = _state_path()
    if not path.is_file():
        return {}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
        return data if isinstance(data, dict) else {}
    except (OSError, json.JSONDecodeError):
        return {}


def save_state(data: dict[str, Any]) -> None:
    CACHE.mkdir(parents=True, exist_ok=True)
    _state_path().write_text(json.dumps(data, indent=2) + "\n", encoding="utf-8")


def _model_cost_heuristic(provider: str, model_id: str) -> float:
    provider = provider.lower()
    model = (model_id or "").lower()
    if provider == "openrouter":
        if ":free" in model:
            return 0.0
        meta = openrouter_model_meta(model_id) or {}
        return float(meta.get("completion_price", 0.0) or 0.0)
    if provider in {"ollama", "vllm", "apple-fm", "lmstudio"}:
        return 0.0
    base = _CLOUD_COST_INDEX.get(provider, 1.0)
    tokens = set(re.split(r"[-_/:.]", model))
    if tokens & {"lite", "mini", "instant", "8b"} or "flash-lite" in model:
        return base * 0.35
    if tokens & {"70b", "pro", "opus", "sonnet-4", "gpt-4", "ultra", "enterprise"}:
        return base * 2.5
    return base


def estimate_cost(provider: str, model_id: str) -> float:
    return _model_cost_heuristic(provider, model_id)


def _add_candidate(
    out: list[CostCandidate],
    seen: set[tuple[str, str]],
    provider: str,
    model: str,
    *,
    source: str,
) -> None:
    provider = provider.strip().lower()
    model = (model or "").strip()
    if not provider or not model:
        return
    key = (provider, model)
    if key in seen:
        return
    if not provider_available(provider):
        return
    seen.add(key)
    out.append(
        CostCandidate(
            provider=provider,
            model=model,
            cost=estimate_cost(provider, model),
            source=source,
        )
    )


def rank_available_candidates(*, limit: int = 12) -> list[CostCandidate]:
    """Rank configured provider/model pairs by estimated cost (cheapest first)."""
    out: list[CostCandidate] = []
    seen: set[tuple[str, str]] = set()

    if provider_available("ollama"):
        for model in ollama_model_ids()[:5]:
            _add_candidate(out, seen, "ollama", model, source="local")

    if provider_available("openrouter"):
        live = fetch_openrouter_models_live()
        for model in live[:25]:
            _add_candidate(
                out,
                seen,
                "openrouter",
                normalize_openrouter_model(model),
                source="openrouter-live",
            )

    from arka.llm.providers import get_provider, provider_specs

    for spec in provider_specs():
        if spec.slug in {"ollama", "openrouter"}:
            continue
        if not provider_available(spec.slug):
            continue
        models = list(spec.default_models or [])
        if spec.default_model:
            models.insert(0, spec.default_model)
        for model in models[:4]:
            _add_candidate(out, seen, spec.slug, model, source="catalog")

    pref_provider, pref_model = get_preferred()
    if pref_provider and pref_model:
        _add_candidate(out, seen, pref_provider, pref_model, source="preferred")

    out.sort(key=lambda row: (row.cost, row.provider, row.model))
    return out[: max(1, limit)]


def evaluate_swap(*, min_savings_ratio: float | None = None) -> dict[str, Any] | None:
    """Return a swap decision when a materially cheaper provider is available."""
    current_provider, current_model = get_preferred()
    if not current_provider or not current_model:
        return None

    candidates = rank_available_candidates()
    if not candidates:
        return None

    current_cost = estimate_cost(current_provider, current_model)
    best = candidates[0]
    if best.provider == current_provider and best.model == current_model:
        return None

    best_cost = best.cost
    threshold = _min_savings_ratio() if min_savings_ratio is None else min_savings_ratio

    if current_cost <= 0 and best_cost <= 0:
        if best.provider == "ollama" and current_provider != "ollama":
            savings_ratio = 1.0
        else:
            return None
    elif current_cost <= 0:
        return None
    else:
        savings_ratio = (current_cost - best_cost) / max(current_cost, 1e-12)
        if savings_ratio < threshold and not (best_cost == 0.0 and current_cost > 0):
            return None

    return {
        "from": {"provider": current_provider, "model": current_model, "cost": current_cost},
        "to": {
            "provider": best.provider,
            "model": best.model,
            "cost": best_cost,
            "source": best.source,
        },
        "savings_ratio": round(savings_ratio, 4),
        "candidates": [asdict(row) for row in candidates[:6]],
    }


def apply_swap(decision: dict[str, Any], *, dry_run: bool = False) -> dict[str, Any]:
    """Hot-swap preferred provider; keep the old pair reachable for in-flight requests."""
    src = decision.get("from") or {}
    dst = decision.get("to") or {}
    from_provider = str(src.get("provider") or "").strip()
    from_model = str(src.get("model") or "").strip()
    to_provider = str(dst.get("provider") or "").strip()
    to_model = str(dst.get("model") or "").strip()
    if not to_provider or not to_model:
        raise ValueError("swap decision missing target provider/model")

    payload: dict[str, Any] = {
        "ok": True,
        "dry_run": dry_run,
        "from": {"provider": from_provider, "model": from_model},
        "to": {"provider": to_provider, "model": to_model},
        "savings_ratio": decision.get("savings_ratio"),
    }
    if dry_run:
        return payload

    slug, chosen, env_path = set_preferred_provider(
        to_provider,
        model=to_model,
        autodetect=False,
    )
    drain = f"{from_provider}:{from_model}" if from_provider and from_model else ""
    extra: dict[str, str | None] = {}
    if drain and (from_provider, from_model) != (slug, chosen):
        extra["ARKA_ARBITRAGE_DRAIN"] = drain
    if extra:
        set_env_vars(extra)

    state = load_state()
    state.update(
        {
            "last_swap_at": time.time(),
            "last_swap": payload | {"to": {"provider": slug, "model": chosen}},
            "draining": drain or None,
        }
    )
    save_state(state)
    payload["env_file"] = str(env_path)
    payload["to"] = {"provider": slug, "model": chosen}
    return payload


def run_once(*, dry_run: bool = False) -> dict[str, Any]:
    decision = evaluate_swap()
    if decision is None:
        pref_provider, pref_model = get_preferred()
        return {
            "ok": True,
            "swapped": False,
            "message": "already on cheapest available provider",
            "preferred": {"provider": pref_provider, "model": pref_model},
            "candidates": [asdict(row) for row in rank_available_candidates()[:6]],
        }
    result = apply_swap(decision, dry_run=dry_run)
    result["swapped"] = not dry_run
    return result


def status_payload() -> dict[str, Any]:
    pref_provider, pref_model = get_preferred()
    state = load_state()
    monitor_pid = None
    if PID_PATH.is_file():
        try:
            monitor_pid = int(PID_PATH.read_text(encoding="utf-8").strip())
        except ValueError:
            monitor_pid = None
    running = bool(monitor_pid and _pid_alive(monitor_pid))
    return {
        "enabled": _truthy("ARKA_ARBITRAGE_ENABLED", "0") or running,
        "monitor_running": running,
        "monitor_pid": monitor_pid,
        "interval_seconds": _interval_seconds(),
        "min_savings_ratio": _min_savings_ratio(),
        "preferred": {
            "provider": pref_provider,
            "model": pref_model,
            "cost": estimate_cost(pref_provider, pref_model) if pref_provider and pref_model else None,
        },
        "draining": state.get("draining"),
        "last_swap": state.get("last_swap"),
        "candidates": [asdict(row) for row in rank_available_candidates()[:8]],
        "env": {
            "ARKA_ARBITRAGE_ENABLED": env("ARKA_ARBITRAGE_ENABLED"),
            "ARKA_ARBITRAGE_INTERVAL": env("ARKA_ARBITRAGE_INTERVAL", "60"),
            "ARKA_ARBITRAGE_MIN_SAVINGS": env("ARKA_ARBITRAGE_MIN_SAVINGS", "0.15"),
            "ARKA_ARBITRAGE_DRAIN": env("ARKA_ARBITRAGE_DRAIN"),
        },
    }


def _pid_alive(pid: int) -> bool:
    try:
        os.kill(pid, 0)
        return True
    except OSError:
        return False


def _monitor_loop(interval: float) -> None:
    while not _MONITOR_STOP.wait(interval):
        try:
            run_once(dry_run=False)
        except Exception as exc:
            print(f"[arka-arbitrage] monitor error: {exc}", file=sys.stderr, flush=True)


def start_monitor(*, interval: float | None = None, foreground: bool = False) -> dict[str, Any]:
    interval = interval if interval is not None else _interval_seconds()

    if PID_PATH.is_file():
        try:
            existing = int(PID_PATH.read_text(encoding="utf-8").strip())
            if _pid_alive(existing):
                return {"ok": True, "already_running": True, "pid": existing, "interval_seconds": interval}
        except ValueError:
            pass

    set_env_vars({"ARKA_ARBITRAGE_ENABLED": "1"})

    if foreground:
        _MONITOR_STOP.clear()
        CACHE.mkdir(parents=True, exist_ok=True)
        PID_PATH.write_text(str(os.getpid()), encoding="utf-8")

        def _stop(_signum, _frame) -> None:
            _MONITOR_STOP.set()
            PID_PATH.unlink(missing_ok=True)
            sys.exit(0)

        signal.signal(signal.SIGTERM, _stop)
        signal.signal(signal.SIGINT, _stop)
        try:
            _monitor_loop(interval)
        finally:
            PID_PATH.unlink(missing_ok=True)
        return {"ok": True, "foreground": True, "interval_seconds": interval}

    proc = subprocess.Popen(
        [
            sys.executable,
            "-m",
            "arka.llm.arbitrage",
            "start",
            "--foreground",
            "--interval",
            str(interval),
        ],
        stdout=subprocess.DEVNULL,
        stderr=subprocess.DEVNULL,
        start_new_session=True,
    )
    time.sleep(0.2)
    pid = _read_pid_from_file()
    return {
        "ok": True,
        "started": True,
        "pid": pid or proc.pid,
        "interval_seconds": interval,
    }


def _read_pid_from_file() -> int | None:
    if not PID_PATH.is_file():
        return None
    try:
        return int(PID_PATH.read_text(encoding="utf-8").strip())
    except ValueError:
        return None


def stop_monitor() -> dict[str, Any]:
    _MONITOR_STOP.set()
    stopped: list[int] = []
    if PID_PATH.is_file():
        try:
            pid = int(PID_PATH.read_text(encoding="utf-8").strip())
            if _pid_alive(pid):
                os.kill(pid, signal.SIGTERM)
                stopped.append(pid)
        except (ValueError, OSError):
            pass
        PID_PATH.unlink(missing_ok=True)
    set_env_vars({"ARKA_ARBITRAGE_ENABLED": "0"})
    return {"ok": True, "stopped_pids": stopped}


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="arka llm arbitrage",
        description=(
            "Monitor LLM provider pricing/availability and hot-swap to cheaper "
            "providers without dropping in-flight requests."
        ),
    )
    sub = parser.add_subparsers(dest="cmd")

    sub.add_parser("status", help="Show arbitrage status, candidates, and drain state")
    once = sub.add_parser("once", help="Evaluate and apply one arbitrage swap")
    once.add_argument("--dry-run", action="store_true", help="Evaluate only; do not write .env")
    start = sub.add_parser("start", help="Start background cost monitor")
    start.add_argument("--interval", type=float, default=None, help="Poll interval seconds")
    start.add_argument("--foreground", action="store_true", help="Run monitor in foreground")
    sub.add_parser("stop", help="Stop background cost monitor")

    args = parser.parse_args(argv or ["status"])
    cmd = args.cmd or "status"

    if cmd == "status":
        print(json.dumps(status_payload(), indent=2))
        return 0
    if cmd == "once":
        print(json.dumps(run_once(dry_run=bool(args.dry_run)), indent=2))
        return 0
    if cmd == "start":
        print(json.dumps(start_monitor(interval=args.interval, foreground=bool(args.foreground)), indent=2))
        return 0
    if cmd == "stop":
        print(json.dumps(stop_monitor(), indent=2))
        return 0
    parser.print_help()
    return 1


if __name__ == "__main__":
    raise SystemExit(main())
