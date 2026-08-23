"""Local LLM token ledger and savings estimates — no prompts stored."""

from __future__ import annotations

import json
import os
import time
from collections import Counter, defaultdict
from datetime import date, datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Literal

from arka.paths import cache_dir

Period = Literal["today", "week", "month", "all"]

# Baseline for savings: what the same tokens would cost on a premium cloud model.
_BASELINE_INPUT_PER_M = float(os.environ.get("ARKA_SAVINGS_BASELINE_INPUT_USD", "2.50"))
_BASELINE_OUTPUT_PER_M = float(os.environ.get("ARKA_SAVINGS_BASELINE_OUTPUT_USD", "10.00"))
_BASELINE_LABEL = os.environ.get("ARKA_SAVINGS_BASELINE_LABEL", "GPT-4o-class")


def _path() -> Path:
    return cache_dir() / "llm-usage.json"


def enabled() -> bool:
    return os.environ.get("ARKA_LLM_USAGE_TRACKING", "1").lower() not in {"0", "false", "off", "no"}


def baseline_label() -> str:
    return _BASELINE_LABEL


def baseline_cost_usd(*, input_tokens: int, output_tokens: int) -> float:
    return round(
        (max(0, input_tokens) * _BASELINE_INPUT_PER_M + max(0, output_tokens) * _BASELINE_OUTPUT_PER_M)
        / 1_000_000,
        6,
    )


def _load() -> dict[str, Any]:
    path = _path()
    if not path.is_file():
        return {"events": [], "offline": []}
    try:
        data = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"events": [], "offline": []}
    if not isinstance(data, dict):
        return {"events": [], "offline": []}
    data.setdefault("events", [])
    data.setdefault("offline", [])
    return data


def _save(data: dict[str, Any]) -> None:
    path = _path()
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2), encoding="utf-8")


def _day_key(ts: int | None = None) -> str:
    when = datetime.fromtimestamp(ts or time.time(), tz=timezone.utc)
    return when.date().isoformat()


def record_completion(
    *,
    provider: str,
    model_id: str,
    input_tokens: int,
    output_tokens: int,
    cost_usd: float | None = None,
    task: str = "",
    skill: str = "",
) -> None:
    """Append one LLM completion to the local ledger."""
    if not enabled():
        return
    inp = max(0, int(input_tokens or 0))
    out = max(0, int(output_tokens or 0))
    total = inp + out
    if total <= 0:
        return

    if cost_usd is None:
        try:
            from arka.telemetry.llm_obs import estimate_cost_usd

            actual = estimate_cost_usd(model_id=model_id, input_tokens=inp, output_tokens=out)
        except ImportError:
            actual = 0.0
    else:
        actual = max(0.0, float(cost_usd))

    baseline = baseline_cost_usd(input_tokens=inp, output_tokens=out)
    savings = round(max(0.0, baseline - actual), 6)

    event = {
        "ts": int(time.time()),
        "day": _day_key(),
        "kind": "llm",
        "provider": (provider or "").strip()[:40],
        "model": (model_id or "").strip()[:120],
        "task": (task or "").strip()[:40],
        "skill": (skill or "").strip()[:80],
        "input_tokens": inp,
        "output_tokens": out,
        "total_tokens": total,
        "cost_usd": round(actual, 6),
        "baseline_usd": baseline,
        "saved_usd": savings,
    }

    data = _load()
    events = data.setdefault("events", [])
    events.append(event)
    data["events"] = events[-5000:]
    try:
        _save(data)
    except OSError:
        return


def record_offline_route(*, skill: str, avoided_input: int = 600, avoided_output: int = 250) -> None:
    """Record a symbolic/offline route that avoided an LLM call."""
    if not enabled():
        return
    head = (skill or "").split(maxsplit=1)[0].lower().replace("-", "_")
    if not head or head in {"web_answer", "deep_web_answer", "ask", "chat"}:
        return

    baseline = baseline_cost_usd(input_tokens=avoided_input, output_tokens=avoided_output)
    event = {
        "ts": int(time.time()),
        "day": _day_key(),
        "kind": "offline",
        "skill": head[:80],
        "avoided_input_tokens": avoided_input,
        "avoided_output_tokens": avoided_output,
        "saved_usd": baseline,
    }

    data = _load()
    offline = data.setdefault("offline", [])
    offline.append(event)
    data["offline"] = offline[-2000:]
    try:
        _save(data)
    except OSError:
        return


def reset() -> None:
    path = _path()
    if path.is_file():
        path.unlink(missing_ok=True)


def _period_bounds(period: Period) -> tuple[int | None, str]:
    today = date.today()
    if period == "today":
        start = datetime.combine(today, datetime.min.time(), tzinfo=timezone.utc)
        return int(start.timestamp()), "Today"
    if period == "week":
        start_day = today - timedelta(days=6)
        start = datetime.combine(start_day, datetime.min.time(), tzinfo=timezone.utc)
        return int(start.timestamp()), "Last 7 days"
    if period == "month":
        start_day = today - timedelta(days=29)
        start = datetime.combine(start_day, datetime.min.time(), tzinfo=timezone.utc)
        return int(start.timestamp()), "Last 30 days"
    return None, "All time"


def report(*, period: Period = "all") -> dict[str, Any]:
    data = _load()
    since_ts, label = _period_bounds(period)

    events = [e for e in data.get("events", []) if isinstance(e, dict)]
    offline = [e for e in data.get("offline", []) if isinstance(e, dict)]
    if since_ts is not None:
        events = [e for e in events if int(e.get("ts") or 0) >= since_ts]
        offline = [e for e in offline if int(e.get("ts") or 0) >= since_ts]

    input_tokens = sum(int(e.get("input_tokens") or 0) for e in events)
    output_tokens = sum(int(e.get("output_tokens") or 0) for e in events)
    total_tokens = input_tokens + output_tokens
    actual_cost = round(sum(float(e.get("cost_usd") or 0) for e in events), 6)
    baseline_cost = round(sum(float(e.get("baseline_usd") or 0) for e in events), 6)
    model_savings = round(sum(float(e.get("saved_usd") or 0) for e in events), 6)
    offline_savings = round(sum(float(e.get("saved_usd") or 0) for e in offline), 6)
    total_savings = round(model_savings + offline_savings, 6)

    by_provider: Counter[str] = Counter()
    by_model: Counter[str] = Counter()
    by_day: dict[str, dict[str, float | int]] = defaultdict(
        lambda: {"tokens": 0, "cost_usd": 0.0, "saved_usd": 0.0, "requests": 0}
    )
    for e in events:
        prov = str(e.get("provider") or "unknown")
        model = str(e.get("model") or "unknown")
        by_provider[prov] += int(e.get("total_tokens") or 0)
        by_model[f"{prov}/{model}"] += int(e.get("total_tokens") or 0)
        day = str(e.get("day") or "")
        if day:
            by_day[day]["tokens"] += int(e.get("total_tokens") or 0)
            by_day[day]["cost_usd"] = float(by_day[day]["cost_usd"]) + float(e.get("cost_usd") or 0)
            by_day[day]["saved_usd"] = float(by_day[day]["saved_usd"]) + float(e.get("saved_usd") or 0)
            by_day[day]["requests"] += 1

    for e in offline:
        day = str(e.get("day") or "")
        if day:
            by_day[day]["saved_usd"] = float(by_day[day]["saved_usd"]) + float(e.get("saved_usd") or 0)

    return {
        "enabled": enabled(),
        "path": str(_path()),
        "period": period,
        "period_label": label,
        "baseline_label": baseline_label(),
        "requests": len(events),
        "offline_routes": len(offline),
        "input_tokens": input_tokens,
        "output_tokens": output_tokens,
        "total_tokens": total_tokens,
        "actual_cost_usd": actual_cost,
        "baseline_cost_usd": baseline_cost,
        "model_savings_usd": model_savings,
        "offline_savings_usd": offline_savings,
        "total_savings_usd": total_savings,
        "by_provider": by_provider.most_common(8),
        "by_model": by_model.most_common(8),
        "by_day": dict(sorted(by_day.items())[-14:]),
    }


def _money(amount: float) -> str:
    if amount >= 1:
        return f"${amount:.2f}"
    if amount >= 0.01:
        return f"${amount:.4f}"
    if amount > 0:
        return f"${amount:.6f}"
    return "$0.00"


def format_report_lines(payload: dict[str, Any] | None = None, *, period: Period = "all") -> list[str]:
    row = payload if payload is not None else report(period=period)
    lines = [
        f"{row['period_label']}: {row['total_tokens']:,} tokens "
        f"({row['input_tokens']:,} in · {row['output_tokens']:,} out)",
        f"  LLM calls: {row['requests']} · offline routes: {row['offline_routes']}",
        f"  You spent: {_money(float(row['actual_cost_usd']))}",
        f"  vs {row['baseline_label']} baseline: {_money(float(row['baseline_cost_usd']))}",
        f"  Estimated savings: {_money(float(row['total_savings_usd']))} "
        f"(cheaper models {_money(float(row['model_savings_usd']))} "
        f"+ offline routing {_money(float(row['offline_savings_usd']))})",
    ]
    if row.get("by_provider"):
        top = ", ".join(f"{name} {tokens:,}" for name, tokens in row["by_provider"][:4])
        lines.append(f"  Top providers: {top}")
    if row.get("by_model"):
        top = ", ".join(f"{name} {tokens:,}" for name, tokens in row["by_model"][:3])
        lines.append(f"  Top models: {top}")
    if not row["requests"] and not row["offline_routes"]:
        lines.append("  (no usage recorded yet — run arka ask or any LLM skill)")
    return lines


def format_report_text(*, period: Period = "all") -> str:
    payload = report(period=period)
    lines = [f"Arka token usage — {payload['period_label']}", "=" * 40, ""]
    lines.extend(format_report_lines(payload))
    lines.extend(
        [
            "",
            f"Tracking: {'on' if payload['enabled'] else 'off'} · {payload['path']}",
            f"Baseline: {payload['baseline_label']} "
            f"(${_BASELINE_INPUT_PER_M}/M in · ${_BASELINE_OUTPUT_PER_M}/M out)",
        ]
    )
    return "\n".join(lines)
