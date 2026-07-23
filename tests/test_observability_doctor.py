from __future__ import annotations

from arka.telemetry import observability_doctor


def test_doctor_reports_disabled_otel(monkeypatch):
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    monkeypatch.delenv("OTEL_TRACES_ENABLED", raising=False)
    monkeypatch.delenv("SIGNOZ_ENDPOINT", raising=False)
    monkeypatch.delenv("SIGNOZ_TRACES", raising=False)

    from importlib import reload

    import arka.telemetry._otlp as otlp
    import arka.telemetry.tracing as tracing

    reload(otlp)
    reload(tracing)

    payload = observability_doctor.collect()
    assert payload["service"] == "arka"
    assert payload["tracing"]["enabled"] == "false"
    assert "verification" in payload
    assert payload["verification"]["traces_skill"]
    assert any("Enable OTEL_TRACES_ENABLED" in item for item in payload["recommendations"])


def test_doctor_json_cli_is_read_only(capsys, monkeypatch):
    monkeypatch.setenv("OTEL_TRACES_ENABLED", "1")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
    assert observability_doctor.main(["--json"]) == 0
    output = capsys.readouterr().out
    assert '"service": "arka"' in output
    assert "collector:4318" in output


def test_observability_skill_strips_doctor_subcommand(monkeypatch, capsys):
    monkeypatch.setenv("OTEL_TRACES_ENABLED", "0")
    from arka.dispatch import run_skill

    assert run_skill("observability doctor") == 0
    output = capsys.readouterr().out
    assert "service\tarka" in output


def test_observability_agent_subcommand(monkeypatch, capsys):
    monkeypatch.setenv("OTEL_TRACES_ENABLED", "0")
    assert observability_doctor.main(["agent"]) == 0
    output = capsys.readouterr().out
    assert "service\tarka" in output
    assert "verify_traces_mcp_server" in output


def test_collect_agent_includes_guide():
    payload = observability_doctor.collect_agent()
    assert payload["service"] == "arka"
    assert "guide" in payload
    assert payload["guide"]["title"]
