from __future__ import annotations

from arka.telemetry import observability_doctor


def test_doctor_reports_disabled_otel(monkeypatch):
    monkeypatch.delenv("OTEL_SERVICE_NAME", raising=False)
    monkeypatch.delenv("OTEL_EXPORTER_OTLP_ENDPOINT", raising=False)
    payload = observability_doctor.collect()
    assert payload["service"] == "arka"
    assert payload["tracing"]["enabled"] == "false"
    assert any("Enable OTEL_TRACES_ENABLED" in item for item in payload["recommendations"])


def test_doctor_json_cli_is_read_only(capsys, monkeypatch):
    monkeypatch.setenv("OTEL_TRACES_ENABLED", "1")
    monkeypatch.setenv("OTEL_EXPORTER_OTLP_ENDPOINT", "http://collector:4318")
    assert observability_doctor.main(["--json"]) == 0
    output = capsys.readouterr().out
    assert '"service": "arka"' in output
    assert "collector:4318" in output
