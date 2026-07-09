"""Shared OTLP endpoint + resource helpers for traces, metrics, and logs."""

from __future__ import annotations

import logging
import os
import socket
from urllib.parse import urlparse

_fast_shutdown = False
_warned_unreachable: set[str] = set()
_collector_available: bool | None = None


def _truthy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"1", "true", "yes", "on"}


def _falsy(name: str) -> bool:
    return os.environ.get(name, "").strip().lower() in {"0", "false", "no", "off"}


def otel_sdk_disabled() -> bool:
    """Master kill switch — OTEL_SDK_DISABLED=true disables all OTLP export."""
    return _truthy("OTEL_SDK_DISABLED")


def otel_base_url() -> str:
    base = os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip()
    if not base:
        base = os.environ.get("SIGNOZ_ENDPOINT", "http://127.0.0.1:4318").strip()
    return base.rstrip("/")


def signal_endpoint(signal: str) -> str:
    """Resolve OTLP HTTP endpoint for traces, metrics, or logs."""
    env_key = f"OTEL_EXPORTER_OTLP_{signal.upper()}_ENDPOINT"
    explicit = os.environ.get(env_key, "").strip()
    if explicit:
        url = explicit.rstrip("/")
        if not url.endswith(f"/v1/{signal}"):
            if url.endswith("/v1"):
                return f"{url}/{signal}"
            return f"{url}/v1/{signal}"
        return url
    return f"{otel_base_url()}/v1/{signal}"


def telemetry_master_enabled() -> bool:
    """Opt-in only: explicit trace flag or OTLP endpoint env — default OFF."""
    if otel_sdk_disabled():
        return False
    if _falsy("OTEL_TRACES_ENABLED") or _falsy("SIGNOZ_TRACES"):
        return False
    if _truthy("OTEL_TRACES_ENABLED") or _truthy("SIGNOZ_TRACES"):
        return True
    if os.environ.get("OTEL_EXPORTER_OTLP_ENDPOINT", "").strip():
        return True
    return False


def signal_enabled(signal: str) -> bool:
    """Whether a signal is enabled. Metrics/logs default on when tracing is on."""
    if otel_sdk_disabled():
        return False
    flag = f"OTEL_{signal.upper()}_ENABLED"
    legacy = {"traces": "SIGNOZ_TRACES", "metrics": "SIGNOZ_METRICS", "logs": "SIGNOZ_LOGS"}.get(signal, "")
    if _falsy(flag) or (legacy and _falsy(legacy)):
        return False
    if _truthy(flag) or (legacy and _truthy(legacy)):
        return True
    if signal == "traces":
        return telemetry_master_enabled()
    if signal in {"metrics", "logs"}:
        return telemetry_master_enabled()
    return False


def otlp_export_timeout_seconds() -> float:
    raw = os.environ.get("OTEL_EXPORTER_OTLP_TIMEOUT", "2").strip()
    try:
        return max(0.5, min(float(raw), 30.0))
    except ValueError:
        return 2.0


def otlp_export_timeout_millis() -> int:
    return int(otlp_export_timeout_seconds() * 1000)


def shutdown_timeout_millis() -> int:
    return 0 if _fast_shutdown else min(otlp_export_timeout_millis(), 500)


def request_fast_shutdown(*_args: object) -> None:
    global _fast_shutdown
    _fast_shutdown = True


def register_fast_shutdown_handlers() -> None:
    import signal

    for sig in (signal.SIGINT, signal.SIGTERM):
        try:
            previous = signal.getsignal(sig)

            def _handler(signum, frame, _prev=previous):
                request_fast_shutdown()
                if callable(_prev) and _prev not in (
                    signal.SIG_DFL,
                    signal.SIG_IGN,
                ):
                    _prev(signum, frame)
                elif _prev is signal.default_int_handler:
                    raise KeyboardInterrupt

            signal.signal(sig, _handler)
        except (ValueError, OSError):
            pass


def suppress_otel_exporter_logging() -> None:
    for name in (
        "opentelemetry.exporter.otlp.proto.http",
        "opentelemetry.exporter.otlp.proto.http.trace_exporter",
        "opentelemetry.exporter.otlp.proto.http.metric_exporter",
        "opentelemetry.exporter.otlp.proto.http._log_exporter",
        "opentelemetry.sdk._shared_internal",
        "urllib3.connectionpool",
    ):
        logging.getLogger(name).setLevel(logging.CRITICAL)


def _host_port_from_url(url: str) -> tuple[str, int]:
    parsed = urlparse(url)
    host = parsed.hostname or "127.0.0.1"
    if parsed.port is not None:
        return host, parsed.port
    if parsed.scheme == "https":
        return host, 443
    return host, 4318


def collector_available(endpoint_url: str | None = None) -> bool:
    """Probe OTLP collector once per process; cache result."""
    global _collector_available
    if otel_sdk_disabled():
        _collector_available = False
        return False
    if _collector_available is not None:
        return _collector_available
    url = endpoint_url or signal_endpoint("traces")
    if endpoint_reachable(url):
        _collector_available = True
        return True
    warn_endpoint_unreachable(url)
    _collector_available = False
    return False


def reset_collector_probe_cache() -> None:
    global _collector_available
    _collector_available = None


def endpoint_reachable(endpoint_url: str, *, timeout: float | None = None) -> bool:
    """Quick TCP probe — skip OTLP setup when collector is down."""
    if _truthy("OTEL_SKIP_ENDPOINT_PROBE"):
        return True
    if timeout is None:
        timeout = min(otlp_export_timeout_seconds(), 1.0)
    try:
        host, port = _host_port_from_url(endpoint_url)
        with socket.create_connection((host, port), timeout=timeout):
            return True
    except OSError:
        return False


def warn_endpoint_unreachable(endpoint_url: str) -> None:
    if otel_sdk_disabled():
        return
    if endpoint_url in _warned_unreachable:
        return
    _warned_unreachable.add(endpoint_url)
    import sys

    print(
        "arka telemetry: OTLP collector unreachable at "
        f"{endpoint_url} — export disabled for this process "
        "(set OTEL_SDK_DISABLED=true to silence, or start SigNoz)",
        file=sys.stderr,
    )


def build_resource():
    from opentelemetry.sdk.resources import Resource

    service = os.environ.get("OTEL_SERVICE_NAME", "arka").strip() or "arka"
    return Resource.create(
        {
            "service.name": service,
            "service.namespace": os.environ.get("OTEL_SERVICE_NAMESPACE", "arka-agent"),
        }
    )
