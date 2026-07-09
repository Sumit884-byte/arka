"""OpenTelemetry logs — structured agent events to SigNoz."""

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

_logger_provider: Any | None = None
_logger: Any | None = None
_initialized = False
_log_processor: Any | None = None


def logs_enabled() -> bool:
    return signal_enabled("logs")


def _severity_number(level: str):
    from opentelemetry._logs import SeverityNumber

    mapping = {
        "debug": SeverityNumber.DEBUG,
        "info": SeverityNumber.INFO,
        "warn": SeverityNumber.WARN,
        "warning": SeverityNumber.WARN,
        "error": SeverityNumber.ERROR,
    }
    return mapping.get(level.lower(), SeverityNumber.INFO)


def _setup() -> None:
    global _logger_provider, _logger, _initialized, _log_processor
    if _initialized:
        return
    _initialized = True
    if not logs_enabled():
        return

    endpoint = signal_endpoint("logs")
    if not collector_available(endpoint):
        return

    suppress_otel_exporter_logging()

    try:
        from opentelemetry._logs import set_logger_provider
        from opentelemetry.exporter.otlp.proto.http._log_exporter import OTLPLogExporter
        from opentelemetry.sdk._logs import LoggerProvider, LoggingHandler
        from opentelemetry.sdk._logs.export import BatchLogRecordProcessor
    except ImportError:
        return

    timeout = otlp_export_timeout_seconds()
    _logger_provider = LoggerProvider(resource=build_resource())
    _log_processor = BatchLogRecordProcessor(
        OTLPLogExporter(endpoint=endpoint, timeout=timeout),
        export_timeout_millis=int(timeout * 1000),
        schedule_delay_millis=5000,
    )
    _logger_provider.add_log_record_processor(_log_processor)
    set_logger_provider(_logger_provider)
    _logger = _logger_provider.get_logger("arka.agent", "0.1.0")

    handler = LoggingHandler(level=0, logger_provider=_logger_provider)
    try:
        import logging

        logging.getLogger("arka").addHandler(handler)
        logging.getLogger("arka").setLevel(logging.INFO)
    except Exception:
        pass

    atexit.register(shutdown_logs)


def emit_log(
    message: str,
    *,
    level: str = "info",
    attributes: dict[str, Any] | None = None,
) -> None:
    _setup()
    if _logger is None:
        return
    body = message[:2000]
    attrs = {k: str(v)[:500] for k, v in (attributes or {}).items() if v is not None}

    trace_id_hex = ""
    span_id_hex = ""
    otel_context = None
    try:
        from opentelemetry import context as otel_context_api
        from opentelemetry import trace

        otel_context = otel_context_api.get_current()
        span_context = trace.get_current_span().get_span_context()
        if span_context.is_valid:
            trace_id_hex = format(span_context.trace_id, "032x")
            span_id_hex = format(span_context.span_id, "016x")
            attrs.setdefault("trace_id", trace_id_hex)
            attrs.setdefault("span_id", span_id_hex)
    except Exception:
        pass

    try:
        from opentelemetry._logs import LogRecord

        _logger.emit(
            LogRecord(
                body=body,
                severity_number=_severity_number(level),
                severity_text=level.upper(),
                attributes=attrs,
                context=otel_context,
            )
        )
    except Exception:
        pass


def logs_status() -> dict[str, str]:
    _setup()
    return {
        "logs_enabled": str(logs_enabled()).lower(),
        "logs_configured": str(_logger is not None).lower(),
        "logs_endpoint": signal_endpoint("logs") if logs_enabled() else "",
    }


def shutdown_logs() -> None:
    global _logger_provider, _logger, _log_processor
    timeout = shutdown_timeout_millis()
    if _log_processor is not None:
        try:
            if hasattr(_log_processor, "force_flush"):
                _log_processor.force_flush(timeout_millis=timeout)
            if hasattr(_log_processor, "shutdown"):
                _log_processor.shutdown()
        except Exception:
            pass
        _log_processor = None
    if _logger_provider is None:
        return
    try:
        if hasattr(_logger_provider, "force_flush"):
            _logger_provider.force_flush(timeout_millis=timeout)
        if hasattr(_logger_provider, "shutdown"):
            _logger_provider.shutdown()
    except Exception:
        pass
    _logger_provider = None
    _logger = None
