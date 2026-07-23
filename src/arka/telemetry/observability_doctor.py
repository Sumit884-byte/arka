"""Local SigNoz/OpenTelemetry diagnostics.

This command is deliberately read-only.  It checks Arka's configuration and
instrumentation without pretending that a configured endpoint has received a
span; use ``arka signoz demo`` and the SigNoz UI to verify ingestion.
"""

from __future__ import annotations

import argparse
import json
import os
import sys
from typing import Any


def _otel_packages_installed() -> bool:
    try:
        import opentelemetry.sdk.trace  # noqa: F401

        return True
    except ImportError:
        return False


def collect() -> dict[str, Any]:
    from arka.telemetry._otlp import (
        _truthy,
        endpoint_reachable,
        otel_base_url,
        signal_enabled,
        telemetry_master_enabled,
    )
    from arka.telemetry.tracing import trace_status

    status = trace_status()
    endpoint = str(status.get("endpoint") or os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "") or otel_base_url())
    traces_env_on = _truthy("OTEL_TRACES_ENABLED") or _truthy("SIGNOZ_TRACES")
    traces_on = status.get("enabled") == "true"
    collector_ok = False
    if endpoint and traces_on:
        collector_ok = endpoint_reachable(endpoint)

    packages_ok = _otel_packages_installed()
    try:
        from arka.telemetry.mcp_obs import mcp_server_log_status, mcp_status_lines

        mcp_log = mcp_server_log_status()
        signoz_mcp_lines = dict(mcp_status_lines())
    except ImportError:
        mcp_log = {"log_path": "", "log_exists": False, "log_bytes": 0}
        signoz_mcp_lines = {}

    arka_self_mcp: dict[str, Any] = {"doctor": "skipped"}
    try:
        from arka.integrations.mcp_server import doctor as mcp_doctor

        text, code = mcp_doctor(timeout=3.0)
        arka_self_mcp = {
            "doctor_exit": code,
            "summary": "ok" if code == 0 else "error",
            "detail": text.splitlines()[0] if text else "",
        }
    except Exception as exc:
        arka_self_mcp = {"doctor": "error", "error": str(exc)[:200]}

    result: dict[str, Any] = {
        "service": os.environ.get("OTEL_SERVICE_NAME", "arka").strip() or "arka",
        "endpoint": endpoint or None,
        "tracing": status,
        "collector_reachable": collector_ok,
        "packages_installed": packages_ok,
        "signals": {
            "traces": traces_on,
            "metrics": signal_enabled("metrics"),
            "logs": signal_enabled("logs"),
        },
        "otel_env": {
            "OTEL_TRACES_ENABLED": os.environ.get("OTEL_TRACES_ENABLED", ""),
            "OTEL_EXPORTER_OTLP_ENDPOINT": os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", ""),
            "SIGNOZ_ENDPOINT": os.environ.get("SIGNOZ_ENDPOINT", ""),
            "OTEL_SDK_DISABLED": os.environ.get("OTEL_SDK_DISABLED", ""),
        },
        "signoz_mcp": {
            "url_configured": bool(os.environ.get("SIGNOZ_MCP_URL")),
            "api_key_configured": bool(
                os.environ.get("SIGNOZ_API_KEY") or os.environ.get("SIGNOZ_ACCESS_TOKEN")
            ),
            **signoz_mcp_lines,
        },
        "mcp_server": {
            **mcp_log,
            "self_check": arka_self_mcp,
        },
        "verification": {
            "traces_skill": "service.name = 'arka' AND name LIKE 'arka.skill.%'",
            "traces_route": "service.name = 'arka' AND name = 'arka.route'",
            "traces_llm": "service.name = 'arka' AND name = 'arka.llm.attempt'",
            "metrics_routing": "metric_name = 'arka.routing.decisions'",
            "metrics_skill": "metric_name = 'arka.skill.duration'",
            "metrics_mcp": "metric_name = 'arka.mcp.ops'",
            "traces_mcp_server": "service.name = 'arka' AND name = 'arka.mcp.server.tool'",
            "traces_mcp_client": "service.name = 'arka' AND name = 'arka.mcp.call_tool'",
            "logs_correlation": "logs with trace_id attribute matching active trace",
        },
        "recommendations": [],
    }
    recommendations: list[str] = result["recommendations"]

    has_endpoint_env = bool(
        os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
        or os.environ.get("SIGNOZ_ENDPOINT", "").strip()
    )
    if traces_env_on and not packages_ok:
        recommendations.append("Install observability extras: pip install 'arka-agent[observability]'.")
    elif not telemetry_master_enabled() and has_endpoint_env and not traces_env_on:
        recommendations.append(
            "OTLP endpoint env detected but tracing is off — set OTEL_TRACES_ENABLED=1."
        )
    elif status.get("enabled") != "true" and not traces_env_on:
        recommendations.append("Enable OTEL_TRACES_ENABLED=1 (and metrics/logs as needed).")
    if traces_env_on and packages_ok and status.get("configured") != "true" and not traces_on:
        recommendations.append(
            "Tracing is configured in env but disabled in-process — start SigNoz or set OTEL_SKIP_ENDPOINT_PROBE=1."
        )
    if not endpoint:
        recommendations.append("Set OTEL_EXPORTER_OTLP_ENDPOINT or SIGNOZ_ENDPOINT to your SigNoz OTLP base URL.")
    if traces_on and endpoint and not collector_ok:
        recommendations.append(
            f"Collector unreachable at {endpoint} — start SigNoz or fix the endpoint before expecting data."
        )
    if not mcp_log.get("log_exists"):
        recommendations.append(
            "No MCP JSONL log yet — call an Arka MCP tool; logs land at "
            f"{mcp_log.get('log_path') or 'config/logs/mcp.jsonl'}."
        )
    if arka_self_mcp.get("summary") == "error":
        recommendations.append(
            "Arka self-MCP doctor failed — run: arka mcp doctor (check launch command and PYTHONPATH)."
        )
    try:
        from arka.telemetry.signoz_autostart import autostart_status as signoz_autostart_status

        autostart = signoz_autostart_status()
        result["signoz_autostart"] = {
            "config_enabled": autostart.get("config_enabled"),
            "config_detail": autostart.get("config_detail"),
            "installed": autostart.get("installed"),
            "loaded": autostart.get("loaded"),
            "backend": autostart.get("backend"),
        }
        if autostart.get("config_enabled") == "false":
            recommendations.append(
                "SigNoz login autostart is disabled-by-config — set SIGNOZ_AUTOSTART=1 "
                "(or unset) in .env to allow `arka signoz autostart install`."
            )
        elif autostart.get("installed") != "true" and autostart.get("supported") == "true":
            recommendations.append(
                "SigNoz stack is not configured to start at login — run: arka signoz autostart install "
                "(or set SIGNOZ_AUTOSTART=0 to keep off)."
            )
    except ImportError:
        pass
    recommendations.append("Send a smoke trace with: arka signoz demo; then verify service.name=arka in SigNoz.")
    recommendations.append(
        "Filter skill spans: name starts with arka.skill. — check arka.skill.duration_ms and arka.skill.exit_code."
    )
    return result


def collect_agent() -> dict[str, Any]:
    """Agent-focused health: OTEL, MCP server/client, LLM providers, skill verification."""
    base = collect()
    agent: dict[str, Any] = {
        "service": base.get("service"),
        "endpoint": base.get("endpoint"),
        "collector_reachable": base.get("collector_reachable"),
        "packages_installed": base.get("packages_installed"),
        "tracing": base.get("tracing"),
        "signals": base.get("signals"),
        "mcp_server": base.get("mcp_server"),
        "signoz_mcp": base.get("signoz_mcp"),
        "verification": base.get("verification"),
        "llm": {},
        "mcp_client": {},
        "recommendations": list(base.get("recommendations") or []),
    }
    try:
        from arka.llm.fallback import llm_doctor_lines, provider_available, provider_specs

        agent["llm"] = {
            "configured_providers": [
                spec.slug for spec in provider_specs() if provider_available(spec.slug)
            ],
            "doctor_lines": llm_doctor_lines(),
        }
    except ImportError:
        pass
    try:
        from arka.telemetry.mcp_obs import mcp_status_lines

        agent["mcp_client"] = dict(mcp_status_lines())
    except ImportError:
        pass
    try:
        from arka.telemetry.telemetry_hints import agent_observability_guide

        agent["guide"] = agent_observability_guide()
    except ImportError:
        pass
    if not agent["llm"].get("configured_providers"):
        agent["recommendations"].append(
            "No LLM providers configured — live agent traces need at least one API key or local Ollama/vLLM."
        )
    agent["recommendations"].append(
        "Generate MCP server spans: call any arka_* MCP tool; filter name = 'arka.mcp.server.tool'."
    )
    return agent


def _print_agent_report(payload: dict[str, Any]) -> None:
    print(f"service\t{payload.get('service')}")
    print(f"otlp_endpoint\t{payload.get('endpoint') or 'not_set'}")
    print(f"collector_reachable\t{str(payload.get('collector_reachable', False)).lower()}")
    tracing = payload.get("tracing") or {}
    for key, value in tracing.items():
        print(f"otel_{key}\t{value}")
    llm = payload.get("llm") or {}
    providers = llm.get("configured_providers") or []
    print(f"llm_providers\t{','.join(providers) if providers else 'none'}")
    for line in llm.get("doctor_lines") or []:
        print(f"llm_detail\t{line.strip()}")
    mcp_server = payload.get("mcp_server") or {}
    print(f"mcp_log_path\t{mcp_server.get('log_path', '')}")
    print(f"mcp_log_exists\t{str(bool(mcp_server.get('log_exists'))).lower()}")
    self_check = mcp_server.get("self_check") or {}
    if self_check:
        print(f"mcp_self_check\t{self_check.get('summary', self_check.get('doctor', 'unknown'))}")
    for key, value in (payload.get("mcp_client") or {}).items():
        print(f"mcp_client_{key}\t{value}")
    for key, value in (payload.get("signoz_mcp") or {}).items():
        print(f"signoz_mcp_{key}\t{value}")
    for key, value in (payload.get("verification") or {}).items():
        print(f"verify_{key}\t{value}")
    for item in payload.get("recommendations") or []:
        print(f"recommendation\t{item}")
    try:
        from arka.telemetry.telemetry_hints import print_agent_observability_guide

        print("guide_start")
        print_agent_observability_guide(file=sys.stdout)
        print("guide_end")
    except ImportError:
        pass


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Diagnose Arka SigNoz instrumentation (read-only)")
    sub = parser.add_subparsers(dest="cmd")
    sub.add_parser("agent", help="MCP/LLM/skill health for AI agent observability")
    parser.add_argument("--json", action="store_true", help="emit machine-readable diagnostics")
    args = parser.parse_args(argv)
    if getattr(args, "cmd", None) == "agent":
        payload = collect_agent()
        if args.json:
            print(json.dumps(payload, indent=2, sort_keys=True))
        else:
            _print_agent_report(payload)
        return 0
    payload = collect()
    if args.json:
        print(json.dumps(payload, indent=2, sort_keys=True))
    else:
        print(f"service\t{payload['service']}")
        print(f"otlp_endpoint\t{payload['endpoint'] or 'not_set'}")
        print(f"collector_reachable\t{str(payload['collector_reachable']).lower()}")
        print(f"packages_installed\t{str(payload['packages_installed']).lower()}")
        for key, value in payload["tracing"].items():
            print(f"otel_{key}\t{value}")
        for signal, enabled in payload["signals"].items():
            print(f"signal_{signal}\t{str(enabled).lower()}")
        mcp_server = payload.get("mcp_server") or {}
        if mcp_server:
            print(f"mcp_log_path\t{mcp_server.get('log_path', '')}")
            print(f"mcp_log_exists\t{str(bool(mcp_server.get('log_exists'))).lower()}")
            self_check = mcp_server.get("self_check") or {}
            if self_check:
                print(f"mcp_self_check\t{self_check.get('summary', self_check.get('doctor', 'unknown'))}")
        for key, value in payload["verification"].items():
            print(f"verify_{key}\t{value}")
        for item in payload["recommendations"]:
            print(f"recommendation\t{item}")
        autostart = payload.get("signoz_autostart") or {}
        if autostart:
            print(f"signoz_autostart_config_enabled\t{autostart.get('config_enabled', '')}")
            print(f"signoz_autostart_config_detail\t{autostart.get('config_detail', '')}")
            print(f"signoz_autostart_installed\t{autostart.get('installed', '')}")
            print(f"signoz_autostart_loaded\t{autostart.get('loaded', '')}")
    return 0


if __name__ == "__main__":  # pragma: no cover - convenience for local diagnosis
    raise SystemExit(main())
