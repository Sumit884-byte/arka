"""LLM token usage, cost, and log-trace correlation helpers for SigNoz."""

from __future__ import annotations

from typing import Any

# Rough USD per 1M tokens for demo cost estimates when provider omits cost.
_COST_PER_MILLION: dict[str, tuple[float, float]] = {
    "gemini-2.0-flash": (0.10, 0.40),
    "gemini-2.5-flash": (0.15, 0.60),
    "llama-3.3-70b-versatile": (0.59, 0.79),
    "llama-3.1-8b-instant": (0.05, 0.08),
    "default": (0.50, 1.50),
}


def _safe_int(value: Any) -> int:
    try:
        return max(0, int(value or 0))
    except (TypeError, ValueError):
        return 0


def _safe_float(value: Any) -> float | None:
    try:
        if value is None:
            return None
        return float(value)
    except (TypeError, ValueError):
        return None


def estimate_cost_usd(*, model_id: str, input_tokens: int, output_tokens: int) -> float:
    model = (model_id or "").lower()
    for key, (in_rate, out_rate) in _COST_PER_MILLION.items():
        if key == "default":
            continue
        if key in model:
            return round((input_tokens * in_rate + output_tokens * out_rate) / 1_000_000, 6)
    in_rate, out_rate = _COST_PER_MILLION["default"]
    return round((input_tokens * in_rate + output_tokens * out_rate) / 1_000_000, 6)


def usage_attrs_from_run(run: Any, *, model_id: str = "") -> dict[str, Any]:
    """Extract OpenTelemetry GenAI usage attributes from an Agno run object."""
    metrics = getattr(run, "metrics", None)
    if metrics is None:
        return {}

    input_tokens = _safe_int(getattr(metrics, "input_tokens", 0))
    output_tokens = _safe_int(getattr(metrics, "output_tokens", 0))
    total_tokens = _safe_int(getattr(metrics, "total_tokens", 0)) or (input_tokens + output_tokens)
    if total_tokens <= 0:
        return {}

    attrs: dict[str, Any] = {
        "gen_ai.usage.input_tokens": input_tokens,
        "gen_ai.usage.output_tokens": output_tokens,
        "gen_ai.usage.total_tokens": total_tokens,
        "arka.llm.prompt_tokens": input_tokens,
        "arka.llm.completion_tokens": output_tokens,
    }

    cost = _safe_float(getattr(metrics, "cost", None))
    if cost is not None and cost >= 0:
        attrs["arka.llm.cost_usd"] = round(cost, 6)
    else:
        attrs["arka.llm.estimated_cost_usd"] = estimate_cost_usd(
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        )

    ttft = _safe_float(getattr(metrics, "time_to_first_token", None))
    if ttft is not None and ttft >= 0:
        attrs["arka.llm.ttft_ms"] = round(ttft * 1000.0, 2)

    duration = _safe_float(getattr(metrics, "duration", None))
    if duration is not None and duration >= 0:
        attrs["arka.llm.duration_ms"] = round(duration * 1000.0, 2)

    cache_read = _safe_int(getattr(metrics, "cache_read_tokens", 0))
    if cache_read:
        attrs["arka.llm.cache_read_tokens"] = cache_read

    return attrs


def apply_run_telemetry(
    span_obj: Any,
    run: Any,
    *,
    provider: str,
    model_id: str,
    task: str = "",
    label: str = "",
) -> dict[str, Any]:
    """Attach token/cost/timing attrs to span, record metrics, emit correlated log."""
    attrs = usage_attrs_from_run(run, model_id=model_id)
    if not attrs:
        return {}

    try:
        from arka.telemetry.tracing import set_span_attributes

        set_span_attributes(span_obj, attrs)
    except ImportError:
        pass

    try:
        from arka.telemetry.metrics import record_llm_attempt, record_llm_tokens

        record_llm_attempt(
            provider=provider,
            model=model_id,
            success=True,
            backend=provider,
        )
        record_llm_tokens(
            provider=provider,
            model=model_id,
            input_tokens=int(attrs.get("gen_ai.usage.input_tokens", 0)),
            output_tokens=int(attrs.get("gen_ai.usage.output_tokens", 0)),
            task=task,
            cost_usd=float(attrs.get("arka.llm.cost_usd", attrs.get("arka.llm.estimated_cost_usd", 0)) or 0),
        )
    except ImportError:
        pass

    try:
        from arka.telemetry.logs import emit_log

        emit_log(
            f"llm tokens {label or f'{provider}/{model_id}'}",
            level="info",
            attributes={
                "gen_ai.provider.name": provider,
                "gen_ai.request.model": model_id,
                "gen_ai.usage.input_tokens": attrs.get("gen_ai.usage.input_tokens", 0),
                "gen_ai.usage.output_tokens": attrs.get("gen_ai.usage.output_tokens", 0),
                "gen_ai.usage.total_tokens": attrs.get("gen_ai.usage.total_tokens", 0),
                "arka.llm.cost_usd": attrs.get("arka.llm.cost_usd", attrs.get("arka.llm.estimated_cost_usd", 0)),
                "arka.task": task or "default",
                "arka.event": "llm.completion",
            },
        )
    except ImportError:
        pass

    return attrs


def synthetic_usage_attrs(
    *,
    input_tokens: int,
    output_tokens: int,
    model_id: str = "gemini-2.0-flash",
    ttft_ms: float | None = None,
    duration_ms: float | None = None,
) -> dict[str, Any]:
    total = input_tokens + output_tokens
    attrs: dict[str, Any] = {
        "gen_ai.usage.input_tokens": input_tokens,
        "gen_ai.usage.output_tokens": output_tokens,
        "gen_ai.usage.total_tokens": total,
        "arka.llm.prompt_tokens": input_tokens,
        "arka.llm.completion_tokens": output_tokens,
        "arka.llm.estimated_cost_usd": estimate_cost_usd(
            model_id=model_id,
            input_tokens=input_tokens,
            output_tokens=output_tokens,
        ),
    }
    if ttft_ms is not None:
        attrs["arka.llm.ttft_ms"] = round(ttft_ms, 2)
    if duration_ms is not None:
        attrs["arka.llm.duration_ms"] = round(duration_ms, 2)
    return attrs
