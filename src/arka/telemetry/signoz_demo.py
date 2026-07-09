"""SigNoz hackathon demo scenarios — inference latency, RAG cascade, router split."""

from __future__ import annotations

import argparse
import os
import sys
import time
from contextlib import contextmanager
from typing import Iterator

_DEMO_PROMPT = (
    "In one sentence, explain why observability matters for AI agents. "
    "Keep the answer under 40 words."
)
_RAG_GOAL = "What did we decide about the SigNoz hackathon demo?"


def _require_tracing() -> bool:
    try:
        from arka.telemetry import spans_enabled
    except ImportError:
        print("Install observability extras: pip install 'arka-agent[observability]'", file=sys.stderr)
        return False
    if not spans_enabled():
        print("Enable tracing first:", file=sys.stderr)
        print("  OTEL_TRACES_ENABLED=1 SIGNOZ_ENDPOINT=http://localhost:4318", file=sys.stderr)
        return False
    return True


def _ui_url() -> str:
    return os.environ.get("SIGNOZ_UI_URL", "http://localhost:8080").rstrip("/")


def _flush() -> None:
    try:
        from arka.telemetry.tracing import shutdown_tracing

        shutdown_tracing()
    except ImportError:
        pass


@contextmanager
def _demo_request(name: str, *, scenario: str) -> Iterator[None]:
    from arka.telemetry import span

    with span(
        "arka.request",
        attributes={
            "arka.command": f"signoz demo-{name}",
            "arka.track": "01",
            "arka.demo.scenario": scenario,
        },
    ):
        yield


def _llm_with_chain(
    provider: str,
    model: str,
    *,
    system: str,
    user: str,
    task: str = "demo",
) -> str:
    """Run one LLM completion with a forced single-provider fallback chain."""
    prev = os.environ.get("LLM_FALLBACK")
    os.environ["LLM_FALLBACK"] = f"{provider}:{model}"
    try:
        from arka.llm.cli import llm_complete

        return llm_complete(system, user, temperature=0.2, task=task, skip_security=True)
    finally:
        if prev is None:
            os.environ.pop("LLM_FALLBACK", None)
        else:
            os.environ["LLM_FALLBACK"] = prev


def _synthetic_attempt(
    *,
    provider: str,
    model: str,
    backend: str | None,
    duration_ms: float,
    ttft_ms: float,
    note: str,
) -> None:
    from arka.telemetry import llm_http_span_attributes, mark_ok, span

    attrs = {
        "gen_ai.provider.name": provider,
        "gen_ai.request.model": model,
        "arka.task": "demo",
        "arka.llm.attempt_index": 1,
        "arka.llm.duration_ms": duration_ms,
        "arka.llm.ttft_ms": ttft_ms,
        "arka.llm.streaming": False,
        "arka.demo.synthetic": True,
        "arka.demo.note": note,
        **llm_http_span_attributes(provider),
        "http.status_code": 200,
        "http.response.status_code": 200,
    }
    if backend:
        attrs["arka.inference.backend"] = backend
    with span("arka.llm.attempt", attributes=attrs) as current:
        mark_ok(current)


def demo_inference_latency(*, synthetic: bool = False) -> int:
    """Scenario 1 — compare self-hosted vLLM vs cloud API latency on the same prompt."""
    if not _require_tracing():
        return 1

    from arka.telemetry import mark_ok, span

    vllm_model = os.environ.get("VLLM_CLOUD_MODEL") or os.environ.get("VLLM_MODEL", "default")
    cloud_provider = os.environ.get("ARKA_DEMO_CLOUD_PROVIDER", "gemini")
    cloud_model = os.environ.get("ARKA_DEMO_CLOUD_MODEL", "gemini-2.0-flash")

    with _demo_request("inference", scenario="vllm-vs-cloud-latency"):
        with span(
            "arka.demo.inference_compare",
            attributes={"arka.demo.scenario": "vllm-vs-cloud-latency"},
        ):
            system = "You are a concise assistant."
            user = _DEMO_PROMPT

            # Self-hosted / vLLM path (local or vllm-cloud remote GPU)
            with span(
                "arka.llm.complete",
                attributes={
                    "arka.task": "demo",
                    "arka.demo.backend": "vllm-cloud",
                    "gen_ai.provider.name": "vllm-cloud",
                },
            ):
                if synthetic:
                    _synthetic_attempt(
                        provider="vllm-cloud",
                        model=vllm_model,
                        backend="vllm-cloud",
                        duration_ms=4200,
                        ttft_ms=1800,
                        note="synthetic — set VLLM_CLOUD_URL for live traces",
                    )
                else:
                    text = _llm_with_chain("vllm-cloud", vllm_model, system=system, user=user)
                    if text.startswith("[LLM error:"):
                        _synthetic_attempt(
                            provider="vllm-cloud",
                            model=vllm_model,
                            backend="vllm-cloud",
                            duration_ms=4200,
                            ttft_ms=1800,
                            note=f"vllm-cloud unavailable: {text[:120]}",
                        )
                    else:
                        print(f"vllm-cloud ok ({len(text)} chars)", file=sys.stderr)

            # External cloud API (network + provider queue)
            with span(
                "arka.llm.complete",
                attributes={
                    "arka.task": "demo",
                    "arka.demo.backend": "cloud-api",
                    "gen_ai.provider.name": cloud_provider,
                },
            ):
                if synthetic:
                    _synthetic_attempt(
                        provider=cloud_provider,
                        model=cloud_model,
                        backend=None,
                        duration_ms=890,
                        ttft_ms=310,
                        note="synthetic — run without --synthetic for live cloud API",
                    )
                else:
                    text = _llm_with_chain(cloud_provider, cloud_model, system=system, user=user)
                    if text.startswith("[LLM error:"):
                        print(f"cloud API failed: {text[:200]}", file=sys.stderr)
                        return 1
                    print(f"{cloud_provider} ok ({len(text)} chars)", file=sys.stderr)

    _flush()
    print(
        f"Inference demo sent. Open {_ui_url()}/traces — filter "
        f"arka.demo.scenario = vllm-vs-cloud-latency"
    )
    print("Compare arka.llm.ttft_ms and arka.llm.duration_ms on vllm-cloud vs cloud provider spans.")
    return 0


def demo_rag_cascade(*, synthetic: bool = False) -> int:
    """Scenario 2 — Supermemory / vector fetch then LLM context processing in one trace."""
    if not _require_tracing():
        return 1

    from arka.telemetry import mark_ok, span

    with _demo_request("rag", scenario="rag-supermemory-cascade"):
        with span("arka.rag.cascade", attributes={"arka.demo.scenario": "rag-supermemory-cascade"}):
            ctx = ""
            if synthetic:
                with span(
                    "arka.supermemory.context",
                    attributes={
                        "arka.supermemory.backend": "supermemory",
                        "arka.supermemory.hits": 3,
                        "arka.supermemory.mode": "auto",
                    },
                ):
                    with span(
                        "arka.supermemory.vector_lookup",
                        attributes={
                            "arka.supermemory.backend": "turboquant",
                            "arka.supermemory.operation": "vector_search",
                            "arka.supermemory.hits": 3,
                            "arka.supermemory.lookup_ms": 42.5,
                        },
                    ):
                        pass
                    ctx = (
                        "Relevant memories (semantic):\n"
                        "- SigNoz demo uses Foundry casting.yaml\n"
                        "- Judges filter service.name = arka\n"
                        "- Three scenarios: inference, RAG, router"
                    )
            else:
                try:
                    from arka.integrations.supermemory import context_for, remember

                    remember(
                        "SigNoz hackathon demo uses Foundry casting.yaml and OTLP :4318",
                        tags=["hackathon", "signoz"],
                    )
                    remember(
                        "Judges should filter service.name = arka in SigNoz Traces",
                        tags=["hackathon"],
                    )
                    ctx = context_for(_RAG_GOAL)
                except Exception as exc:
                    print(f"memory fetch failed ({exc}); using local synthetic context", file=sys.stderr)
                    synthetic = True
                    ctx = (
                        "Relevant memories (local):\n"
                        "- SigNoz demo uses Foundry casting.yaml\n"
                        "- Judges filter service.name = arka"
                    )

            lookup_ms = 0.0
            if not synthetic:
                # Best-effort: child vector_lookup span duration is on the span itself
                lookup_ms = 0.0

            with span(
                "arka.llm.context_process",
                attributes={
                    "arka.llm.context_chars": len(ctx),
                    "arka.supermemory.lookup_ms": lookup_ms,
                    "arka.demo.scenario": "rag-supermemory-cascade",
                },
            ) as proc_span:
                system = (
                    "Answer using only the provided memory context. "
                    "If context is empty, say you have no memories."
                )
                user = f"Memory context:\n{ctx or '(none)'}\n\nQuestion: {_RAG_GOAL}"
                if synthetic:
                    with span(
                        "arka.llm.complete",
                        attributes={"arka.task": "demo", "arka.llm.prompt_chars": len(user)},
                    ):
                        _synthetic_attempt(
                            provider=os.environ.get("ARKA_DEMO_CLOUD_PROVIDER", "gemini"),
                            model=os.environ.get("ARKA_DEMO_CLOUD_MODEL", "gemini-2.0-flash"),
                            backend=None,
                            duration_ms=650,
                            ttft_ms=220,
                            note="synthetic LLM after vector lookup",
                        )
                else:
                    from arka.llm.cli import llm_complete

                    answer = llm_complete(system, user, temperature=0.1, task="demo", skip_security=True)
                    if answer.startswith("[LLM error:"):
                        print(answer[:200], file=sys.stderr)
                        return 1
                    proc_span.set_attribute("arka.llm.completion_chars", len(answer))
                    print(answer[:300], file=sys.stderr)
                mark_ok(proc_span)

    _flush()
    print(
        f"RAG cascade demo sent. Open {_ui_url()}/traces — filter "
        f"arka.demo.scenario = rag-supermemory-cascade"
    )
    print("Waterfall: arka.rag.cascade → vector_lookup → arka.llm.context_process → arka.llm.complete")
    return 0


def demo_router_split(*, synthetic: bool = False) -> int:
    """Scenario 3 — symbolic instant route vs semantic LLM route."""
    if not _require_tracing():
        return 1

    from arka.telemetry import span

    symbolic_cmd = os.environ.get("ARKA_DEMO_SYMBOLIC_CMD", "generate password")
    semantic_cmd = os.environ.get(
        "ARKA_DEMO_SEMANTIC_CMD",
        "what shell command shows disk usage on macOS in human-readable form",
    )
    prev_mode = os.environ.get("ROUTE_MODE")

    with _demo_request("router", scenario="semantic-router-split"):
        with span(
            "arka.demo.router_compare",
            attributes={"arka.demo.scenario": "semantic-router-split"},
        ):
            # Fast symbolic path — no LLM
            from arka.router import route as nl_route

            os.environ["ROUTE_MODE"] = "symbolic_only"
            try:
                sym = nl_route(symbolic_cmd)
                print(f"symbolic → {sym.skill if sym else '(none)'}", file=sys.stderr)
            finally:
                if prev_mode is None:
                    os.environ.pop("ROUTE_MODE", None)
                else:
                    os.environ["ROUTE_MODE"] = prev_mode

            # Semantic path — needs LLM classifier
            with span(
                "arka.route",
                attributes={
                    "arka.route.input": semantic_cmd[:500],
                    "arka.route.mode": "ai_only",
                    "arka.demo.scenario": "semantic-router-split",
                },
            ) as route_span:
                route_start = time.perf_counter()
                if synthetic:
                    with span(
                        "arka.route.llm",
                        attributes={
                            "arka.task": "route",
                            "arka.route.input_chars": len(semantic_cmd),
                            "arka.route.result": "df -h",
                            "arka.route.latency_ms": 840,
                        },
                    ):
                        pass
                    route_span.set_attribute("arka.route.decision", "llm")
                    route_span.set_attribute("arka.route.source", "llm")
                    route_span.set_attribute("arka.route.skill", "df -h")
                    route_span.set_attribute("arka.route.latency_ms", 850)
                else:
                    os.environ["ROUTE_MODE"] = "ai_only"
                    try:
                        from arka.llm.cli import llm_route

                        result = llm_route(semantic_cmd, "", "")
                        route_span.set_attribute("arka.route.decision", "llm")
                        route_span.set_attribute("arka.route.source", "llm")
                        route_span.set_attribute("arka.route.result", result[:500])
                        route_span.set_attribute("arka.route.skill", result[:500])
                        from arka.telemetry.tracing import duration_ms

                        route_span.set_attribute("arka.route.latency_ms", duration_ms(route_start))
                        print(f"semantic → {result}", file=sys.stderr)
                    finally:
                        if prev_mode is None:
                            os.environ.pop("ROUTE_MODE", None)
                        else:
                            os.environ["ROUTE_MODE"] = prev_mode

    _flush()
    print(
        f"Router demo sent. Open {_ui_url()}/traces — filter "
        f"arka.demo.scenario = semantic-router-split"
    )
    print("Compare arka.route.latency_ms: symbolic (~1ms) vs llm child span (~seconds).")
    return 0


def demo_e2e_observability(*, synthetic: bool = True) -> int:
    """Scenario 4 — E2E trace + correlated logs + token analytics (four SigNoz pillars)."""
    if not _require_tracing():
        return 1

    from arka.telemetry import mark_ok, span
    from arka.telemetry.llm_obs import synthetic_usage_attrs
    from arka.telemetry.logs import emit_log
    from arka.telemetry.metrics import record_llm_tokens, record_request

    scenario = "e2e-observability-pillars"

    with _demo_request("e2e", scenario=scenario):
        record_request(command="signoz demo-e2e")
        with span(
            "arka.agent.goal",
            attributes={
                "arka.agent.goal_text": "demo four SigNoz observability pillars",
                "arka.agent.max_steps": 2,
                "arka.demo.scenario": scenario,
            },
        ):
            with span(
                "arka.agent.goal.step",
                attributes={"arka.agent.step": 1, "arka.agent.status": "continue"},
            ):
                with span("arka.route", attributes={"arka.route.decision": "symbolic", "arka.route.latency_ms": 1.2}):
                    pass
                with span(
                    "arka.supermemory.vector_lookup",
                    attributes={"arka.supermemory.lookup_ms": 18.5, "arka.supermemory.hits": 3},
                ):
                    emit_log(
                        "vector lookup completed",
                        level="info",
                        attributes={"arka.supermemory.hits": 3, "arka.event": "memory.recall"},
                    )
                with span(
                    "arka.llm.complete",
                    attributes={"arka.task": "agent", "gen_ai.provider.name": "gemini", "gen_ai.request.model": "gemini-2.0-flash"},
                ) as llm_span:
                    usage = synthetic_usage_attrs(
                        input_tokens=1240,
                        output_tokens=186,
                        model_id="gemini-2.0-flash",
                        ttft_ms=420.0,
                        duration_ms=1850.0,
                    )
                    for key, value in usage.items():
                        llm_span.set_attribute(key, value)
                    with span(
                        "arka.llm.attempt",
                        attributes={
                            **usage,
                            "gen_ai.provider.name": "gemini",
                            "gen_ai.request.model": "gemini-2.0-flash",
                            "arka.llm.attempt_index": 1,
                        },
                    ) as attempt_span:
                        mark_ok(attempt_span)
                        emit_log(
                            "llm tokens gemini/gemini-2.0-flash",
                            level="info",
                            attributes={
                                **{k: v for k, v in usage.items() if k.startswith("gen_ai.") or k.startswith("arka.llm.")},
                                "gen_ai.provider.name": "gemini",
                                "gen_ai.request.model": "gemini-2.0-flash",
                                "arka.event": "llm.completion",
                            },
                        )
                        record_llm_tokens(
                            provider="gemini",
                            model="gemini-2.0-flash",
                            input_tokens=1240,
                            output_tokens=186,
                            task="agent",
                            cost_usd=float(usage.get("arka.llm.estimated_cost_usd", 0)),
                        )
                    mark_ok(llm_span)
                with span(
                    "arka.tool.shell",
                    attributes={"arka.tool.command": "df -h /", "arka.tool.exit_code": 0, "arka.tool.kind": "subprocess"},
                ):
                    emit_log(
                        "shell ok df -h /",
                        level="info",
                        attributes={"arka.tool.command": "df -h /", "arka.event": "tool.shell"},
                    )

    _flush()
    ui = _ui_url()
    print(f"E2E demo sent. Open {ui}/traces — filter arka.demo.scenario = {scenario}")
    print("1. Waterfall: route → vector_lookup → llm.attempt → tool.shell (E2E tracing)")
    print(f"2. Click a slow LLM span → Logs tab shows correlated gen_ai.usage.* entries")
    print(f"3. Metrics: arka.llm.tokens + arka.agent.requests in {ui}/metrics")
    print("4. Alerts: arka signoz alert-create llm-p99-latency")
    return 0


def demo_exception_stacks(*, synthetic: bool = True) -> int:
    """Demo automatic exception recording with stack traces in SigNoz."""
    if not _require_tracing():
        return 1

    from arka.telemetry import record_exception, span

    scenario = "exception-stack-traces"

    with _demo_request("exceptions", scenario=scenario):
        with span("arka.demo.exception_compare", attributes={"arka.demo.scenario": scenario}):
            with span(
                "arka.llm.attempt",
                attributes={
                    "gen_ai.provider.name": "gemini",
                    "gen_ai.request.model": "gemini-2.0-flash",
                    "arka.llm.attempt_index": 1,
                },
            ) as attempt_span:
                try:
                    raise RuntimeError("429 rate limit exceeded — failover to next provider")
                except RuntimeError as exc:
                    record_exception(attempt_span, exc)
            with span(
                "arka.tool.shell",
                attributes={"arka.tool.command": "missing-cmd", "arka.tool.kind": "subprocess"},
            ):
                try:
                    raise FileNotFoundError("missing-cmd: command not found in PATH")
                except FileNotFoundError as exc:
                    from opentelemetry import trace

                    record_exception(trace.get_current_span(), exc)

    _flush()
    ui = _ui_url()
    print(f"Exception demo sent. Open {ui}/traces — filter arka.demo.scenario = {scenario}")
    print("Click error spans → Events tab shows exception stack traces (exception.stacktrace).")
    print("Logs tab shows correlated error entries with the same trace ID.")
    return 0


def demo_all(*, synthetic: bool = False) -> int:
    codes = [
        demo_inference_latency(synthetic=synthetic),
        demo_rag_cascade(synthetic=synthetic),
        demo_router_split(synthetic=synthetic),
        demo_e2e_observability(synthetic=True),
        demo_exception_stacks(synthetic=True),
    ]
    return max(codes)


def _synthetic_flag(args: argparse.Namespace) -> bool:
    return bool(getattr(args, "synthetic", False))


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="SigNoz hackathon demo scenarios for Arka")
    parser.add_argument(
        "--synthetic",
        action="store_true",
        help="Emit structured demo spans without calling live LLM/vLLM APIs",
    )
    sub = parser.add_subparsers(dest="cmd", required=True)

    for name, help_text, fn in (
        ("inference", "vLLM vs cloud latency comparison", demo_inference_latency),
        ("rag", "Supermemory / vector lookup + LLM cascade", demo_rag_cascade),
        ("router", "Symbolic vs semantic router split", demo_router_split),
        ("e2e", "E2E trace + logs + tokens (four SigNoz pillars)", demo_e2e_observability),
        ("exceptions", "Automatic exception recording with stack traces", demo_exception_stacks),
        ("all", "Run all demo scenarios", demo_all),
    ):
        p = sub.add_parser(name, help=help_text)
        p.add_argument("--synthetic", action="store_true")
        p.set_defaults(func=fn)

    args = parser.parse_args(argv)
    synthetic = _synthetic_flag(args)
    if args.func is demo_all:
        return demo_all(synthetic=synthetic)
    return args.func(synthetic=synthetic)


if __name__ == "__main__":
    raise SystemExit(main())
