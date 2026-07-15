"""Local SigNoz/OpenTelemetry diagnostics.

This command is deliberately read-only.  It checks Arka's configuration and
instrumentation without pretending that a configured endpoint has received a
span; use ``arka signoz demo`` and the SigNoz UI to verify ingestion.
"""

from __future__ import annotations

import argparse
import json
import os
from typing import Any


def collect() -> dict[str, Any]:
    from arka.telemetry.tracing import trace_status

    status = trace_status()
    endpoint = str(status.get("endpoint") or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", ""))
    result: dict[str, Any] = {
        "service": os.environ.get("OTEL_SERVICE_NAME", "arka"),
        "endpoint": endpoint or None,
        "tracing": status,
        "signoz_mcp": {
            "url_configured": bool(os.environ.get("SIGNOZ_MCP_URL")),
            "api_key_configured": bool(os.environ.get("SIGNOZ_API_KEY") or os.environ.get("SIGNOZ_ACCESS_TOKEN")),
        },
        "recommendations": [],
    }
    recommendations: list[str] = result["recommendations"]
    if status.get("enabled") != "true":
        recommendations.append("Enable OTEL_TRACES_ENABLED=1 (and metrics/logs as needed).")
    if status.get("enabled") == "true" and status.get("configured") != "true":
        recommendations.append("Install observability extras: pip install 'arka-agent[observability]'.")
    if not endpoint:
        recommendations.append("Set OTEL_EXPORTER_OTLP_ENDPOINT to your SigNoz OTLP endpoint.")
    recommendations.append("Send a smoke trace with: arka signoz demo; then verify service.name=arka in SigNoz.")
    return result


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose Arka SigNoz instrumentation (read-only)")
    parser.add_argument("--json", action="store_true", help="emit machine-readable diagnostics")
    args = parser.parse_args(argv)
    payload = collect()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"service\t{payload['service']}")
        print(f"otlp_endpoint\t{payload['endpoint'] or 'not_set'}")
        for key, value in payload["tracing"].items():
            print(f"otel_{key}\t{value}")
        for item in payload["recommendations"]:
            print(f"recommendation\t{item}")
    return 0


if __name__ == "__main__":  # pragma: no cover - convenience for local diagnosis
    raise SystemExit(main())
