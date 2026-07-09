import os
import pytest


def test_spans_disabled_by_default(monkeypatch):
    monkeypatch.delenv("OTEL_TRACES_ENABLED", raising=False)
    monkeypatch.delenv("SIGNOZ_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_SDK_DISABLED", raising=False)

    from importlib import reload

    import arka.telemetry._otlp as otlp
    import arka.telemetry.tracing as tracing

    reload(otlp)
    reload(tracing)
    from arka.telemetry import spans_enabled, trace_status

    assert spans_enabled() is False
    status = trace_status()
    assert status["enabled"] == "false"


def test_signoz_endpoint_alone_does_not_enable(monkeypatch):
    monkeypatch.delenv("OTEL_TRACES_ENABLED", raising=False)
    monkeypatch.setenv("SIGNOZ_ENDPOINT", "http://localhost:4318")

    from importlib import reload

    import arka.telemetry._otlp as otlp
    import arka.telemetry.tracing as tracing

    reload(otlp)
    reload(tracing)
    from arka.telemetry import spans_enabled

    assert spans_enabled() is False


def test_otel_sdk_disabled_blocks_export(monkeypatch):
    monkeypatch.setenv("OTEL_TRACES_ENABLED", "1")
    monkeypatch.setenv("SIGNOZ_ENDPOINT", "http://localhost:4318")
    monkeypatch.setenv("OTEL_SDK_DISABLED", "true")

    from importlib import reload

    import arka.telemetry._otlp as otlp
    import arka.telemetry.tracing as tracing

    reload(otlp)
    reload(tracing)
    from arka.telemetry import spans_enabled

    assert spans_enabled() is False


def test_unreachable_endpoint_disables_setup(monkeypatch):
    monkeypatch.setenv("OTEL_TRACES_ENABLED", "1")
    monkeypatch.setenv("SIGNOZ_ENDPOINT", "http://localhost:4318")

    from importlib import reload

    import arka.telemetry._otlp as otlp
    import arka.telemetry.tracing as tracing

    reload(otlp)
    reload(tracing)
    otlp.reset_collector_probe_cache()
    monkeypatch.setattr(otlp, "endpoint_reachable", lambda *_a, **_k: False)

    tracing._initialized = False
    tracing._tracer = None
    tracing._enabled = None

    with tracing.span("arka.test.unreachable") as current:
        assert isinstance(current, tracing._NoOpSpan)

    assert tracing._tracer is None


def test_spans_enabled_with_signoz_endpoint(monkeypatch):
    monkeypatch.setenv("OTEL_TRACES_ENABLED", "1")
    monkeypatch.setenv("SIGNOZ_ENDPOINT", "http://localhost:4318")

    from importlib import reload

    import arka.telemetry.tracing as tracing

    reload(tracing)
    from arka.telemetry import spans_enabled

    assert spans_enabled() is True


def test_noop_span_does_not_raise():
    from arka.telemetry.tracing import span

    with span("arka.test", attributes={"demo": True}) as current:
        current.set_attribute("x", 1)
        current.add_event("evt")


def test_parse_http_status_code():
    import urllib.error

    from arka.telemetry.tracing import parse_http_status_code

    assert parse_http_status_code("Error status code: 429") == 429
    assert parse_http_status_code("HTTP Error 401: Unauthorized") == 401
    assert parse_http_status_code(urllib.error.HTTPError("url", 403, "Forbidden", {}, None)) == 403
    assert parse_http_status_code("generic failure") is None


def test_llm_http_span_attributes():
    from arka.telemetry.tracing import llm_http_span_attributes, llm_provider_http_url

    attrs = llm_http_span_attributes("gemini")
    assert attrs["http.method"] == "POST"
    assert "generativelanguage.googleapis.com" in attrs["http.url"]
    assert llm_provider_http_url("openrouter").endswith("/chat/completions")


def test_metrics_logs_enabled_with_traces(monkeypatch):
    monkeypatch.setenv("OTEL_TRACES_ENABLED", "1")
    monkeypatch.setenv("SIGNOZ_ENDPOINT", "http://localhost:4318")

    from importlib import reload

    import arka.telemetry._otlp as otlp
    import arka.telemetry.logs as logs_mod
    import arka.telemetry.metrics as metrics_mod

    reload(otlp)
    reload(metrics_mod)
    reload(logs_mod)

    assert otlp.signal_enabled("metrics") is True
    assert otlp.signal_enabled("logs") is True


def test_duration_ms_and_timing_attrs():
    from arka.telemetry.tracing import _NoOpSpan, duration_ms, set_timing_attrs

    start = 100.0
    assert duration_ms(start, 100.5) == 500.0

    noop = _NoOpSpan()
    set_timing_attrs(noop, start=0.0, end=0.01, streaming=False)
    set_timing_attrs(noop, start=0.0, end=0.02, ttft_ms=5.0, streaming=True)


def test_signoz_demo_synthetic_runs(monkeypatch):
    monkeypatch.setenv("OTEL_TRACES_ENABLED", "1")
    monkeypatch.setenv("SIGNOZ_ENDPOINT", "http://localhost:4318")
    monkeypatch.setenv("OTEL_SKIP_ENDPOINT_PROBE", "1")

    from importlib import reload

    import arka.telemetry.tracing as tracing

    reload(tracing)

    from arka.telemetry.signoz_demo import demo_all

    assert demo_all(synthetic=True) == 0


def test_signoz_alert_rule_loads():
    from arka.telemetry.signoz_alerts import list_alert_rules, load_alert_rule

    assert "agent-error-spike" in list_alert_rules()
    rule = load_alert_rule("agent-error-spike")
    assert rule["alertType"] == "TRACES_BASED_ALERT"
    assert rule["version"] == "v5"
    queries = rule["condition"]["compositeQuery"]["queries"]
    assert queries[0]["spec"]["signal"] == "traces"
    assert "service.name = 'arka'" in queries[0]["spec"]["filter"]["expression"]


def test_signoz_alert_create_dry_run():
    from arka.telemetry.signoz_alerts import create_alert_rule, list_alert_rules

    assert "llm-p99-latency" in list_alert_rules()
    result = create_alert_rule("agent-error-spike", dry_run=True)
    assert result["dry_run"] is True
    assert result["alert"] == "Arka agent error spike"


def test_llm_obs_synthetic_usage():
    from arka.telemetry.llm_obs import estimate_cost_usd, synthetic_usage_attrs

    attrs = synthetic_usage_attrs(input_tokens=1000, output_tokens=200, model_id="gemini-2.0-flash", ttft_ms=400)
    assert attrs["gen_ai.usage.total_tokens"] == 1200
    assert attrs["arka.llm.ttft_ms"] == 400
    assert estimate_cost_usd(model_id="gemini-2.0-flash", input_tokens=1_000_000, output_tokens=0) > 0


def test_exception_attributes_include_stacktrace():
    from arka.telemetry.tracing import exception_attributes

    try:
        raise ValueError("demo failure for SigNoz")
    except ValueError as exc:
        attrs = exception_attributes(exc)
    assert attrs["exception.type"] == "ValueError"
    assert "demo failure" in attrs["exception.message"]
    assert "ValueError" in attrs["exception.stacktrace"]
    assert "raise ValueError" in attrs["exception.stacktrace"]


def test_span_records_exception_automatically(monkeypatch):
    monkeypatch.setenv("OTEL_TRACES_ENABLED", "1")
    monkeypatch.setenv("SIGNOZ_ENDPOINT", "http://localhost:4318")
    monkeypatch.setenv("OTEL_SKIP_ENDPOINT_PROBE", "1")

    from importlib import reload

    import arka.telemetry.tracing as tracing

    reload(tracing)

    recorded: list[Exception] = []

    def _capture_record(span_obj, exc, *, message=None):
        recorded.append(exc)

    monkeypatch.setattr(tracing, "record_exception", _capture_record)

    with pytest.raises(RuntimeError, match="boom"):
        with tracing.span("arka.test.auto_exception"):
            raise RuntimeError("boom")

    assert recorded
    assert isinstance(recorded[0], RuntimeError)


def test_mark_error_with_exc_records_stack():
    from arka.telemetry.tracing import _NoOpSpan, mark_error

    mark_error(_NoOpSpan(), "failed", exc=RuntimeError("rate limited"))


def test_emit_log_includes_trace_context(monkeypatch):
    monkeypatch.setenv("OTEL_TRACES_ENABLED", "1")
    monkeypatch.setenv("SIGNOZ_ENDPOINT", "http://localhost:4318")
    monkeypatch.setenv("OTEL_SKIP_ENDPOINT_PROBE", "1")

    from importlib import reload

    import arka.telemetry.tracing as tracing

    reload(tracing)

    emitted: list[dict] = []

    class _FakeLogger:
        def emit(self, record):
            attrs = dict(getattr(record, "attributes", {}) or {})
            emitted.append(
                {
                    "trace_id": attrs.get("trace_id"),
                    "span_id": attrs.get("span_id"),
                    "body": record.body,
                    "context": getattr(record, "context", None),
                }
            )

    import arka.telemetry._otlp as otlp
    import arka.telemetry.logs as logs_mod

    otlp.reset_collector_probe_cache()
    logs_mod._logger = _FakeLogger()
    logs_mod._initialized = True
    logs_mod._logger_provider = object()
    logs_mod._log_processor = None

    from arka.telemetry import span
    from arka.telemetry.logs import emit_log

    with span("arka.test.trace_log"):
        emit_log("correlated log", attributes={"arka.event": "test"})

    assert emitted
    assert emitted[0]["trace_id"]
    assert emitted[0]["span_id"]
    assert emitted[0]["context"] is not None


def test_cursor_setup_lines():
    from arka.telemetry.signoz_cursor_setup import cursor_setup_lines

    lines = dict(part.split("\t", 1) for part in cursor_setup_lines() if "\t" in part)
    assert "cursor_marketplace" in lines
    assert "github.com/SigNoz/agent-skills" in lines["cursor_marketplace"]
    assert lines["cursor_setup_cmd"] == "/signoz-mcp-setup http://localhost:8000/mcp"


def test_route_decision_attributes(monkeypatch):
    monkeypatch.setenv("OTEL_TRACES_ENABLED", "1")
    monkeypatch.setenv("SIGNOZ_ENDPOINT", "http://localhost:4318")
    monkeypatch.setenv("OTEL_SKIP_ENDPOINT_PROBE", "1")
    monkeypatch.setenv("ROUTE_MODE", "symbolic_only")

    from importlib import reload

    import arka.telemetry.tracing as tracing

    reload(tracing)

    from arka.router import route

    result = route("help")
    assert result is not None
    assert "help" in result.skill
