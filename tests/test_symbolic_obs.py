from __future__ import annotations


def test_route_offline_extras_with_rule_returns_handler_name():
    from arka.routing.symbolic import route_offline_extras, route_offline_extras_with_rule

    matched = route_offline_extras_with_rule("help")
    assert matched is not None
    skill, rule = matched
    assert skill == "help"
    assert rule == "route_help"
    assert route_offline_extras("help") == skill


def test_execution_kind_deterministic_for_password():
    from arka.telemetry.symbolic_obs import execution_kind, llm_used_for_execution

    assert execution_kind(head="generate_password", route_decision="symbolic") == "deterministic"
    assert not llm_used_for_execution(head="generate_password", route_decision="symbolic")


def test_execution_kind_llm_for_web_answer():
    from arka.telemetry.symbolic_obs import execution_kind, llm_used_for_execution

    assert execution_kind(head="web_answer", route_decision="symbolic") == "llm_skill"
    assert llm_used_for_execution(head="web_answer", route_decision="symbolic")


def test_finish_route_obs_sets_context_and_metrics(monkeypatch):
    import time

    monkeypatch.setenv("OTEL_TRACES_ENABLED", "1")
    monkeypatch.setenv("SIGNOZ_ENDPOINT", "http://localhost:4318")
    monkeypatch.setenv("OTEL_SKIP_ENDPOINT_PROBE", "1")

    from importlib import reload

    import arka.telemetry._otlp as otlp
    import arka.telemetry.metrics as metrics_mod
    from arka.router import Route
    from arka.telemetry.symbolic_obs import finish_route_obs, get_route_context
    from arka.telemetry.tracing import _NoOpSpan

    otlp.reset_collector_probe_cache()
    reload(metrics_mod)

    recorded: list[tuple[str, dict]] = []

    class _FakeCounter:
        def add(self, amount, attrs=None):
            recorded.append(("routing", dict(attrs or {})))

    metrics_mod._meter = object()
    metrics_mod._initialized = True
    metrics_mod._counters = {"routing": _FakeCounter()}

    route = Route("generate_password list", source="offline", rule="route_password")
    start = time.perf_counter()
    finish_route_obs(_NoOpSpan(), route, decision="symbolic", start=start)

    ctx = get_route_context()
    assert ctx is not None
    assert ctx["rule"] == "route_password"
    assert ctx["decision"] == "symbolic"
    assert route.decision == "symbolic"
    assert any(item[1].get("arka.execution.kind") == "deterministic" for item in recorded)
    assert any(item[1].get("arka.llm.used") is False for item in recorded)
    assert any(item[1].get("arka.route.rule") == "route_password" for item in recorded)


def test_finish_skill_dispatch_records_execution_kind(monkeypatch):
    import time

    monkeypatch.setenv("OTEL_TRACES_ENABLED", "1")
    monkeypatch.setenv("SIGNOZ_ENDPOINT", "http://localhost:4318")
    monkeypatch.setenv("OTEL_SKIP_ENDPOINT_PROBE", "1")

    from importlib import reload

    import arka.telemetry._otlp as otlp
    import arka.telemetry.metrics as metrics_mod
    from arka.router import Route
    from arka.telemetry.skill_obs import finish_skill_dispatch
    from arka.telemetry.symbolic_obs import set_route_context
    from arka.telemetry.tracing import _NoOpSpan

    otlp.reset_collector_probe_cache()
    reload(metrics_mod)

    recorded: list[tuple[str, dict]] = []

    class _FakeCounter:
        def add(self, amount, attrs=None):
            recorded.append(("skill", dict(attrs or {})))

    class _FakeHistogram:
        def record(self, value, attrs=None):
            recorded.append(("hist", dict(attrs or {})))

    metrics_mod._meter = object()
    metrics_mod._initialized = True
    metrics_mod._counters = {"skill_dispatch": _FakeCounter()}
    metrics_mod._histograms = {"skill_duration": _FakeHistogram()}

    set_route_context(Route("help", source="offline", rule="route_help"), decision="symbolic")
    start = time.perf_counter()
    finish_skill_dispatch(_NoOpSpan(), skill="help", exit_code=0, start=start, skill_line="help")

    assert any(item[1].get("arka.execution.kind") == "deterministic" for item in recorded)
    assert any(item[1].get("arka.llm.used") is False for item in recorded)
