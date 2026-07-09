"""OpenTelemetry metrics — counters for agent, LLM, and goal activity."""

from __future__ import annotations

import atexit
from typing import Any

from arka.telemetry._otlp import (
    build_resource,
    collector_available,
    otlp_export_timeout_seconds,
    shutdown_timeout_millis,
    signal_enabled,
    signal_endpoint,
    suppress_otel_exporter_logging,
)

_meter: Any | None = None
_initialized = False
_counters: dict[str, Any] = {}
_reader: Any | None = None


def metrics_enabled() -> bool:
    return signal_enabled("metrics")


def _setup() -> None:
    global _meter, _initialized, _counters, _reader
    if _initialized:
        return
    _initialized = True
    if not metrics_enabled():
        return

    endpoint = signal_endpoint("metrics")
    if not collector_available(endpoint):
        return

    suppress_otel_exporter_logging()

    try:
        from opentelemetry import metrics
        from opentelemetry.exporter.otlp.proto.http.metric_exporter import OTLPMetricExporter
        from opentelemetry.sdk.metrics import MeterProvider
        from opentelemetry.sdk.metrics.export import PeriodicExportingMetricReader
    except ImportError:
        return

    timeout = otlp_export_timeout_seconds()
    _reader = PeriodicExportingMetricReader(
        OTLPMetricExporter(endpoint=endpoint, timeout=timeout),
        export_interval_millis=5000,
        export_timeout_millis=int(timeout * 1000),
    )
    provider = MeterProvider(resource=build_resource(), metric_readers=[_reader])
    metrics.set_meter_provider(provider)
    _meter = metrics.get_meter("arka.agent", "0.1.0")
    _counters["requests"] = _meter.create_counter(
        "arka.agent.requests",
        description="Arka CLI / agent requests",
    )
    _counters["llm_attempts"] = _meter.create_counter(
        "arka.llm.attempts",
        description="LLM provider attempts (including failover)",
    )
    _counters["errors"] = _meter.create_counter(
        "arka.agent.errors",
        description="Agent / LLM / tool errors",
    )
    _counters["goal_steps"] = _meter.create_counter(
        "arka.agent.goal.steps",
        description="Autonomous goal-loop steps",
    )
    _counters["supermemory_ops"] = _meter.create_counter(
        "arka.supermemory.ops",
        description="Supermemory remember/recall/context and API calls",
    )
    _counters["inference_ops"] = _meter.create_counter(
        "arka.inference.vllm.ops",
        description="vLLM health checks and cloud inference operations",
    )
    _counters["mcp_ops"] = _meter.create_counter(
        "arka.mcp.ops",
        description="MCP connect, list_tools, and call_tool operations",
    )
    _counters["llm_tokens"] = _meter.create_counter(
        "arka.llm.tokens",
        description="LLM input/output token usage",
    )
    atexit.register(shutdown_metrics)


def record_request(*, command: str = "") -> None:
    _setup()
    counter = _counters.get("requests")
    if counter is None:
        return
    attrs = {"arka.command": command[:200]} if command else {}
    counter.add(1, attrs)


def record_llm_attempt(
    *,
    provider: str,
    model: str = "",
    success: bool = True,
    backend: str = "",
) -> None:
    _setup()
    counter = _counters.get("llm_attempts")
    if counter is None:
        return
    attrs: dict[str, str | bool] = {
        "gen_ai.provider.name": provider or "unknown",
        "gen_ai.request.model": model[:120] if model else "unknown",
        "arka.llm.success": success,
    }
    inferred = backend or (
        "vllm-cloud"
        if (provider or "").lower() == "vllm-cloud"
        else (provider or "").lower()
        if (provider or "").lower() in {"vllm", "ollama", "lmstudio", "litellm"}
        else ""
    )
    if inferred:
        attrs["arka.inference.backend"] = inferred
    counter.add(1, attrs)


def record_inference_op(
    *,
    backend: str,
    operation: str,
    success: bool = True,
) -> None:
    _setup()
    counter = _counters.get("inference_ops")
    if counter is None:
        return
    counter.add(
        1,
        {
            "arka.inference.backend": backend[:40] or "unknown",
            "arka.inference.operation": operation[:120] or "unknown",
            "arka.inference.success": success,
        },
    )


def record_error(*, component: str, message: str = "") -> None:
    _setup()
    counter = _counters.get("errors")
    if counter is None:
        return
    counter.add(
        1,
        {
            "arka.component": component[:120] or "unknown",
            "arka.error": message[:200] if message else "",
        },
    )


def record_goal_step(*, step: int, status: str = "continue") -> None:
    _setup()
    counter = _counters.get("goal_steps")
    if counter is None:
        return
    counter.add(1, {"arka.agent.step": step, "arka.agent.status": status[:40]})


def record_supermemory_op(
    *,
    operation: str,
    backend: str = "api",
    success: bool = True,
    hits: int = 0,
) -> None:
    _setup()
    counter = _counters.get("supermemory_ops")
    if counter is None:
        return
    counter.add(
        1,
        {
            "arka.supermemory.operation": operation[:120] or "unknown",
            "arka.supermemory.backend": backend[:40] or "unknown",
            "arka.supermemory.success": success,
            "arka.supermemory.hits": max(0, hits),
        },
    )


def record_mcp_op(
    *,
    server: str,
    operation: str,
    success: bool = True,
    tool_name: str = "",
) -> None:
    _setup()
    counter = _counters.get("mcp_ops")
    if counter is None:
        return
    attrs: dict[str, str | bool] = {
        "arka.mcp.server": server[:40] or "unknown",
        "arka.mcp.operation": operation[:120] or "unknown",
        "arka.mcp.success": success,
    }
    if tool_name:
        attrs["arka.mcp.tool_name"] = tool_name[:120]
    counter.add(1, attrs)


def record_llm_tokens(
    *,
    provider: str,
    model: str = "",
    input_tokens: int = 0,
    output_tokens: int = 0,
    task: str = "",
    cost_usd: float = 0.0,
) -> None:
    _setup()
    counter = _counters.get("llm_tokens")
    if counter is None:
        return
    base = {
        "gen_ai.provider.name": provider or "unknown",
        "gen_ai.request.model": model[:120] if model else "unknown",
        "arka.task": task[:40] if task else "default",
    }
    if input_tokens:
        counter.add(input_tokens, {**base, "gen_ai.token.type": "input"})
    if output_tokens:
        counter.add(output_tokens, {**base, "gen_ai.token.type": "output"})
    if cost_usd > 0:
        counter.add(int(cost_usd * 1_000_000), {**base, "gen_ai.token.type": "cost_micro_usd"})


def metrics_status() -> dict[str, str]:
    _setup()
    return {
        "metrics_enabled": str(metrics_enabled()).lower(),
        "metrics_configured": str(_meter is not None).lower(),
        "metrics_endpoint": signal_endpoint("metrics") if metrics_enabled() else "",
    }


def shutdown_metrics() -> None:
    global _meter, _reader
    timeout = shutdown_timeout_millis()
    if _reader is not None:
        try:
            if hasattr(_reader, "force_flush"):
                _reader.force_flush(timeout_millis=timeout)
            if hasattr(_reader, "shutdown"):
                _reader.shutdown()
        except Exception:
            pass
        _reader = None
    if _meter is None:
        return
    try:
        from opentelemetry import metrics

        provider = metrics.get_meter_provider()
        if hasattr(provider, "force_flush"):
            provider.force_flush(timeout_millis=timeout)
        if hasattr(provider, "shutdown"):
            provider.shutdown()
    except Exception:
        pass
    _meter = None
