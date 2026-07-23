from __future__ import annotations


def test_record_routing_and_skill_metrics(monkeypatch):
    monkeypatch.setenv("OTEL_TRACES_ENABLED", "1")
    monkeypatch.setenv("SIGNOZ_ENDPOINT", "http://localhost:4318")
    monkeypatch.setenv("OTEL_SKIP_ENDPOINT_PROBE", "1")

    from importlib import reload

    import arka.telemetry._otlp as otlp
    import arka.telemetry.metrics as metrics_mod

    otlp.reset_collector_probe_cache()
    reload(metrics_mod)

    recorded: list[tuple[str, dict]] = []

    class _FakeCounter:
        def __init__(self, name: str):
            self.name = name

        def add(self, amount, attrs=None):
            recorded.append((self.name, dict(attrs or {})))

    class _FakeHistogram:
        def __init__(self, name: str):
            self.name = name

        def record(self, value, attrs=None):
            recorded.append((self.name, {"value": value, **dict(attrs or {})}))

    metrics_mod._meter = object()
    metrics_mod._initialized = True
    metrics_mod._counters = {
        "routing": _FakeCounter("routing"),
        "skill_dispatch": _FakeCounter("skill_dispatch"),
        "llm_failover": _FakeCounter("llm_failover"),
    }
    metrics_mod._histograms = {"skill_duration": _FakeHistogram("skill_duration")}

    metrics_mod.record_routing_decision(decision="symbolic", source="offline", latency_ms=1.5)
    metrics_mod.record_skill_dispatch(skill="help", duration_ms=42.0, exit_code=0)
    metrics_mod.record_llm_failover(provider="gemini", model="flash", attempts=3, from_provider="groq")

    assert any(item[1].get("arka.route.decision") == "symbolic" for item in recorded)
    assert any(item[1].get("arka.skill.name") == "help" for item in recorded)
    assert any(item[1].get("value") == 42.0 for item in recorded)
    assert any(item[1].get("gen_ai.provider.name") == "gemini" for item in recorded)


def test_finish_skill_dispatch_noop_span():
    import time

    from arka.telemetry.skill_obs import finish_skill_dispatch
    from arka.telemetry.tracing import _NoOpSpan

    start = time.perf_counter()
    elapsed = finish_skill_dispatch(
        _NoOpSpan(),
        skill="help",
        exit_code=0,
        start=start,
        skill_line="help",
    )
    assert 0 <= elapsed < 5000


def test_current_trace_ids_empty_without_span():
    from arka.telemetry.logs import current_trace_ids

    assert current_trace_ids() == ("", "")


def test_telemetry_hint_when_endpoint_without_traces(monkeypatch, capsys):
    from importlib import reload

    import arka.telemetry._otlp as otlp
    import arka.telemetry.telemetry_hints as hints

    monkeypatch.delenv("OTEL_TRACES_ENABLED", raising=False)
    monkeypatch.setenv("SIGNOZ_ENDPOINT", "http://localhost:4318")
    monkeypatch.setenv("ARKA_TELEMETRY_HINT", "1")
    reload(otlp)
    hints.reset_telemetry_hints_for_tests()

    hints.maybe_emit_telemetry_setup_hint()
    err = capsys.readouterr().err
    assert "OTEL_TRACES_ENABLED=1" in err

    hints.maybe_emit_telemetry_setup_hint()
    assert capsys.readouterr().err == ""


def test_agent_observability_guide():
    from arka.telemetry.telemetry_hints import agent_observability_guide

    guide = agent_observability_guide()
    assert guide["env"]["OTEL_TRACES_ENABLED"] == "1"
    assert guide["env"]["SIGNOZ_AUTOSTART"] == "1"
    assert "arka signoz autostart install" in guide["commands"]
    assert "arka signoz demo" in guide["commands"]
    assert "arka.mcp.server.tool" in guide["sigNoz_filters"]["mcp_server"]


def test_skill_dispatch_failure_alert_loads():
    from arka.telemetry.signoz_alerts import list_alert_rules, load_alert_rule

    assert "skill-dispatch-failures" in list_alert_rules()
    rule = load_alert_rule("skill-dispatch-failures")
    assert "arka.skill." in rule["condition"]["compositeQuery"]["queries"][0]["spec"]["filter"]["expression"]
